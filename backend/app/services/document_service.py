"""
services/document_service.py — Document ingestion and processing orchestration.

Phase 2: Coordinates extraction of PDF pages and database persistence.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DocumentNotFoundError,
    DocumentProcessingError,
    DocumentStillProcessingError,
    InvalidPDFError,
    PageNotFoundError,
)
from app.db.models import Document, DocumentPage, ProcessingStatus
from app.ingestion.extractor import ExtractedPage, PDFExtractor

logger = logging.getLogger("fintel.ingestion")


class DocumentService:
    """Service layer managing document processing and page queries."""

    def __init__(self, extractor: PDFExtractor | None = None) -> None:
        self.extractor = extractor or PDFExtractor()

    async def process_document(
        self,
        document_id: str,
        db: AsyncSession,
    ) -> Document:
        """Process a document by extracting all pages and saving them.

        Lifecycle:
            UPLOADED -> EXTRACTING -> READY (or FAILED on error)

        Args:
            document_id: UUID string of the document to process.
            db: Database async session.

        Returns:
            The updated Document instance.
        """
        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if doc is None:
            raise DocumentNotFoundError(f"Document {document_id!r} not found.")

        if doc.processing_status == ProcessingStatus.EXTRACTING.value:
            raise DocumentStillProcessingError(
                f"Document {document_id!r} is currently being processed."
            )

        # Transition to EXTRACTING
        doc.processing_status = ProcessingStatus.EXTRACTING.value
        doc.processing_error = None
        await db.commit()
        await db.refresh(doc)

        logger.info("Starting processing for document | id=%s file=%s", doc.id, doc.original_filename)

        try:
            # Check file exists on disk
            file_path = Path(doc.file_path)
            if not file_path.exists():
                raise InvalidPDFError(f"Stored file not found on disk at {file_path}")

            # Extract pages via PyMuPDF
            extracted_pages: list[ExtractedPage] = self.extractor.extract_pages(file_path)

            # Clear any existing pages for idempotency / re-processing
            await db.execute(
                delete(DocumentPage).where(DocumentPage.document_id == document_id)
            )

            # Add new document pages
            page_records = [
                DocumentPage(
                    document_id=doc.id,
                    page_number=page.page_number,
                    raw_text=page.raw_text,
                    cleaned_text=page.cleaned_text,
                    is_empty=page.is_empty,
                    char_count=page.char_count,
                )
                for page in extracted_pages
            ]
            db.add_all(page_records)

            # Update document state
            doc.page_count = len(extracted_pages)
            doc.processing_status = ProcessingStatus.READY.value
            doc.processing_error = None

            await db.commit()
            await db.refresh(doc)

            logger.info(
                "Document processing complete | id=%s pages=%d",
                doc.id,
                doc.page_count,
            )
            return doc

        except Exception as exc:
            logger.exception("Document processing failed | id=%s: %s", doc.id, exc)
            await db.rollback()

            # Record failure status in DB
            doc.processing_status = ProcessingStatus.FAILED.value
            doc.processing_error = str(exc)
            await db.commit()

            if isinstance(exc, (InvalidPDFError, DocumentProcessingError)):
                raise
            raise DocumentProcessingError(f"Processing failed for document {document_id}: {exc}") from exc

    async def get_pages(
        self,
        document_id: str,
        db: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[DocumentPage], int]:
        """Fetch paginated pages for a document and the total page count.

        Args:
            document_id: UUID of document.
            db: Database async session.
            limit: Maximum pages to return.
            offset: Page offset.

        Returns:
            Tuple of (list of DocumentPage, total count).
        """
        # Ensure document exists
        result = await db.execute(select(Document).where(Document.id == document_id))
        if result.scalar_one_or_none() is None:
            raise DocumentNotFoundError(f"Document {document_id!r} not found.")

        # Total count
        count_res = await db.execute(
            select(func.count(DocumentPage.id)).where(DocumentPage.document_id == document_id)
        )
        total = count_res.scalar_one()

        # Query pages
        query = (
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number.asc())
            .offset(offset)
            .limit(limit)
        )
        pages_res = await db.execute(query)
        pages = list(pages_res.scalars().all())

        return pages, total

    async def get_page(
        self,
        document_id: str,
        page_number: int,
        db: AsyncSession,
    ) -> DocumentPage:
        """Fetch a specific page of a document.

        Args:
            document_id: UUID of document.
            page_number: 1-indexed page number.
            db: Database async session.

        Returns:
            DocumentPage instance.
        """
        # Ensure document exists
        result = await db.execute(select(Document).where(Document.id == document_id))
        if result.scalar_one_or_none() is None:
            raise DocumentNotFoundError(f"Document {document_id!r} not found.")

        page_res = await db.execute(
            select(DocumentPage).where(
                DocumentPage.document_id == document_id,
                DocumentPage.page_number == page_number,
            )
        )
        page = page_res.scalar_one_or_none()
        if page is None:
            raise PageNotFoundError(
                f"Page {page_number} not found for document {document_id!r}."
            )
        return page
