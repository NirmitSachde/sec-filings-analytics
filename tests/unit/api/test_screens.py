"""Tests for the screening endpoints."""

import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sec_filings.api.main import app
from sec_filings.api.routes import screens
from tests.unit.api.fakes import FakeQuery, FakeSession, render

client = TestClient(app)


@pytest.fixture
def install(monkeypatch):
    def _install(session):
        monkeypatch.setattr(screens, "get_session", lambda: session)
        return session

    return _install


# --- /screen/cluster-buying -----------------------------------------------------


def _cluster_row(**overrides):
    row = {
        "issuer_cik": 320193,
        "issuer_name": "Apple Inc.",
        "issuer_ticker": "AAPL",
        "distinct_insiders": 4,
        "total_buy_value": 1_250_000,
        "latest_filing_date": datetime.date(2024, 5, 1),
    }
    row.update(overrides)
    return SimpleNamespace(**row)


def test_cluster_buying_maps_rows(install):
    rows = [
        _cluster_row(),
        _cluster_row(issuer_cik=1, issuer_name="X", issuer_ticker=None, total_buy_value=None),
    ]
    session = install(FakeSession([FakeQuery(rows)]))

    resp = client.get("/screen/cluster-buying")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0] == {
        "issuer_ticker": "AAPL",
        "issuer_name": "Apple Inc.",
        "issuer_cik": 320193,
        "distinct_insiders": 4,
        "total_buy_value": 1_250_000.0,
        "latest_filing_date": "2024-05-01",
    }
    # A NULL sum falls back to 0.0 rather than failing validation.
    assert body[1]["total_buy_value"] == 0.0
    assert body[1]["issuer_ticker"] is None
    assert session.closed


def test_cluster_buying_default_filters(install):
    session = install(FakeSession([FakeQuery([])]))

    resp = client.get("/screen/cluster-buying")

    assert resp.status_code == 200
    assert resp.json() == []
    q = session.queries[0]
    default_since = datetime.date.today() - datetime.timedelta(days=90)
    assert q.rendered_filters() == [
        "raw.insider_transactions.transaction_code = 'P'",
        f"raw.insider_transactions.filing_date >= '{default_since.isoformat()}'",
        "raw.insider_transactions.shares IS NOT NULL",
        "raw.insider_transactions.price_per_share IS NOT NULL",
    ]
    havings = [render(h) for h in q.havings]
    assert havings == [
        "count(distinct(raw.insider_transactions.owner_cik)) >= 3",
        "sum(raw.insider_transactions.shares * raw.insider_transactions.price_per_share) >= 250000",
    ]
    assert len(q.group_bys) == 3
    assert q.rendered_order_bys() == ["count(distinct(raw.insider_transactions.owner_cik)) DESC"]
    assert q.limit_value == 50


def test_cluster_buying_custom_params(install):
    session = install(FakeSession([FakeQuery([])]))

    resp = client.get(
        "/screen/cluster-buying",
        params={"min_insiders": 5, "min_value": 1000, "since": "2023-07-01", "limit": 10},
    )

    assert resp.status_code == 200
    q = session.queries[0]
    assert "raw.insider_transactions.filing_date >= '2023-07-01'" in q.rendered_filters()
    havings = [render(h) for h in q.havings]
    assert havings[0].endswith(">= 5")
    assert havings[1].endswith(">= 1000.0")
    assert q.limit_value == 10


@pytest.mark.parametrize(
    "params",
    [
        {"min_insiders": 1},
        {"min_value": -1},
        {"limit": 501},
        {"since": "nope"},
    ],
)
def test_cluster_buying_validation(install, params):
    session = install(FakeSession([]))
    resp = client.get("/screen/cluster-buying", params=params)
    assert resp.status_code == 422
    assert session.queries == []


# --- /screen/concentration ------------------------------------------------------

LATEST = datetime.date(2024, 6, 30)


def _issuer(cusip, total, ticker="TCK"):
    return SimpleNamespace(
        name_of_issuer=f"Issuer {cusip}", cusip=cusip, ticker=ticker, total_value=total
    )


def _holders(*values):
    return [SimpleNamespace(filer_cik=i, value=v) for i, v in enumerate(values)]


def test_concentration_no_data_returns_empty(install):
    session = install(FakeSession([FakeQuery(scalar=None)]))

    resp = client.get("/screen/concentration")

    assert resp.status_code == 200
    assert resp.json() == []
    assert len(session.queries) == 1
    assert session.closed


def test_concentration_computes_hhi_and_top10(install):
    issuers = [
        _issuer("ONE", 100, ticker=None),  # single holder: HHI 10000, top10 100%
        _issuer("SPLIT", 100),  # 50/50: HHI 5000
        _issuer("WIDE", 1200),  # 12 equal holders: top10 = 83.33%
        _issuer("EMPTY", 50),  # no holder rows: skipped
        _issuer("ZERO", 0),  # zero total: skipped
    ]
    session = install(
        FakeSession(
            [
                FakeQuery(scalar=LATEST),
                FakeQuery(issuers),
                FakeQuery(_holders(100)),
                FakeQuery(_holders(50, 50)),
                FakeQuery(_holders(*([100] * 12))),
                FakeQuery([]),
                FakeQuery(_holders(0)),
            ]
        )
    )

    resp = client.get("/screen/concentration")

    assert resp.status_code == 200
    body = resp.json()
    assert [r["issuer_name"] for r in body] == ["Issuer ONE", "Issuer SPLIT", "Issuer WIDE"]
    assert body[0] == {
        "issuer_name": "Issuer ONE",
        "ticker": None,
        "cik": 0,
        "top10_holder_pct": 100.0,
        "hhi": 10000.0,
    }
    assert body[1]["hhi"] == 5000.0
    assert body[1]["top10_holder_pct"] == 100.0
    assert body[2]["top10_holder_pct"] == 83.33
    assert body[2]["hhi"] == round(12 * (1 / 12) ** 2 * 10000, 2)

    totals_q = session.queries[1]
    assert totals_q.rendered_filters() == ["raw.holdings_positions.period_of_report = '2024-06-30'"]
    assert [render(h) for h in totals_q.havings] == ["sum(raw.holdings_positions.value) > 0"]
    holder_q = session.queries[2]
    assert holder_q.rendered_filters() == [
        "raw.holdings_positions.cusip = 'ONE'",
        "raw.holdings_positions.period_of_report = '2024-06-30'",
    ]
    assert holder_q.rendered_order_bys() == ["raw.holdings_positions.value DESC"]
    assert session.closed


def test_concentration_top_n_truncates_after_sort(install):
    issuers = [_issuer("LOW", 100), _issuer("HIGH", 100)]
    install(
        FakeSession(
            [
                FakeQuery(scalar=LATEST),
                FakeQuery(issuers),
                FakeQuery(_holders(25, 25, 25, 25)),
                FakeQuery(_holders(90, 10)),
            ]
        )
    )

    resp = client.get("/screen/concentration", params={"top_n": 1})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["issuer_name"] == "Issuer HIGH"
    assert body[0]["hhi"] == 8200.0


def test_concentration_top_n_validation(install):
    session = install(FakeSession([]))
    resp = client.get("/screen/concentration", params={"top_n": 101})
    assert resp.status_code == 422
    assert session.queries == []
