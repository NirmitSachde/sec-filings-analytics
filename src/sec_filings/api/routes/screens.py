"""Screening endpoints — cluster buying, ownership concentration."""

import datetime

from fastapi import APIRouter, Query
from sqlalchemy import func

from sec_filings.api.models import ClusterBuyingSignal, ConcentrationResult
from sec_filings.db import get_session
from sec_filings.models import HoldingsPosition, InsiderTransaction

router = APIRouter()


@router.get("/cluster-buying", response_model=list[ClusterBuyingSignal])
def screen_cluster_buying(
    min_insiders: int = Query(3, ge=2),
    min_value: float = Query(250_000, ge=0),
    since: datetime.date | None = None,
    limit: int = Query(50, le=500),
) -> list[ClusterBuyingSignal]:
    """Find issuers with cluster insider buying activity."""
    if since is None:
        since = datetime.date.today() - datetime.timedelta(days=90)

    session = get_session()
    try:
        # Buy transactions: codes P (open-market purchase), A (grant/award)
        results = (
            session.query(
                InsiderTransaction.issuer_cik,
                InsiderTransaction.issuer_name,
                InsiderTransaction.issuer_ticker,
                func.count(func.distinct(InsiderTransaction.owner_cik)).label("distinct_insiders"),
                func.sum(
                    InsiderTransaction.shares * InsiderTransaction.price_per_share
                ).label("total_buy_value"),
                func.max(InsiderTransaction.filing_date).label("latest_filing_date"),
            )
            .filter(
                InsiderTransaction.transaction_code == "P",
                InsiderTransaction.filing_date >= since,
                InsiderTransaction.shares.isnot(None),
                InsiderTransaction.price_per_share.isnot(None),
            )
            .group_by(
                InsiderTransaction.issuer_cik,
                InsiderTransaction.issuer_name,
                InsiderTransaction.issuer_ticker,
            )
            .having(
                func.count(func.distinct(InsiderTransaction.owner_cik)) >= min_insiders,
                func.sum(
                    InsiderTransaction.shares * InsiderTransaction.price_per_share
                )
                >= min_value,
            )
            .order_by(func.count(func.distinct(InsiderTransaction.owner_cik)).desc())
            .limit(limit)
            .all()
        )

        return [
            ClusterBuyingSignal(
                issuer_cik=r.issuer_cik,
                issuer_name=r.issuer_name,
                issuer_ticker=r.issuer_ticker,
                distinct_insiders=r.distinct_insiders,
                total_buy_value=float(r.total_buy_value or 0),
                latest_filing_date=r.latest_filing_date,
            )
            for r in results
        ]
    finally:
        session.close()


@router.get("/concentration", response_model=list[ConcentrationResult])
def screen_concentration(
    top_n: int = Query(20, le=100),
) -> list[ConcentrationResult]:
    """Find issuers with highest institutional ownership concentration (HHI)."""
    session = get_session()
    try:
        # Get latest period
        latest_period = (
            session.query(func.max(HoldingsPosition.period_of_report)).scalar()
        )
        if not latest_period:
            return []

        # Get total value per issuer, then compute HHI
        issuer_totals = (
            session.query(
                HoldingsPosition.name_of_issuer,
                HoldingsPosition.cusip,
                HoldingsPosition.ticker,
                func.sum(HoldingsPosition.value).label("total_value"),
            )
            .filter(HoldingsPosition.period_of_report == latest_period)
            .group_by(
                HoldingsPosition.name_of_issuer,
                HoldingsPosition.cusip,
                HoldingsPosition.ticker,
            )
            .having(func.sum(HoldingsPosition.value) > 0)
            .all()
        )

        results: list[ConcentrationResult] = []
        for issuer in issuer_totals:
            # Get individual holder values
            holders = (
                session.query(
                    HoldingsPosition.filer_cik,
                    HoldingsPosition.value,
                )
                .filter(
                    HoldingsPosition.cusip == issuer.cusip,
                    HoldingsPosition.period_of_report == latest_period,
                )
                .order_by(HoldingsPosition.value.desc())
                .all()
            )

            if not holders or issuer.total_value == 0:
                continue

            shares = [h.value / issuer.total_value for h in holders]
            hhi = sum(s * s for s in shares) * 10000
            top10_pct = sum(shares[:10]) * 100

            results.append(
                ConcentrationResult(
                    issuer_name=issuer.name_of_issuer,
                    ticker=issuer.ticker,
                    cik=0,
                    top10_holder_pct=round(top10_pct, 2),
                    hhi=round(hhi, 2),
                )
            )

        results.sort(key=lambda x: x.hhi, reverse=True)
        return results[:top_n]
    finally:
        session.close()
