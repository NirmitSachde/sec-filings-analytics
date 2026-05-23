"""Semantic search and risk-factor diff endpoints."""

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query
from sqlalchemy import text

from sec_filings.api.models import RiskDiffResponse, RiskSimilarResult
from sec_filings.db import get_session
from sec_filings.models import RiskFactorChunk, RiskFactorDiff, TickerCik

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

router = APIRouter()

_model: "SentenceTransformer | None" = None


def _get_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return _model


@router.get("/risk-similar/{ticker}", response_model=list[RiskSimilarResult])
def search_risk_similar(
    ticker: str,
    top_k: int = Query(10, le=50),
) -> list[RiskSimilarResult]:
    """Find companies with risk profiles similar to the given ticker."""
    session = get_session()
    try:
        # Resolve ticker to CIK
        mapping = (
            session.query(TickerCik)
            .filter(TickerCik.ticker == ticker.upper())
            .first()
        )
        if not mapping:
            return []

        # Get the most recent risk factor chunk for this company
        ref_chunk = (
            session.query(RiskFactorChunk)
            .filter(RiskFactorChunk.issuer_cik == mapping.cik)
            .order_by(RiskFactorChunk.year.desc(), RiskFactorChunk.chunk_index)
            .first()
        )
        if not ref_chunk or ref_chunk.embedding is None:
            return []

        embedding_str = "[" + ",".join(str(x) for x in ref_chunk.embedding) + "]"

        results = session.execute(
            text("""
                SELECT issuer_cik, chunk_text,
                       1 - (embedding <=> :embedding::vector) as similarity
                FROM vec.risk_factor_chunks
                WHERE issuer_cik != :exclude_cik
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top_k
            """),
            {
                "embedding": embedding_str,
                "exclude_cik": mapping.cik,
                "top_k": top_k,
            },
        ).fetchall()

        response: list[RiskSimilarResult] = []
        seen_ciks: set[int] = set()
        for row in results:
            if row.issuer_cik in seen_ciks:
                continue
            seen_ciks.add(row.issuer_cik)

            # Resolve CIK back to ticker
            t = (
                session.query(TickerCik.ticker)
                .filter(TickerCik.cik == row.issuer_cik)
                .first()
            )

            response.append(
                RiskSimilarResult(
                    ticker=t.ticker if t else None,
                    issuer_cik=row.issuer_cik,
                    similarity=round(float(row.similarity), 4),
                    chunk_preview=row.chunk_text[:200],
                )
            )

        return response
    finally:
        session.close()


@router.get("/diffs/{ticker}/{year}", response_model=RiskDiffResponse)
def get_risk_diffs(
    ticker: str,
    year: int,
) -> RiskDiffResponse:
    """Get the LLM-generated risk-factor diff summary for a company and year."""
    session = get_session()
    try:
        mapping = (
            session.query(TickerCik)
            .filter(TickerCik.ticker == ticker.upper())
            .first()
        )
        if not mapping:
            return RiskDiffResponse(issuer_cik=0, year=year, diffs=[])

        diff = (
            session.query(RiskFactorDiff)
            .filter(
                RiskFactorDiff.issuer_cik == mapping.cik,
                RiskFactorDiff.year == year,
            )
            .first()
        )
        if not diff:
            return RiskDiffResponse(issuer_cik=mapping.cik, year=year, diffs=[])

        return RiskDiffResponse(
            issuer_cik=mapping.cik,
            year=year,
            diffs=json.loads(diff.diff_json),
        )
    finally:
        session.close()
