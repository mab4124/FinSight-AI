"""
api/documents.py — Document upload, processing, and management endpoints.

Phase 1: Upload, list, get status, delete.
Phase 2: PDF extraction triggered via POST /documents/{id}/process, page listing/retrieval.
Phase 3: Full pipeline (extract → chunk → embed) and chunk listing endpoint.

Security considerations:
- MIME type validation (must be application/pdf or equivalent)
- File size limit enforced before reading the full file
- Filename is sanitized; original name is stored but never used as file path
- Storage path uses UUID to prevent path traversal
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response
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
from app.services.document_service import DocumentService

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


class DocumentProcessResponse(BaseModel):
    id: str
    status: str
    page_count: int | None
    chunk_count: int | None
    message: str


class DocumentPageResponse(BaseModel):
    id: str
    document_id: str
    page_number: int
    raw_text: str | None
    cleaned_text: str | None
    is_empty: bool
    char_count: int | None

    model_config = {"from_attributes": True}


class DocumentPagesListResponse(BaseModel):
    document_id: str
    total_pages: int
    pages: list[DocumentPageResponse]


class DocumentChunkResponse(BaseModel):
    id: str
    document_id: str
    page_number: int
    chunk_index: int
    content: str
    token_count: int | None
    has_embedding: bool

    model_config = {"from_attributes": True}


class DocumentChunksListResponse(BaseModel):
    document_id: str
    total_chunks: int
    chunks: list[DocumentChunkResponse]


# ── Helper ────────────────────────────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    """Remove dangerous characters from a filename."""
    import re
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
    if content_type not in _ALLOWED_MIME and not (file.filename or "").lower().endswith(".pdf"):
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


@router.post(
    "/{document_id}/process",
    response_model=DocumentProcessResponse,
    summary="Run the full ingestion pipeline: extract pages, chunk, and generate embeddings",
    description=(
        "Runs all three ingestion stages in sequence:\n"
        "1. **Extract** — parse PDF page-by-page with PyMuPDF.\n"
        "2. **Chunk** — split cleaned text into overlapping word-window chunks.\n"
        "3. **Embed** — generate a 768-dim vector per chunk via Ollama nomic-embed-text.\n\n"
        "If Ollama is unavailable, chunks are saved without embeddings and the "
        "document is still marked READY so text search remains functional."
    ),
)
async def process_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> DocumentProcessResponse:
    from sqlalchemy import func as _func
    from app.db.models import DocumentChunk as _DocumentChunk

    service = DocumentService()
    doc = await service.process_document(document_id, db)

    # Count persisted chunks for the response
    chunk_count_res = await db.execute(
        _func.count(_DocumentChunk.id).filter(_DocumentChunk.document_id == document_id)
    )
    # SQLAlchemy scalar for a plain func.count expression
    try:
        chunk_count: int | None = chunk_count_res.scalar_one()
    except Exception:
        chunk_count = None

    return DocumentProcessResponse(
        id=doc.id,
        status=doc.processing_status,
        page_count=doc.page_count,
        chunk_count=chunk_count,
        message=(
            f"Pipeline complete: {doc.page_count or 0} pages extracted, "
            f"{chunk_count or 0} chunks embedded."
        ),
    )


@router.get(
    "/{document_id}/pages",
    response_model=DocumentPagesListResponse,
    summary="Get extracted pages for a document",
)
async def get_document_pages(
    document_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DocumentPagesListResponse:
    service = DocumentService()
    pages, total = await service.get_pages(document_id, db, limit=limit, offset=offset)
    return DocumentPagesListResponse(
        document_id=document_id,
        total_pages=total,
        pages=[DocumentPageResponse.model_validate(p) for p in pages],
    )


@router.get(
    "/{document_id}/pages/{page_number}",
    response_model=DocumentPageResponse,
    summary="Get a specific extracted page from a document",
)
async def get_document_page(
    document_id: str,
    page_number: int,
    db: AsyncSession = Depends(get_db),
) -> DocumentPageResponse:
    service = DocumentService()
    page = await service.get_page(document_id, page_number, db)
    return DocumentPageResponse.model_validate(page)


@router.get(
    "/{document_id}/chunks",
    response_model=DocumentChunksListResponse,
    summary="List text chunks for a document",
    description="Returns the chunks generated from the document's pages. "
                "Each chunk includes its page number, text content, and whether an "
                "embedding vector was successfully stored.",
)
async def get_document_chunks(
    document_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DocumentChunksListResponse:
    service = DocumentService()
    chunks, total = await service.get_chunks(document_id, db, limit=limit, offset=offset)
    return DocumentChunksListResponse(
        document_id=document_id,
        total_chunks=total,
        chunks=[
            DocumentChunkResponse(
                id=c.id,
                document_id=c.document_id,
                page_number=c.page_number,
                chunk_index=c.chunk_index,
                content=c.content,
                token_count=c.token_count,
                has_embedding=c.embedding is not None,
            )
            for c in chunks
        ],
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
