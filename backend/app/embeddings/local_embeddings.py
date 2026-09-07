"""
embeddings/local_embeddings.py — Ollama-backed embedding provider.

Phase 3: Implements EmbeddingProvider using Ollama's /api/embeddings endpoint.

Why Ollama for embeddings?
    The user already has Ollama installed and has nomic-embed-text available
    (768-dimensional, strong on retrieval tasks).  Using Ollama keeps everything
    local — no external API keys, no internet dependency, no data leaving the
    machine.

Model: nomic-embed-text
    - Dimension: 768
    - Context: 8192 tokens
    - Designed for retrieval / RAG workloads
    - Strong MTEB benchmark scores for its size

nomic-embed-text must be pulled before first use:
    ollama pull nomic-embed-text

Batch embedding:
    Ollama processes one text at a time per API call.  embed_batch()
    runs requests sequentially here — this is intentional simplicity.
    For production scale, we would parallelize with asyncio.gather and
    a rate-limiting semaphore.  The sequential approach is fast enough
    for the document corpus sizes expected in this portfolio project.

Retry / error handling:
    httpx raises httpx.ConnectError / httpx.TimeoutException when Ollama is
    unreachable.  We catch these and raise EmbeddingUnavailableError so the
    caller sees a typed domain exception instead of a raw HTTP error.
"""
from __future__ import annotations

import logging

import httpx

from app.core.exceptions import EmbeddingUnavailableError, VectorDimensionMismatchError
from app.embeddings.base import EmbeddingProvider

logger = logging.getLogger("fintel.embeddings")

# Ollama embedding API path
_EMBED_PATH = "/api/embeddings"


class OllamaEmbeddingProvider(EmbeddingProvider):
    """EmbeddingProvider backed by a locally running Ollama instance.

    Args:
        base_url:        Base URL of the Ollama server (e.g. http://localhost:11434).
        model:           Name of the Ollama embedding model (e.g. nomic-embed-text).
        expected_dim:    Expected vector dimension. Validated on first call.
        timeout_seconds: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        expected_dim: int = 768,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._expected_dim = expected_dim
        self._timeout = timeout_seconds

    # ── EmbeddingProvider interface ────────────────────────────────────────────

    @property
    def dimension(self) -> int:
        return self._expected_dim

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string via Ollama.

        Args:
            text: Text to embed.  Should not exceed the model's context limit
                  (nomic-embed-text: 8192 tokens).

        Returns:
            List of floats of length self.dimension.

        Raises:
            EmbeddingUnavailableError: If Ollama is unreachable or returns an error.
            VectorDimensionMismatchError: If the returned vector length differs from
                                          self._expected_dim.
        """
        url = f"{self._base_url}{_EMBED_PATH}"
        payload = {"model": self._model, "prompt": text}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise EmbeddingUnavailableError(
                f"Cannot connect to Ollama at {self._base_url}. "
                "Ensure Ollama is running: ollama serve"
            ) from exc
        except httpx.TimeoutException as exc:
            raise EmbeddingUnavailableError(
                f"Ollama embedding request timed out after {self._timeout}s."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise EmbeddingUnavailableError(
                f"Ollama returned HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc

        data = response.json()
        vector: list[float] = data.get("embedding", [])

        if not vector:
            raise EmbeddingUnavailableError(
                f"Ollama returned an empty embedding for model {self._model!r}. "
                "Is the model pulled? Run: ollama pull nomic-embed-text"
            )

        if len(vector) != self._expected_dim:
            raise VectorDimensionMismatchError(
                f"Embedding dimension mismatch: expected {self._expected_dim}, "
                f"got {len(vector)}. Check EMBEDDING_MODEL and EMBEDDING_DIMENSION config."
            )

        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts sequentially.

        Ollama does not support native batching via /api/embeddings.
        Requests are sent one at a time.  This is acceptable for the
        document corpus sizes expected in this project.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors in the same order as input.
        """
        logger.info(
            "Embedding batch of %d texts with model=%s", len(texts), self._model
        )
        vectors: list[list[float]] = []
        for i, text in enumerate(texts):
            vector = await self.embed_text(text)
            vectors.append(vector)
            if (i + 1) % 10 == 0:
                logger.debug("Embedded %d / %d chunks", i + 1, len(texts))
        return vectors

    async def health_check(self) -> bool:
        """Return True if Ollama is reachable and the model responds."""
        try:
            await self.embed_text("health check")
            return True
        except EmbeddingUnavailableError:
            return False
        except VectorDimensionMismatchError:
            # Model reachable but config mismatch — still counts as reachable
            return True
