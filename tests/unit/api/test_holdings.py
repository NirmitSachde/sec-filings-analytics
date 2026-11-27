"""Tests for the institutional holdings endpoints."""

import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sec_filings.api.main import app
from sec_filings.api.routes import holdings
from tests.unit.api.fakes import FakeQuery, FakeSession

client = TestClient(app)

Q1 = datetime.date(2024, 3, 31)
Q2 = datetime.date(2024, 6, 30)


def _pos(cusip, value, period=Q2, **overrides):
    row = {
        "filer_name": "Big Fund LP",
        "filer_cik": 102909,
        "period_of_report": period,
        "name_of_issuer": f"Issuer {cusip}",
        "cusip": cusip,
        "ticker": f"T{cusip}",
        "value": value,
        "shares": value // 10,
        "investment_discretion": "SOLE",
    }
    row.update(overrides)
    return SimpleNamespace(**row)


@pytest.fixture
def install(monkeypatch):
    def _install(session):
        monkeypatch.setattr(holdings, "get_session", lambda: session)
        return session

    return _install


# --- GET /holdings/{manager_cik} ----------------------------------------------


def test_get_holdings_filters_to_latest_period(install):
    rows = [_pos("AAA", 5000), _pos("BBB", 300, ticker=None, investment_discretion=None)]
    q = FakeQuery(rows, first=rows[0])
    session = install(FakeSession([q]))

    resp = client.get("/holdings/102909")

    assert resp.status_code == 200
    body = resp.json()
    assert [r["cusip"] for r in body] == ["AAA", "BBB"]
    assert body[0] == {
        "filer_name": "Big Fund LP",
        "filer_cik": 102909,
        "period_of_report": "2024-06-30",
        "name_of_issuer": "Issuer AAA",
        "cusip": "AAA",
        "ticker": "TAAA",
        "value": 5000,
        "shares": 500,
        "investment_discretion": "SOLE",
    }
    assert body[1]["ticker"] is None
    assert body[1]["investment_discretion"] is None

    assert q.rendered_filters() == [
        "raw.holdings_positions.filer_cik = 102909",
        "raw.holdings_positions.period_of_report = '2024-06-30'",
    ]
    assert q.rendered_order_bys() == [
        "raw.holdings_positions.period_of_report DESC",
        "raw.holdings_positions.value DESC",
    ]
    assert q.limit_value == 50
    assert session.closed


def test_get_holdings_with_period_param_still_uses_latest(install):
    # The period argument is accepted but currently ignored: both branches pick
    # the latest period. This pins the present behaviour.
    rows = [_pos("AAA", 10)]
    q = FakeQuery(rows, first=rows[0])
    install(FakeSession([q]))

    resp = client.get("/holdings/102909", params={"period": "2023-Q4", "limit": 7})

    assert resp.status_code == 200
    assert resp.json()[0]["period_of_report"] == "2024-06-30"
    assert q.rendered_filters()[-1] == "raw.holdings_positions.period_of_report = '2024-06-30'"
    assert q.limit_value == 7


@pytest.mark.parametrize("params", [{}, {"period": "2024-Q1"}])
def test_get_holdings_unknown_manager_returns_empty(install, params):
    q = FakeQuery([], first=None)
    session = install(FakeSession([q]))

    resp = client.get("/holdings/1", params=params)

    assert resp.status_code == 200
    assert resp.json() == []
    # No period filter is added when there is no latest row.
    assert q.rendered_filters() == ["raw.holdings_positions.filer_cik = 1"]
    assert session.closed


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/holdings/abc", {}),
        ("/holdings/1", {"limit": 501}),
        ("/holdings/changes/abc", {}),
        ("/holdings/changes/1", {"limit": 501}),
    ],
)
def test_holdings_validation_errors(install, path, params):
    session = install(FakeSession([]))
    resp = client.get(path, params=params)
    assert resp.status_code == 422
    assert session.queries == []


# --- GET /holdings/changes/{manager_cik} ----------------------------------------


@pytest.mark.parametrize("periods", [[], [(Q2,)]])
def test_changes_needs_two_periods(install, periods):
    q = FakeQuery(periods)
    session = install(FakeSession([q]))

    resp = client.get("/holdings/changes/102909")

    assert resp.status_code == 200
    assert resp.json() == []
    assert q.distinct_called
    assert q.limit_value == 2
    assert q.rendered_filters() == ["raw.holdings_positions.filer_cik = 102909"]
    assert q.rendered_order_bys() == ["raw.holdings_positions.period_of_report DESC"]
    assert len(session.queries) == 1
    assert session.closed


def _changes_session():
    current = [
        _pos("NEW", 900),  # new position, delta +900
        _pos("UP", 1500),  # increased from 1000, delta +500
        _pos("DOWN", 100),  # reduced from 400, delta -300
        _pos("SAME", 250),  # unchanged, delta 0
    ]
    previous = [
        _pos("UP", 1000, period=Q1),
        _pos("DOWN", 400, period=Q1),
        _pos("SAME", 250, period=Q1),
        _pos("GONE", 2000, period=Q1, ticker=None),  # exited, delta -2000
    ]
    return FakeSession(
        [
            FakeQuery([(Q2,), (Q1,)]),
            FakeQuery(current),
            FakeQuery(previous),
        ]
    )


def test_changes_classifies_and_sorts_by_abs_delta(install):
    session = install(_changes_session())

    resp = client.get("/holdings/changes/102909")

    assert resp.status_code == 200
    body = resp.json()
    assert [(r["cusip"], r["change_type"], r["value_delta"]) for r in body] == [
        ("GONE", "EXITED", -2000),
        ("NEW", "NEW_POSITION", 900),
        ("UP", "INCREASED", 500),
        ("DOWN", "REDUCED", -300),
        ("SAME", "UNCHANGED", 0),
    ]
    by_cusip = {r["cusip"]: r for r in body}
    assert by_cusip["NEW"]["previous_value"] is None
    assert by_cusip["NEW"]["current_value"] == 900
    assert by_cusip["GONE"]["current_value"] == 0
    assert by_cusip["GONE"]["previous_value"] == 2000
    assert by_cusip["GONE"]["ticker"] is None
    assert by_cusip["UP"]["previous_value"] == 1000
    # Every row is stamped with the current period, even exited positions.
    assert {r["period_of_report"] for r in body} == {"2024-06-30"}
    assert {r["filer_cik"] for r in body} == {102909}

    _, cur_q, prev_q = session.queries
    assert cur_q.rendered_filters() == [
        "raw.holdings_positions.filer_cik = 102909",
        "raw.holdings_positions.period_of_report = '2024-06-30'",
    ]
    assert prev_q.rendered_filters() == [
        "raw.holdings_positions.filer_cik = 102909",
        "raw.holdings_positions.period_of_report = '2024-03-31'",
    ]
    assert session.closed


def test_changes_respects_limit(install):
    install(_changes_session())

    resp = client.get("/holdings/changes/102909", params={"limit": 2})

    assert resp.status_code == 200
    assert [r["cusip"] for r in resp.json()] == ["GONE", "NEW"]


def test_changes_session_closed_on_error(install):
    class Boom(FakeSession):
        def query(self, *entities):
            raise RuntimeError("db down")

    session = install(Boom())
    with pytest.raises(RuntimeError):
        client.get("/holdings/changes/1")
    assert session.closed
