"""Unit tests for the yfinance price loader (yfinance and psycopg are mocked)."""

import io
import logging
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from sec_filings.ingestion import price_flow

_FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def _yf_frame(data: dict[str, list[float | None]]) -> pd.DataFrame:
    """Build a frame shaped like yf.download(group_by='ticker'): (ticker, field) columns."""
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])
    cols = {}
    for sym, closes in data.items():
        for field in _FIELDS:
            if field == "Close":
                cols[(sym, field)] = closes
            elif field == "Volume":
                cols[(sym, field)] = [1000.0, None]
            else:
                cols[(sym, field)] = [c if c is None else c - 1 for c in closes]
    df = pd.DataFrame(cols, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def test_yahoo_symbol_and_rate_limit_detection():
    assert price_flow._yahoo_symbol("BRK.B") == "BRK-B"
    assert price_flow._yahoo_symbol("AAPL") == "AAPL"
    assert price_flow._is_rate_limit("YFRateLimitError('Too Many Requests. Rate limited')")
    assert price_flow._is_rate_limit(RuntimeError("Too Many Requests"))
    assert not price_flow._is_rate_limit("possibly delisted; no timezone found")


def test_dsn_uses_plain_postgres_scheme():
    dsn = price_flow._dsn()
    assert dsn.startswith("postgresql://")
    assert "+psycopg" not in dsn


def test_error_capture_only_collects_errors():
    cap = price_flow._ErrorCapture()
    log = logging.getLogger("test_price_flow.capture")
    log.addHandler(cap)
    log.propagate = False
    try:
        log.warning("ignored")
        log.error("['XYZ']: failed")
    finally:
        log.removeHandler(cap)
    assert cap.messages == ["['XYZ']: failed"]


# ---------------------------------------------------------------- _download


def test_download_maps_symbols_and_reshapes(monkeypatch):
    calls = {}

    def fake_download(symbols, **kwargs):
        calls["symbols"] = symbols
        calls["kwargs"] = kwargs
        logging.getLogger("yfinance").error(
            "['GONE']: YFTzMissingError('possibly delisted; no timezone found')"
        )
        return _yf_frame({"BRK-B": [400.0, 401.0], "AAPL": [190.0, None], "EMPTY": [None, None]})

    monkeypatch.setattr(price_flow.yf, "download", fake_download)

    df, errors = price_flow._download(["AAPL", "BRK.B", "EMPTY", "GONE"])

    assert calls["symbols"] == ["AAPL", "BRK-B", "EMPTY", "GONE"]
    assert calls["kwargs"]["auto_adjust"] is True
    assert calls["kwargs"]["group_by"] == "ticker"
    assert calls["kwargs"]["start"] == price_flow._START
    # Rows are keyed by the SEC ticker, NaN closes are dropped, empty symbols vanish.
    assert sorted(df["ticker"].unique()) == ["AAPL", "BRK.B"]
    assert len(df[df["ticker"] == "AAPL"]) == 1
    brk = df[df["ticker"] == "BRK.B"].reset_index(drop=True)
    assert list(brk["close"]) == [400.0, 401.0]
    assert list(brk["adj_close"]) == list(brk["close"])
    assert list(brk["open"]) == [399.0, 400.0]
    assert brk["volume"].dtype == np.int64
    assert list(brk["volume"]) == [1000, 0]
    assert [str(d) for d in brk["date"]] == ["2024-01-02", "2024-01-03"]
    assert list(df.columns) == [
        "ticker",
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
    ]
    assert set(errors) == {"GONE"}
    assert "possibly delisted" in errors["GONE"]
    # The capture handler must be removed afterwards.
    assert not any(
        isinstance(h, price_flow._ErrorCapture) for h in logging.getLogger("yfinance").handlers
    )


@pytest.mark.parametrize("result", [None, pd.DataFrame()])
def test_download_empty_result(monkeypatch, result):
    monkeypatch.setattr(price_flow.yf, "download", lambda *a, **k: result)
    df, errors = price_flow._download(["AAPL"])
    assert df.empty
    assert errors == {}


def test_download_removes_handler_when_yfinance_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network")

    monkeypatch.setattr(price_flow.yf, "download", boom)
    with pytest.raises(RuntimeError):
        price_flow._download(["AAPL"])
    assert not any(
        isinstance(h, price_flow._ErrorCapture) for h in logging.getLogger("yfinance").handlers
    )


# ---------------------------------------------------------------- fetch_prices


class _Db:
    """psycopg.connect stand-in that records SQL and COPY payloads."""

    def __init__(self, done: list[str] | None = None) -> None:
        self.conn = MagicMock()
        self.conn.__enter__.return_value = self.conn
        self.cur = MagicMock()
        self.cur.__enter__.return_value = self.cur
        self.conn.cursor.return_value = self.cur
        self.cur.fetchall.return_value = [(t,) for t in (done or [])]
        self.copied: list[str] = []
        self.copy_sql: list[str] = []

        def copy(sql):
            self.copy_sql.append(sql)
            cp = MagicMock()
            cp.write.side_effect = self.copied.append
            cm = MagicMock()
            cm.__enter__.return_value = cp
            return cm

        self.cur.copy.side_effect = copy

    def sql(self) -> list[str]:
        return [c.args[0] for c in self.cur.execute.call_args_list]

    def misses(self) -> list[tuple]:
        return [
            c.args[1]
            for c in self.cur.execute.call_args_list
            if c.args[0].startswith("insert into raw.price_fetch_misses")
        ]


def _rows(ticker: str, n: int = 2) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": [ticker] * n,
            "date": pd.date_range("2024-01-02", periods=n).date,
            "open": [1.0] * n,
            "high": [2.0] * n,
            "low": [0.5] * n,
            "close": [1.5] * n,
            "adj_close": [1.5] * n,
            "volume": [100] * n,
        }
    )


