"""
embeddings/base.py — Abstract EmbeddingProvider interface.

Why an abstraction?
    The rest of the application (chunker, retriever, RAG pipeline) should not
    know or care whether embeddings come from Ollama, sentence-transformers,
    or any future provider.  This interface is the only contract they depend on.

Current implementation status:
    Phase 1: Abstract base class only.
    Phase 4: OllamaEmbeddingProvider will implement this using nomic-embed-text.

Embedding dimension:
    Must match the VECTOR(n) column in document_chunks.
    Configurable via EMBEDDING_DIMENSION in .env.
    Changing dimension requires a database migration and re-embedding all docs.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Abstract base for all embedding providers.

    Implementors must be safe to call concurrently — embeddings are generated
    during document ingestion and query time.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """The fixed vector dimension this provider produces.

        Must match the pgvector column dimension.
        """
        ...

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text string.

        Args:
            text: Input text to embed.  Should be under the model's token limit.

        Returns:
            A list of floats of length self.dimension.

        Raises:
            EmbeddingUnavailableError: If the embedding service is unreachable.
            VectorDimensionMismatchError: If returned dimension differs from expected.
        """
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Prefer this over repeated embed_text() calls — providers may
        batch requests internally for efficiency.

        Args:
            texts: List of input texts.

        Returns:
            List of embedding vectors, one per input text, in the same order.
        """
        ...
