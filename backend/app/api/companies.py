"""
api/companies.py — Company management endpoints.

Phase 1: Basic CRUD for companies.
Phase 2+: Companies gain documents, metrics, and comparison views.

A company is the top-level organizational unit.  Every uploaded document
belongs to exactly one company.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CompanyNotFoundError
from app.db.models import Company
from app.db.session import get_db

logger = logging.getLogger("fintel")
router = APIRouter(prefix="/companies", tags=["Companies"])


# ── Request / Response Schemas ────────────────────────────────────────────────

class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Full company name")
    ticker: str | None = Field(None, max_length=20, description="Stock ticker symbol")
    sector: str | None = Field(None, max_length=100, description="Industry sector")


class CompanyResponse(BaseModel):
    id: str
    name: str
    ticker: str | None
    sector: str | None
    created_at: datetime
    document_count: int = 0

    model_config = {"from_attributes": True}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a company",
)
async def create_company(
    payload: CompanyCreate,
    db: AsyncSession = Depends(get_db),
) -> CompanyResponse:
    company = Company(
        name=payload.name,
        ticker=payload.ticker.upper() if payload.ticker else None,
        sector=payload.sector,
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    logger.info("Company created | id=%s name=%s", company.id, company.name)
    return CompanyResponse(
        id=company.id,
        name=company.name,
        ticker=company.ticker,
        sector=company.sector,
        created_at=company.created_at,
    )


@router.get(
    "",
    response_model=list[CompanyResponse],
    summary="List all companies",
)
async def list_companies(db: AsyncSession = Depends(get_db)) -> list[CompanyResponse]:
    result = await db.execute(select(Company).order_by(Company.created_at.desc()))
    companies = result.scalars().all()
    return [
        CompanyResponse(
            id=c.id,
            name=c.name,
            ticker=c.ticker,
            sector=c.sector,
            created_at=c.created_at,
        )
        for c in companies
    ]


@router.get(
    "/{company_id}",
    response_model=CompanyResponse,
    summary="Get a company by ID",
)
async def get_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
) -> CompanyResponse:
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if company is None:
        raise CompanyNotFoundError(f"Company {company_id!r} not found.")
    return CompanyResponse(
        id=company.id,
        name=company.name,
        ticker=company.ticker,
        sector=company.sector,
        created_at=company.created_at,
    )
