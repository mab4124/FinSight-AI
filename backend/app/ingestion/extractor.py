"""
ingestion/extractor.py — PDF text extraction using PyMuPDF (fitz).

Phase 2: Page-by-page text extraction with metadata preservation.

Why PyMuPDF?
- Fast C-based rendering engine (MuPDF) orders of magnitude faster than Pure-Python PDF parsers.
- Preserves reading order and whitespace layout reliably.
- Provides page-level navigation essential for financial document citations.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from app.core.exceptions import DocumentProcessingError, InvalidPDFError

logger = logging.getLogger("fintel.ingestion")


@dataclass(frozen=True)
class ExtractedPage:
    """Structured representation of a single extracted PDF page."""
    page_number: int  # 1-indexed
    raw_text: str
    cleaned_text: str
    char_count: int
    is_empty: bool


class PDFExtractor:
    """Extracts text page-by-page from PDF files using PyMuPDF."""

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean extracted page text while preserving paragraph structure.

        - Replaces null bytes
        - Normalizes Windows / Mac line endings to Unix (\n)
        - Normalizes non-breaking spaces and excessive inline spaces
        - Collapses 3+ consecutive newlines to 2 newlines
        - Strips leading and trailing whitespace
        """
        if not text:
            return ""

        # Remove null characters
        cleaned = text.replace("\x00", "")

        # Normalize line breaks
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")

        # Replace non-breaking spaces with standard space
        cleaned = cleaned.replace("\xa0", " ")

        # Replace horizontal tabs with spaces
        cleaned = cleaned.replace("\t", " ")

        # Collapse multiple inline spaces (preserving single spaces and newlines)
        cleaned = re.sub(r"[^\S\n]+", " ", cleaned)

        # Remove spaces at end of lines
        cleaned = re.sub(r" +\n", "\n", cleaned)

        # Collapse 3+ newlines to double newline (paragraphs)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        return cleaned.strip()

    def extract_pages(self, file_path: Path | str) -> list[ExtractedPage]:
        """Extract text from all pages of a PDF document.

        Args:
            file_path: Path to the PDF file on disk.

        Returns:
            List of ExtractedPage objects (1-indexed page numbers).

        Raises:
            InvalidPDFError: If the file is encrypted or cannot be opened as a PDF.
            DocumentProcessingError: If reading pages fails unexpectedly.
        """
        path = Path(file_path)
        if not path.exists():
            raise InvalidPDFError(f"PDF file not found at path: {path}")

        try:
            doc = fitz.open(str(path))
        except Exception as exc:
            logger.error("Failed to open PDF at %s: %s", path, exc)
            raise InvalidPDFError(f"Cannot open PDF file: {exc}") from exc

        try:
            if doc.is_encrypted:
                logger.warning("Encrypted/password-protected PDF: %s", path)
                raise InvalidPDFError("Cannot process password-protected or encrypted PDF.")

            total_pages = len(doc)
            logger.info("Extracting %d pages from %s", total_pages, path.name)

            extracted: list[ExtractedPage] = []

            for page_index in range(total_pages):
                page_number = page_index + 1
                page = doc.load_page(page_index)
                raw_text = page.get_text("text") or ""
                cleaned_text = self.clean_text(raw_text)

                is_empty = len(cleaned_text.strip()) == 0
                char_count = len(cleaned_text)

                extracted.append(
                    ExtractedPage(
                        page_number=page_number,
                        raw_text=raw_text,
                        cleaned_text=cleaned_text,
                        char_count=char_count,
                        is_empty=is_empty,
                    )
                )

            logger.info(
                "Completed extraction for %s: %d total pages (%d non-empty)",
                path.name,
                total_pages,
                sum(1 for p in extracted if not p.is_empty),
            )
            return extracted

        except InvalidPDFError:
            raise
        except Exception as exc:
            logger.exception("Error during PDF page extraction for %s: %s", path, exc)
            raise DocumentProcessingError(f"PDF extraction failed: {exc}") from exc
        finally:
            doc.close()
