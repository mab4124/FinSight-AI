"""app/embeddings/__init__.py"""
from app.embeddings.base import EmbeddingProvider
from app.embeddings.local_embeddings import OllamaEmbeddingProvider

__all__ = ["EmbeddingProvider", "OllamaEmbeddingProvider"]
