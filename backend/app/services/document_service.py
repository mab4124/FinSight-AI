"""
services/document_service.py — Document ingestion and processing orchestration.

Phase 2: Coordinates extraction of PDF pages and database persistence.
Phase 3: Extends pipeline with chunking and embedding generation.

Pipeline lifecycle:
    UPLOADED → EXTRACTING → CHUNKING → EMBEDDING → READY
                                                  ↘ FAILED (at any stage)
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    DocumentNotFoundError,
    DocumentProcessingError,
    DocumentStillProcessingError,
    EmbeddingUnavailableError,
    InvalidPDFError,
    PageNotFoundError,
)
from app.db.models import Document, DocumentChunk, DocumentPage, ProcessingStatus
from app.embeddings.local_embeddings import OllamaEmbeddingProvider
from app.ingestion.chunker import TextChunker
from app.ingestion.extractor import ExtractedPage, PDFExtractor

logger = logging.getLogger("fintel.ingestion")


class DocumentService:
    """Service layer managing document processing and page queries."""

    def __init__(
        self,
        extractor: PDFExtractor | None = None,
        chunker: TextChunker | None = None,
        embedder: OllamaEmbeddingProvider | None = None,
    ) -> None:
        settings = get_settings()
        self.extractor = extractor or PDFExtractor()
        self.chunker = chunker or TextChunker(
            chunk_size=settings.RAG_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,
        )
        self.embedder = embedder or OllamaEmbeddingProvider(
            base_url=settings.EMBEDDING_BASE_URL,
            model=settings.EMBEDDING_MODEL,
            expected_dim=settings.EMBEDDING_DIMENSION,
        )

    # ── Main pipeline ─────────────────────────────────────────────────────────

    async def process_document(
        self,
        document_id: str,
        db: AsyncSession,
    ) -> Document:
        """Run the full ingestion pipeline for a document.

        Stages:
            1. Extract pages from PDF (PyMuPDF).
            2. Persist DocumentPage rows.
            3. Chunk cleaned page text.
            4. Generate embeddings for each chunk via Ollama.
            5. Persist DocumentChunk rows (content + embedding vector).
            6. Mark document READY.

        Lifecycle transitions:
            UPLOADED → EXTRACTING → CHUNKING → EMBEDDING → READY
                                                          ↘ FAILED

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

        # Reset to EXTRACTING
        doc.processing_status = ProcessingStatus.EXTRACTING.value
        doc.processing_error = None
        await db.commit()
        await db.refresh(doc)

        logger.info(
            "Starting pipeline for document | id=%s file=%s",
            doc.id,
            doc.original_filename,
        )

        try:
            # ── Stage 1: Extract pages ─────────────────────────────────────────
            file_path = Path(doc.file_path)
            if not file_path.exists():
                raise InvalidPDFError(f"Stored file not found on disk at {file_path}")

            extracted_pages: list[ExtractedPage] = self.extractor.extract_pages(file_path)

            # Clear any existing pages for idempotency
            await db.execute(
                delete(DocumentPage).where(DocumentPage.document_id == document_id)
            )

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

            doc.page_count = len(extracted_pages)
            await db.commit()

            logger.info(
                "Extraction complete | id=%s pages=%d", doc.id, doc.page_count
            )

            # ── Stage 2: Chunk ────────────────────────────────────────────────
            doc.processing_status = ProcessingStatus.CHUNKING.value
            await db.commit()

            # Build (page_number, cleaned_text) pairs, skip empty pages
            page_pairs = [
                (p.page_number, p.cleaned_text)
                for p in extracted_pages
                if not p.is_empty and p.cleaned_text
            ]

            chunks = self.chunker.chunk_pages(document_id=doc.id, pages=page_pairs)
            logger.info(
                "Chunking complete | id=%s chunks=%d", doc.id, len(chunks)
            )

            # ── Stage 3: Embed ────────────────────────────────────────────────
            doc.processing_status = ProcessingStatus.EMBEDDING.value
            await db.commit()

            # Clear existing chunks for idempotency
            await db.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )

            if chunks:
                chunk_texts = [c.content for c in chunks]
                try:
                    embeddings = await self.embedder.embed_batch(chunk_texts)
                except EmbeddingUnavailableError as exc:
                    # Embedding unavailable: persist chunks without vectors so
                    # the document is not stuck in FAILED and can be re-embedded
                    # once Ollama is available.
                    logger.warning(
                        "Embedding unavailable — saving chunks without vectors | id=%s | %s",
                        doc.id,
                        exc,
                    )
                    embeddings = [None] * len(chunks)  # type: ignore[list-item]

                chunk_records = [
                    DocumentChunk(
                        document_id=doc.id,
                        page_number=chunk.page_number,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        embedding=embedding,
                        token_count=chunk.token_count,
                    )
                    for chunk, embedding in zip(chunks, embeddings)
                ]
                db.add_all(chunk_records)

                logger.info(
                    "Embedding complete | id=%s chunks=%d embedded=%d",
                    doc.id,
                    len(chunks),
                    sum(1 for e in embeddings if e is not None),
                )

            # ── Stage 4: Mark READY ───────────────────────────────────────────
            doc.processing_status = ProcessingStatus.READY.value
            doc.processing_error = None
            await db.commit()
            await db.refresh(doc)

            logger.info(
                "Pipeline complete | id=%s status=READY pages=%d chunks=%d",
                doc.id,
                doc.page_count,
                len(chunks),
            )
            return doc

        except Exception as exc:
            logger.exception(
                "Document pipeline failed | id=%s stage=%s: %s",
                doc.id,
                doc.processing_status,
                exc,
            )
            await db.rollback()

            doc.processing_status = ProcessingStatus.FAILED.value
            doc.processing_error = str(exc)
            await db.commit()

            if isinstance(exc, (InvalidPDFError, DocumentProcessingError)):
                raise
            raise DocumentProcessingError(
                f"Processing failed for document {document_id}: {exc}"
            ) from exc

    # ── Page queries ───────────────────────────────────────────────────────────

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

    # ── Chunk queries ──────────────────────────────────────────────────────────

    async def get_chunks(
        self,
        document_id: str,
        db: AsyncSession,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[DocumentChunk], int]:
        """Fetch paginated chunks for a document.

        Args:
            document_id: UUID of document.
            db: Database async session.
            limit: Maximum chunks to return.
            offset: Chunk offset.

        Returns:
            Tuple of (list of DocumentChunk, total count).
        """
        result = await db.execute(select(Document).where(Document.id == document_id))
        if result.scalar_one_or_none() is None:
            raise DocumentNotFoundError(f"Document {document_id!r} not found.")

        count_res = await db.execute(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.document_id == document_id
            )
        )
        total = count_res.scalar_one()

        chunks_res = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .offset(offset)
            .limit(limit)
        )
        chunks = list(chunks_res.scalars().all())
        return chunks, total
