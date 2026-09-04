"""
db/session.py — SQLAlchemy async engine and session factory.

We use SQLAlchemy's async API (via asyncpg) so database I/O never blocks
FastAPI's event loop.  This allows the application to handle concurrent
requests efficiently — important when processing large PDF uploads.

Key concepts:
- AsyncEngine: manages the connection pool to PostgreSQL.
- AsyncSessionLocal: a session factory — each request gets its own session.
- get_db(): a FastAPI dependency that yields a session and ensures it is
  properly closed even if an exception occurs.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger("fintel.db")

settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────────────
# pool_pre_ping=True: tests connections before use (guards against stale connections)
# echo=False: don't log every SQL statement in production
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG,
)

# ── Session Factory ───────────────────────────────────────────────────────────
# expire_on_commit=False: prevent SQLAlchemy from expiring attributes after
# commit, which would trigger lazy loads that fail in async context.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── FastAPI Dependency ────────────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for the duration of a single request.

    Usage in a route:
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
