"""
tests/test_extraction.py — Phase 2 PDF extraction unit tests.

Tests:
- PDFExtractor text cleaning logic
- Page-by-page extraction with accurate page counts
- Empty/blank page detection
- Character counts and whitespace normalization
- Non-existent and invalid file handling
"""
from __future__ import annotations

import fitz
import pytest

from app.core.exceptions import InvalidPDFError
from app.ingestion.extractor import PDFExtractor


@pytest.fixture
def sample_pdf_path(tmp_path):
    """Create a temporary multi-page PDF with text and a blank page."""
    pdf_path = tmp_path / "sample_report.pdf"
    doc = fitz.open()

    # Page 1: Standard financial text
    p1 = doc.new_page()
    p1.insert_text(
        (50, 72),
        "FinSight AI Annual Report 2024\n\nTotal revenue increased 15% to $120 million.\nOperating margin improved to 28%.",
    )

    # Page 2: Blank / empty page
    doc.new_page()

    # Page 3: Additional commentary
    p3 = doc.new_page()
    p3.insert_text(
        (50, 72),
        "Risk Factors\n\nGlobal macroeconomic volatility may impact future performance.",
    )

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestPDFExtractor:
    """Unit tests for the PDFExtractor class."""

    def test_text_cleaning(self) -> None:
        extractor = PDFExtractor()
        raw = "  Hello   world! \t\r\n\r\n\r\n\r\nThis  is a   test.\x00  "
        cleaned = extractor.clean_text(raw)
        assert cleaned == "Hello world!\n\nThis is a test."

    def test_extract_pages_success(self, sample_pdf_path) -> None:
        extractor = PDFExtractor()
        pages = extractor.extract_pages(sample_pdf_path)

        assert len(pages) == 3

        # Page 1
        assert pages[0].page_number == 1
        assert "Total revenue increased" in pages[0].cleaned_text
        assert not pages[0].is_empty
        assert pages[0].char_count > 0

        # Page 2 (Empty)
        assert pages[1].page_number == 2
        assert pages[1].is_empty
        assert pages[1].char_count == 0

        # Page 3
        assert pages[2].page_number == 3
        assert "Risk Factors" in pages[2].cleaned_text
        assert not pages[2].is_empty
        assert pages[2].char_count > 0

    def test_extract_nonexistent_file_raises_error(self, tmp_path) -> None:
        extractor = PDFExtractor()
        missing_path = tmp_path / "does_not_exist.pdf"
        with pytest.raises(InvalidPDFError, match="not found"):
            extractor.extract_pages(missing_path)

    def test_extract_corrupt_file_raises_error(self, tmp_path) -> None:
        extractor = PDFExtractor()
        corrupt_path = tmp_path / "corrupt.pdf"
        corrupt_path.write_bytes(b"%PDF-1.4 corrupt content that cannot parse")
        with pytest.raises(InvalidPDFError):
            extractor.extract_pages(corrupt_path)
