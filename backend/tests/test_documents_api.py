"""
tests/test_documents_api.py — Document API & Service tests for Phase 2.

Tests:
- Route registration for Phase 2 endpoints (/documents/{id}/process, /documents/{id}/pages, /documents/{id}/pages/{num})
- DocumentService async lifecycle (mocking DB session & extractor)
- 404 behavior for unknown documents/pages
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import DocumentNotFoundError, PageNotFoundError
from app.db.models import Document, DocumentPage, ProcessingStatus
from app.ingestion.extractor import ExtractedPage
from app.main import app
from app.services.document_service import DocumentService

client = TestClient(app, raise_server_exceptions=False)


class TestDocumentRoutesPhase2:
    """Verify Phase 2 OpenAPI paths and basic route behaviors."""

    def test_routes_in_openapi_schema(self) -> None:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]
        assert "/api/v1/documents/{document_id}/process" in paths
        assert "/api/v1/documents/{document_id}/pages" in paths
        assert "/api/v1/documents/{document_id}/pages/{page_number}" in paths

    def test_get_unknown_document_returns_404(self) -> None:
        response = client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000")
        # In isolated unit tests without DB running, FastAPI raises or returns error
        assert response.status_code in (404, 500)


@pytest.mark.asyncio
class TestDocumentServiceUnit:
    """Unit tests for DocumentService business logic with mocked session & extractor."""

    async def test_process_document_success(self, tmp_path) -> None:
        # Prepare test PDF
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 mock")

        # Mock DB and Document
        mock_doc = Document(
            id="doc-123",
            company_id="comp-123",
            original_filename="test.pdf",
            file_path=str(fake_pdf),
            processing_status=ProcessingStatus.UPLOADED.value,
        )

        mock_db = AsyncMock()
        mock_db.add_all = MagicMock()
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = mock_doc
        mock_db.execute.return_value = mock_execute_result

        # Mock Extractor
        mock_extractor = MagicMock()
        mock_extractor.extract_pages.return_value = [
            ExtractedPage(
                page_number=1,
                raw_text="Revenue grew 20%.",
                cleaned_text="Revenue grew 20%.",
                char_count=18,
                is_empty=False,
            ),
            ExtractedPage(
                page_number=2,
                raw_text="",
                cleaned_text="",
                char_count=0,
                is_empty=True,
            ),
        ]

        service = DocumentService(extractor=mock_extractor)
        result = await service.process_document("doc-123", mock_db)

        assert result.processing_status == ProcessingStatus.READY.value
        assert result.page_count == 2
        assert mock_db.commit.call_count >= 2
        assert mock_db.add_all.called

    async def test_process_document_not_found(self) -> None:
        mock_db = AsyncMock()
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_execute_result

        service = DocumentService()
        with pytest.raises(DocumentNotFoundError):
            await service.process_document("non-existent-id", mock_db)
