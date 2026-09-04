"""
main.py — FastAPI application entry point.

Responsibilities:
- Create the FastAPI app with metadata.
- Configure CORS (so the React frontend can call the API).
- Register all API routers under /api/v1/.
- Register exception handlers.
- Configure logging at startup.
- Run database table creation on first launch (dev convenience).

Lifespan context manager:
    FastAPI uses @asynccontextmanager lifespan for startup/shutdown logic.
    This replaces the deprecated @app.on_event("startup") pattern.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import companies, documents, health, query
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown logic."""
    configure_logging(debug=settings.DEBUG)
    logger = logging.getLogger("fintel")
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Database URL: %s", settings.DATABASE_URL.split("@")[-1])  # hide credentials
    logger.info("LLM model: %s @ %s", settings.LLM_MODEL, settings.LLM_BASE_URL)
    logger.info("Embedding model: %s (dim=%d)", settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSION)

    # Ensure upload directory exists
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    yield  # Application runs here

    logger.info("Shutting down %s", settings.APP_NAME)


# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "A RAG-based financial document intelligence platform. "
        "Upload annual reports and financial PDFs, then ask natural-language "
        "questions answered with grounded citations from your documents."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ───────────────────────────────────────────────────────────────────────
# Allows the React dev server (localhost:5173) and production frontend to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Exception Handlers ────────────────────────────────────────────────────────
register_exception_handlers(app)

# ── Routers ───────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(health.router, prefix=API_PREFIX)
app.include_router(companies.router, prefix=API_PREFIX)
app.include_router(documents.router, prefix=API_PREFIX)
app.include_router(query.router, prefix=API_PREFIX)
