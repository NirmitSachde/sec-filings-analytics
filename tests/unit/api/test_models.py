"""Tests for the Pydantic API response models."""

import datetime

import pytest
from pydantic import ValidationError

from sec_filings.api.models import (
    ClusterBuyingSignal,
    ConcentrationResult,
    HoldingChangeResponse,
    HoldingResponse,
    InsiderTransactionResponse,
    RiskDiffResponse,
    RiskSimilarResult,
)


def _insider_payload(**overrides):
    payload = {
        "accession_number": "0000320193-24-000001",
        "filing_date": "2024-03-01",
        "owner_name": "Doe John",
        "owner_cik": 1234,
        "is_director": True,
        "is_officer": False,
        "officer_title": None,
        "issuer_name": "Apple Inc.",
        "issuer_ticker": "AAPL",
        "security_title": "Common Stock",
        "transaction_date": None,
        "transaction_code": "P",
        "shares": 100.0,
        "price_per_share": 180.5,
        "shares_after": 1100.0,
        "is_derivative": False,
        "is_10b5_1": True,
    }
    payload.update(overrides)
    return payload


def test_insider_transaction_coerces_dates_and_keeps_optionals():
    m = InsiderTransactionResponse(**_insider_payload())
    assert m.filing_date == datetime.date(2024, 3, 1)
    assert m.transaction_date is None
    assert m.officer_title is None
    assert m.is_10b5_1 is True
    dumped = m.model_dump()
    assert dumped["owner_cik"] == 1234
    assert set(dumped) == set(_insider_payload())


def test_insider_transaction_requires_fields():
    payload = _insider_payload()
    del payload["owner_name"]
    with pytest.raises(ValidationError) as exc:
        InsiderTransactionResponse(**payload)
    assert "owner_name" in str(exc.value)


def test_insider_transaction_rejects_bad_date():
    with pytest.raises(ValidationError):
        InsiderTransactionResponse(**_insider_payload(filing_date="not-a-date"))


def test_holding_response_round_trip():
    m = HoldingResponse(
        filer_name="Big Fund",
        filer_cik=1,
        period_of_report=datetime.date(2024, 3, 31),
        name_of_issuer="Apple Inc.",
        cusip="037833100",
        ticker=None,
        value=1000,
        shares=10,
        investment_discretion="SOLE",
    )
    assert HoldingResponse.model_validate_json(m.model_dump_json()) == m


def test_holding_response_rejects_non_integer_value():
    with pytest.raises(ValidationError):
        HoldingResponse(
            filer_name="Big Fund",
            filer_cik=1,
            period_of_report="2024-03-31",
            name_of_issuer="X",
            cusip="1",
            ticker=None,
            value="lots",
            shares=10,
            investment_discretion=None,
        )


def test_holding_change_response_allows_missing_previous_value():
    m = HoldingChangeResponse(
        filer_name="Big Fund",
        filer_cik=1,
        period_of_report="2024-06-30",
        name_of_issuer="X",
        cusip="1",
        ticker="X",
        current_value=50,
        previous_value=None,
        change_type="NEW_POSITION",
        value_delta=50,
    )
    assert m.previous_value is None
    assert m.period_of_report == datetime.date(2024, 6, 30)


def test_cluster_buying_signal():
    m = ClusterBuyingSignal(
        issuer_ticker=None,
        issuer_name="X",
        issuer_cik=9,
        distinct_insiders=3,
        total_buy_value=1.5e6,
        latest_filing_date="2024-01-02",
    )
    assert m.total_buy_value == 1_500_000.0
    assert m.latest_filing_date == datetime.date(2024, 1, 2)


def test_concentration_result():
    m = ConcentrationResult(issuer_name="X", ticker=None, cik=0, top10_holder_pct=99.5, hhi=5000)
    assert m.hhi == 5000.0
    with pytest.raises(ValidationError):
        ConcentrationResult(issuer_name="X", ticker=None, cik=0, top10_holder_pct="n/a", hhi=1)


def test_risk_similar_result():
    m = RiskSimilarResult(ticker="MSFT", issuer_cik=789019, similarity=0.9, chunk_preview="abc")
    assert m.model_dump() == {
        "ticker": "MSFT",
        "issuer_cik": 789019,
        "similarity": 0.9,
        "chunk_preview": "abc",
    }


def test_risk_diff_response_accepts_arbitrary_dicts():
    m = RiskDiffResponse(issuer_cik=1, year=2024, diffs=[{"type": "added", "n": 1}])
    assert m.diffs[0]["type"] == "added"
    with pytest.raises(ValidationError):
        RiskDiffResponse(issuer_cik=1, year=2024, diffs=["not a dict"])
