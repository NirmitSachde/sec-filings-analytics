"""Institutional holdings endpoints."""

from fastapi import APIRouter, Query

from sec_filings.api.models import HoldingChangeResponse, HoldingResponse
from sec_filings.db import get_session
from sec_filings.models import HoldingsPosition

router = APIRouter()


@router.get("/{manager_cik}", response_model=list[HoldingResponse])
def get_holdings(
    manager_cik: int,
    period: str | None = Query(None, description="Period in YYYY-Qn format"),
    limit: int = Query(50, le=500),
) -> list[HoldingResponse]:
    session = get_session()
    try:
        query = session.query(HoldingsPosition).filter(
            HoldingsPosition.filer_cik == manager_cik
        )

        if period:
            latest = (
                query.order_by(HoldingsPosition.period_of_report.desc())
                .first()
            )
            if latest:
                query = query.filter(
                    HoldingsPosition.period_of_report == latest.period_of_report
                )
        else:
            latest = (
                query.order_by(HoldingsPosition.period_of_report.desc())
                .first()
            )
            if latest:
                query = query.filter(
                    HoldingsPosition.period_of_report == latest.period_of_report
                )

        rows = query.order_by(HoldingsPosition.value.desc()).limit(limit).all()

        return [
            HoldingResponse(
                filer_name=r.filer_name,
                filer_cik=r.filer_cik,
                period_of_report=r.period_of_report,
                name_of_issuer=r.name_of_issuer,
                cusip=r.cusip,
                ticker=r.ticker,
                value=r.value,
                shares=r.shares,
                investment_discretion=r.investment_discretion,
            )
            for r in rows
        ]
    finally:
        session.close()


@router.get("/changes/{manager_cik}", response_model=list[HoldingChangeResponse])
def get_holdings_changes(
    manager_cik: int,
    limit: int = Query(50, le=500),
) -> list[HoldingChangeResponse]:
    """Quarter-over-quarter holding changes for a manager."""
    session = get_session()
    try:
        periods = (
            session.query(HoldingsPosition.period_of_report)
            .filter(HoldingsPosition.filer_cik == manager_cik)
            .distinct()
            .order_by(HoldingsPosition.period_of_report.desc())
            .limit(2)
            .all()
        )

        if len(periods) < 2:
            return []

        current_period = periods[0][0]
        prev_period = periods[1][0]

        current = {
            r.cusip: r
            for r in session.query(HoldingsPosition)
            .filter(
                HoldingsPosition.filer_cik == manager_cik,
                HoldingsPosition.period_of_report == current_period,
            )
            .all()
        }
        previous = {
            r.cusip: r
            for r in session.query(HoldingsPosition)
            .filter(
                HoldingsPosition.filer_cik == manager_cik,
                HoldingsPosition.period_of_report == prev_period,
            )
            .all()
        }

        results: list[HoldingChangeResponse] = []
        all_cusips = set(current.keys()) | set(previous.keys())

        for cusip in all_cusips:
            curr = current.get(cusip)
            prev = previous.get(cusip)

            if curr and not prev:
                change_type = "NEW_POSITION"
            elif not curr and prev:
                change_type = "EXITED"
            elif curr and prev:
                if curr.value > prev.value:
                    change_type = "INCREASED"
                elif curr.value < prev.value:
                    change_type = "REDUCED"
                else:
                    change_type = "UNCHANGED"
            else:
                continue

            ref = curr or prev
            assert ref is not None

            results.append(
                HoldingChangeResponse(
                    filer_name=ref.filer_name,
                    filer_cik=ref.filer_cik,
                    period_of_report=current_period,
                    name_of_issuer=ref.name_of_issuer,
                    cusip=cusip,
                    ticker=ref.ticker,
                    current_value=curr.value if curr else 0,
                    previous_value=prev.value if prev else None,
                    change_type=change_type,
                    value_delta=(curr.value if curr else 0) - (prev.value if prev else 0),
                )
            )

        results.sort(key=lambda x: abs(x.value_delta), reverse=True)
        return results[:limit]
    finally:
        session.close()
