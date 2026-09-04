"""
tests/test_health.py — Phase 1 health endpoint tests.

These tests verify the /health endpoint returns 200 with the correct shape.
The /health/db test is skipped when no database is available (CI-safe).

We use FastAPI's TestClient which runs the app synchronously — no real
server is needed.  The database dependency is mocked to avoid requiring
a live PostgreSQL instance for the liveness check test.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint:
    """Tests for GET /api/v1/health (liveness check)."""

    def test_health_returns_200(self) -> None:
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self) -> None:
        response = client.get("/api/v1/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_health_returns_app_name(self) -> None:
        response = client.get("/api/v1/health")
        data = response.json()
        assert "app" in data
        assert len(data["app"]) > 0

    def test_health_returns_version(self) -> None:
        response = client.get("/api/v1/health")
        data = response.json()
        assert "version" in data


class TestAPIStructure:
    """Verify the router structure is assembled correctly."""

    def test_docs_available(self) -> None:
        """OpenAPI docs should be accessible."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_openapi_schema(self) -> None:
        """OpenAPI schema should include our routes."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        paths = schema["paths"]
        assert "/api/v1/health" in paths
        assert "/api/v1/companies" in paths
        assert "/api/v1/documents/upload" in paths
        assert "/api/v1/query" in paths

    def test_query_stub_returns_501(self) -> None:
        """Query endpoint should return 501 until Phase 7."""
        response = client.post(
            "/api/v1/query",
            json={"question": "What was the revenue last year?"},
        )
        assert response.status_code == 501

    def test_unknown_route_returns_404(self) -> None:
        response = client.get("/api/v1/nonexistent")
        assert response.status_code == 404
