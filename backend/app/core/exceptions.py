"""
core/exceptions.py — Custom exception hierarchy and FastAPI exception handlers.

Design principle: routes raise domain exceptions; handlers convert them to
consistent JSON error responses.  Stack traces are never leaked to the client.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger("fintel")


# ── Domain Exception Base ─────────────────────────────────────────────────────

class FintelError(Exception):
    """Base class for all application exceptions."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


# ── Document Errors ───────────────────────────────────────────────────────────

class DocumentNotFoundError(FintelError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "DOCUMENT_NOT_FOUND"


class DuplicateDocumentError(FintelError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "DUPLICATE_DOCUMENT"


class InvalidPDFError(FintelError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "INVALID_PDF"


class FileTooLargeError(FintelError):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    error_code = "FILE_TOO_LARGE"


class DocumentProcessingError(FintelError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "PROCESSING_ERROR"


class DocumentStillProcessingError(FintelError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "DOCUMENT_STILL_PROCESSING"


# ── Company Errors ────────────────────────────────────────────────────────────

class CompanyNotFoundError(FintelError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "COMPANY_NOT_FOUND"


# ── RAG / Retrieval Errors ────────────────────────────────────────────────────

class NoRetrievalResultsError(FintelError):
    status_code = status.HTTP_200_OK   # Not a failure — returns a "no evidence" answer
    error_code = "NO_RETRIEVAL_RESULTS"


class LLMUnavailableError(FintelError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "LLM_UNAVAILABLE"


class EmbeddingUnavailableError(FintelError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "EMBEDDING_UNAVAILABLE"


class VectorDimensionMismatchError(FintelError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "VECTOR_DIMENSION_MISMATCH"


class MalformedLLMResponseError(FintelError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "MALFORMED_LLM_RESPONSE"


# ── FastAPI Exception Handlers ────────────────────────────────────────────────

def _error_body(error_code: str, message: str, detail: str | None = None) -> dict:
    body: dict = {"error": error_code, "message": message}
    if detail:
        body["detail"] = detail
    return body


async def fintel_exception_handler(request: Request, exc: FintelError) -> JSONResponse:
    """Convert domain exceptions to structured JSON responses."""
    logger.warning(
        "Domain error | path=%s | code=%s | message=%s",
        request.url.path,
        exc.error_code,
        exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.error_code, exc.message, exc.detail),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler — never leak stack traces to the client."""
    logger.exception("Unhandled exception | path=%s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_body("INTERNAL_ERROR", "An unexpected error occurred."),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI application."""
    app.add_exception_handler(FintelError, fintel_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
