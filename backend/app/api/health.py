"""
api/health.py — Health check endpoints.

Two endpoints:
    GET /health       — lightweight liveness probe (is the app running?)
    GET /health/db    — readiness probe (can we reach the database + pgvector?)

These are used by:
- Docker Compose health checks
- Monitoring tools / load balancers
- Manual developer verification after startup

/health intentionally does NOT hit the database — it should always return 200
if the process is alive, even if the database is temporarily unreachable.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.config import get_settings, Settings
from app.db.session import get_db

logger = logging.getLogger("fintel")
router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    summary="Liveness check",
    description="Returns 200 if the application process is running.",
)
async def health(settings: Settings = Depends(get_settings)) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ok",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
        },
    )


@router.get(
    "/health/db",
    summary="Database readiness check",
    description="Verifies PostgreSQL connectivity and confirms pgvector is installed.",
)
async def health_db(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Check database connectivity and pgvector extension availability.

    pgvector check: we query pg_extension to verify the extension is installed.
    This catches the common mistake of running standard Postgres without pgvector.
    """
    try:
        # Basic connectivity check
        await db.execute(text("SELECT 1"))

        # pgvector extension check
        result = await db.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        pgvector_installed = result.scalar() == "vector"

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ok",
                "database": "connected",
                "pgvector": pgvector_installed,
            },
        )
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "database": "unreachable",
                "pgvector": False,
                "detail": str(exc),
            },
        )
