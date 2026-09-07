"""
ingestion/chunker.py — Page-aware text chunker for financial documents.

Phase 3: Splits cleaned page text into overlapping chunks for RAG retrieval.

Chunking strategy:
    - Split text into chunks of approximately RAG_CHUNK_SIZE words.
    - Apply RAG_CHUNK_OVERLAP words of overlap between consecutive chunks to
      prevent information loss at chunk boundaries.
    - Respect page boundaries: a chunk never spans two pages.
      This keeps citations clean — every chunk maps to exactly one page number.
    - Empty pages (is_empty=True) produce no chunks.

Why word-based splitting rather than character or token counting?
    Word count is the simplest approximation for length that works well with
    financial prose without requiring a tokenizer dependency.  A tokenizer
    would be more accurate but would add a heavyweight dependency (e.g.,
    tiktoken) just for chunking.  The RAG_CHUNK_SIZE value accounts for this
    approximation by targeting 600 words ≈ ~800 tokens for typical English
    financial text.

Overlap rationale:
    A sentence at a chunk boundary may be split across chunks.  Overlap
    ensures that the semantics of boundary content are present in both the
    preceding and following chunk.  Typical values: 10–20% of chunk size.

Tradeoffs (for interview / documentation):
    Small chunks (+) precise retrieval  (-) less surrounding context
    Large chunks (+) more semantic context (-) worse retrieval precision,
                                              more tokens consumed by LLM
    Overlap       (+) prevents boundary loss (-) storage + retrieval duplication

Configuration:
    RAG_CHUNK_SIZE: target words per chunk (default 600)
    RAG_CHUNK_OVERLAP: overlap words between chunks (default 80)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("fintel.ingestion")


@dataclass(frozen=True)
class TextChunk:
    """A single text chunk produced from a document page.

    Attributes:
        document_id:  UUID string of the source document.
        page_number:  1-indexed page this chunk came from.
        chunk_index:  0-based sequential index across the whole document.
        content:      The chunk text (used in retrieval prompts).
        token_count:  Approximate word count (not true BPE token count).
    """

    document_id: str
    page_number: int
    chunk_index: int
    content: str
    token_count: int


class TextChunker:
    """Splits page text into overlapping word-window chunks.

    Args:
        chunk_size:    Target number of words per chunk.
        chunk_overlap: Number of words to repeat at the start of the next chunk.
    """

    def __init__(self, chunk_size: int = 600, chunk_overlap: int = 80) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be less than "
                f"chunk_size ({chunk_size})."
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ── Public API ─────────────────────────────────────────────────────────────

    def chunk_pages(
        self,
        document_id: str,
        pages: list[tuple[int, str]],
    ) -> list[TextChunk]:
        """Chunk a list of (page_number, cleaned_text) pairs.

        Pages are chunked independently so citations stay page-accurate.
        chunk_index is global across the document (monotonically increasing).

        Args:
            document_id: UUID string of the source document.
            pages:       List of (page_number, cleaned_text) tuples.
                         Pages with empty text are silently skipped.

        Returns:
            List of TextChunk objects in page order.
        """
        all_chunks: list[TextChunk] = []
        global_index = 0

        for page_number, text in pages:
            if not text or not text.strip():
                continue  # skip empty / image-only pages

            page_chunks = self._chunk_text(text)

            for content in page_chunks:
                all_chunks.append(
                    TextChunk(
                        document_id=document_id,
                        page_number=page_number,
                        chunk_index=global_index,
                        content=content,
                        token_count=len(content.split()),
                    )
                )
                global_index += 1

        logger.debug(
            "Chunked document %s: %d pages → %d chunks",
            document_id,
            len(pages),
            len(all_chunks),
        )
        return all_chunks

    # ── Internal ───────────────────────────────────────────────────────────────

    def _chunk_text(self, text: str) -> list[str]:
        """Split a single block of text into overlapping word-window chunks.

        Algorithm:
            1. Tokenize into words by whitespace.
            2. Slide a window of `chunk_size` words across the word list.
            3. Advance the window by `chunk_size - chunk_overlap` words each step.
            4. Reconstruct each window back into a string.

        Args:
            text: Cleaned page text.

        Returns:
            List of text strings.  Each string represents one chunk.
        """
        words = text.split()
        if not words:
            return []

        step = self.chunk_size - self.chunk_overlap
        chunks: list[str] = []

        start = 0
        while start < len(words):
            end = min(start + self.chunk_size, len(words))
            chunk_text = " ".join(words[start:end])
            chunks.append(chunk_text)
            if end == len(words):
                break
            start += step

        return chunks
