"""
db/models.py — SQLAlchemy ORM models.

These define the relational schema for the application.
Alembic reads these models to generate migration files.

Schema overview:
    companies           — company registry (Apple, Microsoft, etc.)
    documents           — uploaded PDF files, one per annual report / filing
    document_pages      — raw + cleaned text, one row per PDF page
    document_chunks     — text chunks with vector embeddings for RAG
    financial_metrics   — extracted structured financial metrics with provenance

Design decisions:
- UUIDs as primary keys: no sequential ID exposure, safe for public APIs.
- Timestamps with timezone: consistent across deployments.
- ProcessingStatus enum: tracks the pipeline stage, enables reliable
  status polling from the frontend.
- VECTOR(n) from pgvector: the dimension must match EMBEDDING_DIMENSION in
  config.  Mismatch causes insertion errors caught at runtime.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Base ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class ProcessingStatus(str, Enum):
    """Lifecycle states of a document through the ingestion pipeline.

    Transitions:
        UPLOADED → EXTRACTING → CHUNKING → EMBEDDING → READY
                                                     ↘ FAILED (at any stage)
    """
    UPLOADED = "UPLOADED"
    EXTRACTING = "EXTRACTING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    READY = "READY"
    FAILED = "FAILED"


class DocumentType(str, Enum):
    ANNUAL_REPORT = "ANNUAL_REPORT"
    EARNINGS_RELEASE = "EARNINGS_RELEASE"
    SEC_10K = "SEC_10K"
    SEC_10Q = "SEC_10Q"
    INVESTOR_PRESENTATION = "INVESTOR_PRESENTATION"
    OTHER = "OTHER"


# ── companies ─────────────────────────────────────────────────────────────────

class Company(Base):
    """A company whose financial documents are stored in the platform."""

    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    # Relationships
    documents: Mapped[list[Document]] = relationship(
        "Document", back_populates="company", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("name", "ticker", name="uq_company_name_ticker"),)

    def __repr__(self) -> str:
        return f"<Company id={self.id!r} name={self.name!r} ticker={self.ticker!r}>"


# ── documents ─────────────────────────────────────────────────────────────────

class Document(Base):
    """A single uploaded financial PDF, associated with a company."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    company_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Original filename as uploaded by the user (sanitized before storage)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    # Internal storage path (UUID-based, not user-controlled)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(50), default=DocumentType.ANNUAL_REPORT.value, nullable=False
    )
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    processing_status: Mapped[str] = mapped_column(
        String(20),
        default=ProcessingStatus.UPLOADED.value,
        nullable=False,
        index=True,
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    # Relationships
    company: Mapped[Company] = relationship("Company", back_populates="documents")
    pages: Mapped[list[DocumentPage]] = relationship(
        "DocumentPage", back_populates="document", cascade="all, delete-orphan"
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )
    metrics: Mapped[list[FinancialMetric]] = relationship(
        "FinancialMetric", back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Document id={self.id!r} "
            f"filename={self.original_filename!r} "
            f"status={self.processing_status!r}>"
        )


# ── document_pages ────────────────────────────────────────────────────────────

class DocumentPage(Base):
    """Raw and cleaned text for a single PDF page.

    Storing pages separately provides:
    1. Page-level provenance for citations.
    2. Ability to re-chunk or re-clean without re-extracting PDFs.
    3. Debugging visibility into extraction quality page-by-page.
    """

    __tablename__ = "document_pages"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Raw text as extracted from PDF (may contain noise)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cleaned text after preprocessing (used for chunking)
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True if the page had no machine-readable text (e.g., scanned image)
    is_empty: Mapped[bool] = mapped_column(default=False, nullable=False)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    document: Mapped[Document] = relationship("Document", back_populates="pages")

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_page_per_document"),
    )

    def __repr__(self) -> str:
        return f"<DocumentPage doc={self.document_id!r} page={self.page_number}>"


# ── document_chunks ───────────────────────────────────────────────────────────

class DocumentChunk(Base):
    """A text chunk with its vector embedding — the core RAG retrieval unit.

    Each chunk stores:
    - The text content used in retrieval prompts.
    - The embedding vector used for similarity search.
    - Its source page, enabling accurate citations.

    Embedding dimension is set at table-creation time via Alembic.
    Changing it requires a migration (ALTER COLUMN) and re-embedding all docs.
    """

    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # VECTOR(768) — dimension must match EMBEDDING_DIMENSION config
    # Stored as a pgvector column; supports cosine similarity search
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    # Relationships
    document: Mapped[Document] = relationship("Document", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint(
            "document_id", "chunk_index", name="uq_chunk_index_per_document"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk doc={self.document_id!r} "
            f"page={self.page_number} idx={self.chunk_index}>"
        )


# ── financial_metrics ─────────────────────────────────────────────────────────

class FinancialMetric(Base):
    """A single extracted financial metric with full provenance.

    Every metric includes its source page and the text snippet that
    supports the extracted value.  This prevents blindly trusting the LLM
    and allows human verification of extracted figures.

    Example row:
        metric_name  = "revenue"
        metric_value = 391035.0
        unit         = "millions"
        currency     = "USD"
        period       = "FY2024"
        source_page  = 37
        source_text  = "Net sales were $391.0 billion..."
    """

    __tablename__ = "financial_metrics"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    period: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Confidence is optional; populated when the LLM signals uncertainty
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Flagged rows need human review before being trusted
    needs_review: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    # Relationships
    document: Mapped[Document] = relationship("Document", back_populates="metrics")

    def __repr__(self) -> str:
        return (
            f"<FinancialMetric doc={self.document_id!r} "
            f"metric={self.metric_name!r} value={self.metric_value}>"
        )
