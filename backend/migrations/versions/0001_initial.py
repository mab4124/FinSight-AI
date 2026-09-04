"""Initial schema: companies, documents, document_pages, document_chunks, financial_metrics

Revision ID: 0001_initial
Revises: 
Create Date: 2026-09-05

This migration:
1. Enables the pgvector extension.
2. Creates all application tables.

The VECTOR(768) dimension matches nomic-embed-text output.
If you switch embedding models, create a new migration to ALTER the column.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension — must run before any VECTOR column is created
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── companies ─────────────────────────────────────────────────────────────
    op.create_table(
        "companies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=True),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_companies_ticker", "companies", ["ticker"])
    op.create_unique_constraint(
        "uq_company_name_ticker", "companies", ["name", "ticker"]
    )

    # ── documents ─────────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False, server_default="ANNUAL_REPORT"),
        sa.Column("fiscal_year", sa.Integer, nullable=True),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("processing_status", sa.String(20), nullable=False, server_default="UPLOADED"),
        sa.Column("processing_error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_documents_company_id", "documents", ["company_id"])
    op.create_index("ix_documents_processing_status", "documents", ["processing_status"])

    # ── document_pages ────────────────────────────────────────────────────────
    op.create_table(
        "document_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("cleaned_text", sa.Text, nullable=True),
        sa.Column("is_empty", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("char_count", sa.Integer, nullable=True),
    )
    op.create_index("ix_document_pages_document_id", "document_pages", ["document_id"])
    op.create_unique_constraint(
        "uq_page_per_document", "document_pages", ["document_id", "page_number"]
    )

    # ── document_chunks ───────────────────────────────────────────────────────
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        # VECTOR(768): pgvector column for semantic similarity search
        # Dimension matches nomic-embed-text; change requires a new migration
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_unique_constraint(
        "uq_chunk_index_per_document", "document_chunks", ["document_id", "chunk_index"]
    )

    # ── financial_metrics ─────────────────────────────────────────────────────
    op.create_table(
        "financial_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("metric_value", sa.Float, nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("period", sa.String(50), nullable=True),
        sa.Column("source_page", sa.Integer, nullable=True),
        sa.Column("source_text", sa.Text, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_financial_metrics_document_id", "financial_metrics", ["document_id"])
    op.create_index("ix_financial_metrics_metric_name", "financial_metrics", ["metric_name"])


def downgrade() -> None:
    op.drop_table("financial_metrics")
    op.drop_table("document_chunks")
    op.drop_table("document_pages")
    op.drop_table("documents")
    op.drop_table("companies")
    op.execute("DROP EXTENSION IF EXISTS vector")
