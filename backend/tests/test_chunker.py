"""
tests/test_chunker.py — Unit tests for the TextChunker.

These tests run entirely in-process with no database or network I/O.
They verify the core splitting logic, overlap behavior, edge cases, and the
chunk_pages() convenience method.
"""
from __future__ import annotations

import pytest

from app.ingestion.chunker import TextChunk, TextChunker


# ── Helpers ───────────────────────────────────────────────────────────────────

def _words(n: int) -> str:
    """Return a string of n distinct words."""
    return " ".join(f"word{i}" for i in range(n))


# ── Constructor validation ────────────────────────────────────────────────────

def test_constructor_rejects_overlap_gte_chunk_size() -> None:
    with pytest.raises(ValueError, match="chunk_overlap"):
        TextChunker(chunk_size=100, chunk_overlap=100)

    with pytest.raises(ValueError, match="chunk_overlap"):
        TextChunker(chunk_size=100, chunk_overlap=150)


def test_constructor_accepts_valid_params() -> None:
    chunker = TextChunker(chunk_size=600, chunk_overlap=80)
    assert chunker.chunk_size == 600
    assert chunker.chunk_overlap == 80


# ── _chunk_text edge cases ────────────────────────────────────────────────────

def test_chunk_text_empty_returns_empty() -> None:
    chunker = TextChunker(chunk_size=10, chunk_overlap=2)
    assert chunker._chunk_text("") == []
    assert chunker._chunk_text("   ") == []


def test_chunk_text_short_text_single_chunk() -> None:
    """Text shorter than chunk_size → exactly one chunk."""
    chunker = TextChunker(chunk_size=100, chunk_overlap=10)
    text = _words(50)
    result = chunker._chunk_text(text)
    assert len(result) == 1
    assert result[0] == text


def test_chunk_text_exact_chunk_size_single_chunk() -> None:
    chunker = TextChunker(chunk_size=10, chunk_overlap=2)
    text = _words(10)
    result = chunker._chunk_text(text)
    assert len(result) == 1


def test_chunk_text_produces_multiple_chunks() -> None:
    """100 words with chunk_size=40, overlap=10 → step=30
    chunks start at: 0, 30, 60
    - chunk[0] covers words[0:40]
    - chunk[1] covers words[30:70]
    - chunk[2] covers words[60:100]  ← reaches end, loop exits → 3 chunks total
    """
    chunker = TextChunker(chunk_size=40, chunk_overlap=10)
    text = _words(100)
    result = chunker._chunk_text(text)
    assert len(result) == 3


def test_chunk_text_overlap_content() -> None:
    """The last `chunk_overlap` words of chunk N must be the first words of chunk N+1."""
    chunk_size = 10
    overlap = 3
    chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=overlap)
    text = _words(25)
    result = chunker._chunk_text(text)
    assert len(result) >= 2

    for i in range(len(result) - 1):
        tail_words = result[i].split()[-overlap:]
        head_words = result[i + 1].split()[:overlap]
        assert tail_words == head_words, (
            f"Overlap mismatch between chunk {i} and {i + 1}: "
            f"tail={tail_words!r}, head={head_words!r}"
        )


def test_chunk_text_last_chunk_ends_at_text_end() -> None:
    """The final chunk must include the last word of the text."""
    chunker = TextChunker(chunk_size=10, chunk_overlap=2)
    words_list = [f"word{i}" for i in range(23)]
    text = " ".join(words_list)
    result = chunker._chunk_text(text)
    assert result[-1].split()[-1] == words_list[-1]


def test_chunk_text_no_duplicate_last_chunk() -> None:
    """Text that divides exactly should not produce a trailing duplicate chunk."""
    # chunk_size=10, overlap=2 → step=8
    # 26 words: starts at 0, 8, 16, 24 → chunk at 24 covers words[24:34] = words[24:26]
    chunker = TextChunker(chunk_size=10, chunk_overlap=2)
    text = _words(26)
    result = chunker._chunk_text(text)
    # There must be no two identical consecutive chunks
    for i in range(len(result) - 1):
        assert result[i] != result[i + 1], "Duplicate consecutive chunks detected"


# ── chunk_pages ────────────────────────────────────────────────────────────────

def test_chunk_pages_returns_text_chunks() -> None:
    chunker = TextChunker(chunk_size=50, chunk_overlap=5)
    pages = [
        (1, _words(60)),
        (2, _words(60)),
    ]
    result = chunker.chunk_pages("doc-id-123", pages)
    assert all(isinstance(c, TextChunk) for c in result)


def test_chunk_pages_global_chunk_index_is_monotonic() -> None:
    chunker = TextChunker(chunk_size=50, chunk_overlap=5)
    pages = [(1, _words(60)), (2, _words(60)), (3, _words(60))]
    result = chunker.chunk_pages("doc-id", pages)
    indices = [c.chunk_index for c in result]
    assert indices == list(range(len(result)))


def test_chunk_pages_page_number_preserved() -> None:
    chunker = TextChunker(chunk_size=50, chunk_overlap=5)
    pages = [(3, _words(60)), (7, _words(60))]
    result = chunker.chunk_pages("doc-id", pages)
    page_numbers = {c.page_number for c in result}
    assert page_numbers == {3, 7}


def test_chunk_pages_skips_empty_pages() -> None:
    chunker = TextChunker(chunk_size=50, chunk_overlap=5)
    pages = [
        (1, _words(60)),
        (2, ""),             # empty
        (3, "   "),          # whitespace-only
        (4, _words(60)),
    ]
    result = chunker.chunk_pages("doc-id", pages)
    page_numbers = {c.chunk_index: c.page_number for c in result}
    # No chunks should have page_number 2 or 3
    for chunk in result:
        assert chunk.page_number in {1, 4}


def test_chunk_pages_document_id_propagated() -> None:
    doc_id = "abc-123"
    chunker = TextChunker(chunk_size=50, chunk_overlap=5)
    result = chunker.chunk_pages(doc_id, [(1, _words(60))])
    assert all(c.document_id == doc_id for c in result)


def test_chunk_pages_token_count_is_word_count() -> None:
    chunker = TextChunker(chunk_size=50, chunk_overlap=5)
    result = chunker.chunk_pages("doc", [(1, _words(60))])
    for chunk in result:
        assert chunk.token_count == len(chunk.content.split())


def test_chunk_pages_no_pages_returns_empty() -> None:
    chunker = TextChunker(chunk_size=50, chunk_overlap=5)
    assert chunker.chunk_pages("doc", []) == []


def test_chunk_pages_single_word_page() -> None:
    """A page with a single word should produce exactly one chunk."""
    chunker = TextChunker(chunk_size=50, chunk_overlap=5)
    result = chunker.chunk_pages("doc", [(1, "hello")])
    assert len(result) == 1
    assert result[0].content == "hello"
