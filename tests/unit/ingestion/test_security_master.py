"""Unit tests for ref.ticker_cik and raw.security_master builders (HTTP and DB mocked)."""

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from sec_filings.ingestion import security_master
from sec_filings.ingestion.security_master import _office


class _Db:
    def __init__(self, fetchall=None) -> None:
        self.conn = MagicMock()
        self.conn.__enter__.return_value = self.conn
        self.cur = MagicMock()
        self.cur.__enter__.return_value = self.cur
        self.conn.cursor.return_value = self.cur
        self.cur.fetchall.return_value = fetchall or []
        self.cp = MagicMock()
        self.cur.copy.return_value.__enter__.return_value = self.cp


class _FakeEdgar:
    """EdgarClient stand-in: maps URL to a JSON payload or an exception."""

    routes: dict = {}
    requested: list[str] = []
    in_flight = 0
    max_in_flight = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url: str) -> httpx.Response:
        cls = type(self)
        cls.requested.append(url)
        cls.in_flight += 1
        cls.max_in_flight = max(cls.max_in_flight, cls.in_flight)
        try:
            await asyncio.sleep(0)
            payload = cls.routes[url]
            if isinstance(payload, Exception):
                raise payload
            return httpx.Response(200, json=payload)
        finally:
            cls.in_flight -= 1


@pytest.fixture
def edgar(monkeypatch):
    class Fake(_FakeEdgar):
        routes = {}
        requested = []
        in_flight = 0
        max_in_flight = 0

    monkeypatch.setattr(security_master, "EdgarClient", Fake)
    return Fake


def _connect(monkeypatch, *dbs: _Db) -> list[str]:
    dsns: list[str] = []
    it = iter(dbs)

    def connect(dsn):
        dsns.append(dsn)
        return next(it).conn

    monkeypatch.setattr(security_master.psycopg, "connect", connect)
    return dsns


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("06 Technology", "Technology"),
        ("Office of Energy & Transportation", "Office of Energy & Transportation"),
        ("01", None),
        ("", None),
        (None, None),
    ],
)
def test_office(raw, expected):
    assert _office(raw) == expected


async def test_refresh_ticker_cik_reloads_in_sec_order(monkeypatch, edgar):
    edgar.routes[security_master._TICKERS_URL] = {
        "0": {"cik_str": 1326801, "ticker": "meta", "title": "Meta Platforms, Inc."},
        "1": {"cik_str": "1067983", "ticker": "BRK-B", "title": "B" * 250},
        "2": {"cik_str": 1067983, "ticker": "BRK-A", "title": "Berkshire"},
    }
    db = _Db()
    dsns = _connect(monkeypatch, db)

    assert await security_master.refresh_ticker_cik() == 3

    assert dsns[0].startswith("postgresql://")
    db.cur.execute.assert_called_once_with("TRUNCATE ref.ticker_cik RESTART IDENTITY")
    assert "COPY ref.ticker_cik (cik, ticker, company_name)" in db.cur.copy.call_args.args[0]
    rows = [c.args[0] for c in db.cp.write_row.call_args_list]
    assert rows == [
        (1326801, "META", "Meta Platforms, Inc."),
        (1067983, "BRK-B", "B" * 200),
        (1067983, "BRK-A", "Berkshire"),
    ]
    db.conn.commit.assert_called_once()


def _sub_url(cik: int) -> str:
    return security_master._SUBMISSIONS_URL.format(cik=cik)


async def test_refresh_sectors_classifies_and_skips_failures(monkeypatch, edgar):
    edgar.routes.update(
        {
            _sub_url(320193): {
                "name": "Apple Inc.",
                "ownerOrg": "06 Technology",
                "sic": 3571,
                "sicDescription": "Electronic Computers",
                "tickers": ["AAPL"],
            },
            _sub_url(1): {"name": None, "ownerOrg": None, "sic": "", "tickers": []},
            _sub_url(2): httpx.ConnectError("reset"),
        }
    )
    pick = _Db(fetchall=[("AAPL", 320193), ("OLD", 1), ("FAIL", 2)])
    write = _Db()
    _connect(monkeypatch, pick, write)

    assert await security_master.refresh_sectors() == 2

    select_sql = pick.cur.execute.call_args.args[0]
    assert "int_cluster_buy_events" in select_sql
    assert "m.ticker is null" in select_sql  # only tickers not yet classified
    assert sorted(edgar.requested) == sorted([_sub_url(320193), _sub_url(1), _sub_url(2)])
    assert _sub_url(320193).endswith("CIK0000320193.json")

    sql, rows = write.cur.executemany.call_args.args
    assert "on conflict (ticker) do update" in sql
    by_ticker = {r[0]: r for r in rows}
    assert set(by_ticker) == {"AAPL", "OLD"}
    assert by_ticker["AAPL"] == (
        "AAPL",
        320193,
        "Apple Inc.",
        "Technology",
        "3571",
        "Electronic Computers",
        True,
    )
    assert by_ticker["OLD"] == ("OLD", 1, "", None, None, None, False)
    write.conn.commit.assert_called_once()


async def test_refresh_sectors_respects_concurrency(monkeypatch, edgar):
    pairs = [(f"T{i}", i) for i in range(1, 9)]
    for _, cik in pairs:
        edgar.routes[_sub_url(cik)] = {"name": "x", "tickers": ["x"]}
    _connect(monkeypatch, _Db(fetchall=pairs), _Db())

    assert await security_master.refresh_sectors(concurrency=3) == 8
    assert edgar.max_in_flight == 3


async def test_refresh_sectors_with_nothing_to_classify(monkeypatch, edgar):
    write = _Db()
    _connect(monkeypatch, _Db(fetchall=[]), write)
    assert await security_master.refresh_sectors() == 0
    assert edgar.requested == []
    assert write.cur.executemany.call_args.args[1] == []
