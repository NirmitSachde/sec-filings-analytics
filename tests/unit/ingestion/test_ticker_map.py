"""Unit tests for the SQLAlchemy-backed ticker map refresh."""

from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from sec_filings.ingestion import ticker_map
from sec_filings.models import TickerCik

# SQLAlchemy returns Row objects with attribute access, like a namedtuple.
_Row = namedtuple("_Row", ["cik", "ticker"])

_SEC_JSON = {
    "0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."},
    "1": {"cik_str": "789019", "ticker": "MSFT", "title": "MICROSOFT CORP", "exchange": "Nasdaq"},
}


async def test_fetch_ticker_map_normalizes_entries():
    client = MagicMock()
    client.get = AsyncMock(return_value=httpx.Response(200, json=_SEC_JSON))

    records = await ticker_map.fetch_ticker_map.fn(client)

    client.get.assert_awaited_once_with("https://www.sec.gov/files/company_tickers.json")
    assert records == [
        {"cik": 320193, "ticker": "AAPL", "company_name": "Apple Inc.", "exchange": None},
        {"cik": 789019, "ticker": "MSFT", "company_name": "MICROSOFT CORP", "exchange": "Nasdaq"},
    ]


def test_upsert_ticker_map_empty(monkeypatch):
    get_session = MagicMock()
    monkeypatch.setattr(ticker_map, "get_session", get_session)
    assert ticker_map.upsert_ticker_map.fn([]) == 0
    get_session.assert_not_called()


def _rec(cik: int, ticker: str) -> dict:
    return {"cik": cik, "ticker": ticker, "company_name": "N", "exchange": None}


def test_upsert_ticker_map_inserts_only_new_pairs(monkeypatch):
    session = MagicMock()
    session.query.return_value.all.return_value = [_Row(320193, "AAPL")]
    monkeypatch.setattr(ticker_map, "get_session", lambda: session)

    inserted = ticker_map.upsert_ticker_map.fn(
        [
            _rec(320193, "AAPL"),  # already stored
            _rec(789019, "MSFT"),
            _rec(789019, "MSFT"),  # duplicate inside the same batch
            _rec(1652044, "GOOG"),
        ]
    )

    assert inserted == 2
    added = [c.args[0] for c in session.add.call_args_list]
    assert all(isinstance(a, TickerCik) for a in added)
    assert [(a.cik, a.ticker) for a in added] == [(789019, "MSFT"), (1652044, "GOOG")]
    session.commit.assert_called_once()
    session.close.assert_called_once()


def test_upsert_ticker_map_rolls_back_on_error(monkeypatch):
    session = MagicMock()
    session.query.return_value.all.return_value = []
    session.commit.side_effect = RuntimeError("boom")
    monkeypatch.setattr(ticker_map, "get_session", lambda: session)

    with pytest.raises(RuntimeError):
        ticker_map.upsert_ticker_map.fn([_rec(1, "A")])
    session.rollback.assert_called_once()
    session.close.assert_called_once()


async def test_refresh_ticker_map_wires_fetch_into_upsert(monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    seen = {}

    async def fake_fetch(client):
        seen["client"] = client
        return [_rec(1, "A"), _rec(2, "B")]

    def fake_upsert(records):
        seen["records"] = records
        return len(records)

    monkeypatch.setattr(ticker_map, "EdgarClient", FakeClient)
    monkeypatch.setattr(ticker_map, "fetch_ticker_map", fake_fetch)
    monkeypatch.setattr(ticker_map, "upsert_ticker_map", fake_upsert)

    assert await ticker_map.refresh_ticker_map.fn() == 2
    assert isinstance(seen["client"], FakeClient)
    assert [r["ticker"] for r in seen["records"]] == ["A", "B"]
