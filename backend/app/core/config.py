"""
core/config.py — Application configuration via environment variables.

All settings are read from a .env file (or real environment variables).
Pydantic Settings validates types at startup so misconfiguration fails fast
instead of silently producing wrong behavior at runtime.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration.

    Fields map directly to environment variables.  The names are intentionally
    verbose so the .env.example is self-documenting.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    APP_NAME: str = "Financial Document Intelligence Platform"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/fintel"
    # Synchronous URL is required by Alembic (migrations run synchronously)
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/fintel"

    # ── File Storage ──────────────────────────────────────────────────────────
    UPLOAD_DIR: Path = Path("uploads")
    MAX_UPLOAD_SIZE_MB: int = 100

    # ── LLM (Ollama / local runtime) ──────────────────────────────────────────
    LLM_BASE_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "gemma3:4b"
    LLM_TIMEOUT_SECONDS: int = 120

    # ── Embeddings ────────────────────────────────────────────────────────────
    EMBEDDING_BASE_URL: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "nomic-embed-text"
    # Dimension MUST match the pgvector column.
    # nomic-embed-text → 768, all-MiniLM-L6-v2 → 384
    EMBEDDING_DIMENSION: int = 768

    # ── RAG ───────────────────────────────────────────────────────────────────
    RAG_TOP_K: int = 5
    RAG_CHUNK_SIZE: int = 600       # approximate words per chunk
    RAG_CHUNK_OVERLAP: int = 80     # approximate words of overlap

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator("UPLOAD_DIR", mode="before")
    @classmethod
    def coerce_upload_dir(cls, v: str | Path) -> Path:
        return Path(v)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton.

    Use this as a FastAPI dependency:
        settings: Settings = Depends(get_settings)
    Or import directly for non-route usage.
    """
    return Settings()
