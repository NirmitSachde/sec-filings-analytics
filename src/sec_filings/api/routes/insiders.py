"""Insider transaction endpoints."""

import datetime

from fastapi import APIRouter, Query

from sec_filings.api.models import InsiderTransactionResponse
from sec_filings.db import get_session
from sec_filings.models import InsiderTransaction

router = APIRouter()


@router.get("/{ticker}", response_model=list[InsiderTransactionResponse])
def get_insider_transactions(
    ticker: str,
    since: datetime.date | None = Query(None, description="Filter transactions since this date"),
    limit: int = Query(100, le=1000),
) -> list[InsiderTransactionResponse]:
    session = get_session()
    try:
        query = session.query(InsiderTransaction).filter(
            InsiderTransaction.issuer_ticker == ticker.upper()
        )
        if since:
            query = query.filter(InsiderTransaction.filing_date >= since)

        rows = query.order_by(InsiderTransaction.filing_date.desc()).limit(limit).all()

        return [
            InsiderTransactionResponse(
                accession_number=r.accession_number,
                filing_date=r.filing_date,
                owner_name=r.owner_name,
                owner_cik=r.owner_cik,
                is_director=r.is_director,
                is_officer=r.is_officer,
                officer_title=r.officer_title,
                issuer_name=r.issuer_name,
                issuer_ticker=r.issuer_ticker,
                security_title=r.security_title,
                transaction_date=r.transaction_date,
                transaction_code=r.transaction_code,
                shares=r.shares,
                price_per_share=r.price_per_share,
                shares_after=r.shares_after,
                is_derivative=r.is_derivative,
                is_10b5_1=r.is_10b5_1,
            )
            for r in rows
        ]
    finally:
        session.close()
