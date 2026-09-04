"""
api/query.py — RAG query endpoint stub.

Phase 1: Returns a 501 Not Implemented response to confirm the route is
          registered and the request schema is correct.
Phase 7: Full RAG implementation (retrieval → Gemma → citations).
"""
from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/query", tags=["Research / RAG"])


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=5, description="Natural language question")
    document_ids: list[str] = Field(default_factory=list, description="Filter to specific documents")
    company_ids: list[str] = Field(default_factory=list, description="Filter to specific companies")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of evidence chunks to retrieve")


@router.post(
    "",
    summary="Ask a question about uploaded documents (RAG)",
    description="Phase 7 will implement the full retrieval-augmented generation pipeline.",
)
async def query_documents(payload: QueryRequest) -> JSONResponse:
    # Placeholder — full implementation in Phase 7
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "message": "RAG pipeline not yet implemented. Coming in Phase 7.",
            "received_question": payload.question,
        },
    )