@pytest.fixture
def sleeps(monkeypatch):
    recorded: list[float] = []
    monkeypatch.setattr(price_flow.time, "sleep", recorded.append)
    return recorded


def _install(monkeypatch, db: _Db, responses):
    """responses: list of (DataFrame, errors) returned by successive _download calls."""
    calls: list[list[str]] = []
    it = iter(responses)

    def fake_download(batch):
        calls.append(list(batch))
        return next(it)

    monkeypatch.setattr(price_flow.psycopg, "connect", lambda dsn: db.conn)
    monkeypatch.setattr(price_flow, "_download", fake_download)
    return calls


def test_fetch_prices_skips_done_and_records_misses(monkeypatch, sleeps):
    db = _Db(done=["MSFT"])
    calls = _install(
        monkeypatch,
        db,
        [(_rows("AAPL", 3), {"ZZZZ": "['ZZZZ']: possibly delisted"})],
    )

    rows, priced = price_flow.fetch_prices(["aapl", "MSFT", "ZZZZ", "", "AAPL", "NODATA"])

    assert (rows, priced) == (3, 1)
    # Uppercased, de-duplicated, sorted, already-done tickers removed.
    assert calls == [["AAPL", "NODATA", "ZZZZ"]]
    sql = db.sql()
    assert sql[0].startswith("create table if not exists raw.price_fetch_misses")
    assert "union select ticker from raw.price_fetch_misses" in sql[1]
    delete = next(c for c in db.cur.execute.call_args_list if c.args[0].startswith("DELETE"))
    assert delete.args[1] == (["AAPL"],)
    assert "COPY raw.daily_prices" in db.copy_sql[0]
    copied = pd.read_csv(io.StringIO(db.copied[0]), header=None)
    assert len(copied) == 3
    assert set(copied[0]) == {"AAPL"}
    assert sorted(db.misses()) == [
        ("NODATA", "no rows returned"),
        ("ZZZZ", "['ZZZZ']: possibly delisted"),
    ]
    assert sleeps == [price_flow._PAUSE_S]
    assert db.conn.commit.call_count == 2


def test_fetch_prices_refresh_ignores_previous_state(monkeypatch, sleeps):
    db = _Db(done=["AAPL"])
    calls = _install(monkeypatch, db, [(_rows("AAPL"), {})])

    assert price_flow.fetch_prices(["AAPL"], refresh=True) == (2, 1)
    assert calls == [["AAPL"]]
    assert not any("union select" in s for s in db.sql())
    db.cur.fetchall.assert_not_called()
    assert db.misses() == []


def test_fetch_prices_batches(monkeypatch, sleeps):
    monkeypatch.setattr(price_flow, "_BATCH", 2)
    db = _Db()
    calls = _install(
        monkeypatch,
        db,
        [(_rows("A"), {}), (_rows("C"), {}), (pd.DataFrame(), {})],
    )

    rows, priced = price_flow.fetch_prices(["E", "D", "C", "B", "A"])

    assert calls == [["A", "B"], ["C", "D"], ["E"]]
    assert (rows, priced) == (4, 2)
    assert [m[0] for m in db.misses()] == ["B", "D", "E"]
    assert sleeps == [price_flow._PAUSE_S] * 3
    # An all-empty batch writes no COPY.
    assert len(db.copied) == 2


def test_fetch_prices_waits_and_retries_rate_limited_batch(monkeypatch, sleeps):
    db = _Db()
    limited = {"AAPL": "['AAPL']: YFRateLimitError('Too Many Requests')"}
    calls = _install(
        monkeypatch,
        db,
        [(pd.DataFrame(), limited), (pd.DataFrame(), limited), (_rows("AAPL"), {})],
    )

    assert price_flow.fetch_prices(["AAPL"]) == (2, 1)
    assert calls == [["AAPL"]] * 3
    waits = price_flow._RATE_LIMIT_WAITS_S
    assert sleeps == [waits[0], waits[1], price_flow._PAUSE_S]
    # A rate-limited ticker is never recorded as missing.
    assert db.misses() == []


def test_fetch_prices_gives_up_after_all_waits(monkeypatch, sleeps):
    monkeypatch.setattr(price_flow, "_RATE_LIMIT_WAITS_S", [1, 2])
    db = _Db()
    limited = {"AAPL": "Too Many Requests"}
    calls = _install(monkeypatch, db, [(pd.DataFrame(), limited)] * 3)

    with pytest.raises(RuntimeError, match="kept rate limiting"):
        price_flow.fetch_prices(["AAPL"])
    assert len(calls) == 3
    assert sleeps == [1, 2]
    assert db.misses() == []


def test_fetch_prices_nothing_to_do(monkeypatch, sleeps):
    db = _Db(done=["AAPL"])
    calls = _install(monkeypatch, db, [])
    assert price_flow.fetch_prices(["AAPL"]) == (0, 0)
    assert calls == []
    assert sleeps == []


def test_tickers_for_backtest(monkeypatch):
    db = _Db(done=["AAPL", "BRK.B"])
    monkeypatch.setattr(price_flow.psycopg, "connect", lambda dsn: db.conn)
    assert price_flow.tickers_for_backtest() == ["AAPL", "BRK.B"]
    assert "int_cluster_buy_events" in db.sql()[0]
