"""
api/documents.py — Document upload and management endpoints.

Phase 1: Upload, list, get status, delete.
Phase 2: PDF extraction is triggered via POST /documents/{id}/process.

Security considerations (from the master spec):
- MIME type validation (must be application/pdf or equivalent)
- File size limit enforced before reading the full file
- Filename is sanitized; original name is stored but never used as file path
- Storage path uses UUID to prevent path traversal
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    CompanyNotFoundError,
    DocumentNotFoundError,
    FileTooLargeError,
    InvalidPDFError,
)
from app.db.models import Company, Document, DocumentType, ProcessingStatus
from app.db.session import get_db

logger = logging.getLogger("fintel")
router = APIRouter(prefix="/documents", tags=["Documents"])

# Allowed MIME types for PDFs
_ALLOWED_MIME = {"application/pdf", "application/x-pdf"}


# ── Response Schemas ──────────────────────────────────────────────────────────

class DocumentResponse(BaseModel):
    id: str
    company_id: str
    company_name: str
    original_filename: str
    document_type: str
    fiscal_year: int | None
    page_count: int | None
    file_size_bytes: int | None
    processing_status: str
    processing_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Helper ────────────────────────────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    """Remove dangerous characters from a filename."""
    import re
    # Keep only alphanumeric, dots, dashes, underscores
    safe = re.sub(r"[^\w.\-]", "_", name)
    return safe[:200]  # cap length


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a financial PDF document",
)
async def upload_document(
    file: UploadFile = File(..., description="Financial PDF file"),
    company_id: str = Form(..., description="UUID of the company this document belongs to"),
    document_type: str = Form(default=DocumentType.ANNUAL_REPORT.value),
    fiscal_year: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentResponse:
    # 1. Validate company exists
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if company is None:
        raise CompanyNotFoundError(f"Company {company_id!r} not found.")

    # 2. Validate MIME type
    content_type = file.content_type or ""
    if content_type not in _ALLOWED_MIME and not file.filename.lower().endswith(".pdf"):
        raise InvalidPDFError(
            f"Unsupported file type: {content_type!r}. Only PDF files are accepted."
        )

    # 3. Read content and check file size
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise FileTooLargeError(
            f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit "
            f"({len(content) / 1_048_576:.1f} MB uploaded)."
        )

    # 4. Verify PDF magic bytes (%PDF-)
    if not content.startswith(b"%PDF"):
        raise InvalidPDFError("File does not appear to be a valid PDF (missing %PDF header).")

    # 5. Create storage directory and persist file with UUID-based path
    import uuid as _uuid
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    internal_id = str(_uuid.uuid4())
    safe_name = _sanitize_filename(file.filename or "document.pdf")
    storage_path = settings.UPLOAD_DIR / f"{internal_id}_{safe_name}"
    storage_path.write_bytes(content)

    # 6. Create database record
    doc = Document(
        company_id=company_id,
        original_filename=file.filename or "document.pdf",
        file_path=str(storage_path),
        document_type=document_type,
        fiscal_year=fiscal_year,
        file_size_bytes=len(content),
        processing_status=ProcessingStatus.UPLOADED.value,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    logger.info(
        "Document uploaded | id=%s company=%s filename=%s size_kb=%.1f",
        doc.id,
        company.name,
        doc.original_filename,
        len(content) / 1024,
    )

    return DocumentResponse(
        id=doc.id,
        company_id=doc.company_id,
        company_name=company.name,
        original_filename=doc.original_filename,
        document_type=doc.document_type,
        fiscal_year=doc.fiscal_year,
        page_count=doc.page_count,
        file_size_bytes=doc.file_size_bytes,
        processing_status=doc.processing_status,
        processing_error=doc.processing_error,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get(
    "",
    response_model=list[DocumentResponse],
    summary="List all documents",
)
async def list_documents(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentResponse]:
    query = select(Document, Company).join(Company, Document.company_id == Company.id)
    if company_id:
        query = query.where(Document.company_id == company_id)
    query = query.order_by(Document.created_at.desc())
    result = await db.execute(query)
    rows = result.all()
    return [
        DocumentResponse(
            id=doc.id,
            company_id=doc.company_id,
            company_name=comp.name,
            original_filename=doc.original_filename,
            document_type=doc.document_type,
            fiscal_year=doc.fiscal_year,
            page_count=doc.page_count,
            file_size_bytes=doc.file_size_bytes,
            processing_status=doc.processing_status,
            processing_error=doc.processing_error,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        for doc, comp in rows
    ]


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get a document by ID",
)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    result = await db.execute(
        select(Document, Company)
        .join(Company, Document.company_id == Company.id)
        .where(Document.id == document_id)
    )
    row = result.one_or_none()
    if row is None:
        raise DocumentNotFoundError(f"Document {document_id!r} not found.")
    doc, comp = row
    return DocumentResponse(
        id=doc.id,
        company_id=doc.company_id,
        company_name=comp.name,
        original_filename=doc.original_filename,
        document_type=doc.document_type,
        fiscal_year=doc.fiscal_year,
        page_count=doc.page_count,
        file_size_bytes=doc.file_size_bytes,
        processing_status=doc.processing_status,
        processing_error=doc.processing_error,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and its associated data",
)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise DocumentNotFoundError(f"Document {document_id!r} not found.")

    # Remove stored file
    try:
        Path(doc.file_path).unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Could not delete file %s: %s", doc.file_path, exc)

    await db.delete(doc)
    await db.commit()
    logger.info("Document deleted | id=%s", document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
