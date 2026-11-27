"""Tests for the insider transaction endpoint."""

import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sec_filings.api.main import app
from sec_filings.api.routes import insiders
from tests.unit.api.fakes import FakeQuery, FakeSession

client = TestClient(app)


def _tx(**overrides):
    row = {
        "accession_number": "0000320193-24-000001",
        "filing_date": datetime.date(2024, 3, 1),
        "owner_name": "Doe John",
        "owner_cik": 1234,
        "is_director": True,
        "is_officer": True,
        "officer_title": "CEO",
        "issuer_name": "Apple Inc.",
        "issuer_ticker": "AAPL",
        "security_title": "Common Stock",
        "transaction_date": datetime.date(2024, 2, 28),
        "transaction_code": "P",
        "shares": 100.0,
        "price_per_share": 180.5,
        "shares_after": 1100.0,
        "is_derivative": False,
        "is_10b5_1": False,
    }
    row.update(overrides)
    return SimpleNamespace(**row)


@pytest.fixture
def install(monkeypatch):
    def _install(session):
        monkeypatch.setattr(insiders, "get_session", lambda: session)
        return session

    return _install


def test_returns_mapped_transactions(install):
    rows = [
        _tx(),
        _tx(
            accession_number="0000320193-24-000002",
            officer_title=None,
            transaction_date=None,
            transaction_code=None,
            shares=None,
            price_per_share=None,
            shares_after=None,
            is_derivative=True,
            is_10b5_1=True,
        ),
    ]
    session = install(FakeSession([FakeQuery(rows)]))

    resp = client.get("/insiders/AAPL")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0] == {
        "accession_number": "0000320193-24-000001",
        "filing_date": "2024-03-01",
        "owner_name": "Doe John",
        "owner_cik": 1234,
        "is_director": True,
        "is_officer": True,
        "officer_title": "CEO",
        "issuer_name": "Apple Inc.",
        "issuer_ticker": "AAPL",
        "security_title": "Common Stock",
        "transaction_date": "2024-02-28",
        "transaction_code": "P",
        "shares": 100.0,
        "price_per_share": 180.5,
        "shares_after": 1100.0,
        "is_derivative": False,
        "is_10b5_1": False,
    }
    assert body[1]["transaction_date"] is None
    assert body[1]["shares"] is None
    assert body[1]["is_10b5_1"] is True
    assert session.closed


def test_ticker_is_uppercased_and_defaults_applied(install):
    session = install(FakeSession([FakeQuery([])]))

    resp = client.get("/insiders/aapl")

    assert resp.status_code == 200
    assert resp.json() == []
    q = session.queries[0]
    assert q.rendered_filters() == ["raw.insider_transactions.issuer_ticker = 'AAPL'"]
    assert q.rendered_order_bys() == ["raw.insider_transactions.filing_date DESC"]
    assert q.limit_value == 100


def test_since_and_limit_filters(install):
    session = install(FakeSession([FakeQuery([])]))

    resp = client.get("/insiders/msft", params={"since": "2024-01-15", "limit": 5})

    assert resp.status_code == 200
    q = session.queries[0]
    filters = q.rendered_filters()
    assert filters[0] == "raw.insider_transactions.issuer_ticker = 'MSFT'"
    assert filters[1] == "raw.insider_transactions.filing_date >= '2024-01-15'"
    assert q.limit_value == 5


@pytest.mark.parametrize(
    "params",
    [{"limit": 1001}, {"since": "yesterday"}, {"limit": "ten"}],
)
def test_invalid_query_params_rejected(install, params):
    session = install(FakeSession([FakeQuery([])]))

    resp = client.get("/insiders/AAPL", params=params)

    assert resp.status_code == 422
    assert session.queries == []


def test_session_closed_on_error(install):
    class Boom(FakeSession):
        def query(self, *entities):
            raise RuntimeError("db down")

    session = install(Boom())
    with pytest.raises(RuntimeError, match="db down"):
        client.get("/insiders/AAPL")
    assert session.closed
