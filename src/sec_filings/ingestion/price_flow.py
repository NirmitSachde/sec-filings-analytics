"""Daily price ingestion for the signal-validation backtest.

Source: Yahoo Finance via yfinance, adjusted for splits and dividends
(auto_adjust=True), so a return computed from adj_close is a total return.
Stooq, the original source, now sits behind a browser bot check, so it is no
longer usable from a script.

Only the tickers that actually appear in a cluster-buy event are fetched, plus
SPY for the benchmark, instead of the whole market.

Known limitation: Yahoo drops most delisted tickers, so signals whose stock was
later delisted, acquired or went bankrupt cannot be priced and fall out of the
backtest. That survivorship bias flatters the results; the backtest summary
reports how many signals were dropped for missing prices.
"""

from __future__ import annotations

import io
import logging
import sys
import time

import pandas as pd
import psycopg
import yfinance as yf

from sec_filings.config import get_settings

logger = logging.getLogger(__name__)

_BATCH = 25
_START = "2013-06-01"
_PAUSE_S = 8  # between batches, to stay under Yahoo's rate limit
# Waits after a rate-limited batch: 2, 5, 10, then 15 minutes (about 2.5 hours in all).
_RATE_LIMIT_WAITS_S = [120, 300, 600] + [900] * 8


def _dsn() -> str:
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


def _yahoo_symbol(ticker: str) -> str:
    """SEC writes class shares as BRK.B, Yahoo as BRK-B."""
    return ticker.replace(".", "-")


def _is_rate_limit(err: object) -> bool:
    text = str(err)
    return "RateLimit" in text or "Too Many Requests" in text


class _ErrorCapture(logging.Handler):
    """yfinance logs per-ticker failures instead of raising; collect them per batch."""

    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _download(tickers: list[str]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Download one batch. Returns long-format rows keyed by SEC ticker, plus per-ticker errors."""
    mapping = {_yahoo_symbol(t): t for t in tickers}
    capture = _ErrorCapture()
    yf_logger = logging.getLogger("yfinance")
    yf_logger.addHandler(capture)
    try:
        raw = yf.download(
            list(mapping),
            start=_START,
            auto_adjust=True,
            actions=False,
            group_by="ticker",
            threads=4,
            progress=False,
        )
    finally:
        yf_logger.removeHandler(capture)
    # Messages look like "['ABC', 'XYZ']: YFRateLimitError('Too Many Requests...')".
    errors: dict[str, str] = {}
    for msg in capture.messages:
        for ysym, sec_ticker in mapping.items():
            if f"'{ysym}'" in msg:
                errors[sec_ticker] = msg[-300:]
    if raw is None or raw.empty:
        return pd.DataFrame(), errors
    frames = []
    for ysym, sec_ticker in mapping.items():
        if ysym not in raw.columns.get_level_values(0):
            continue
        df = raw[ysym].dropna(subset=["Close"])
        if df.empty:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "ticker": sec_ticker,
                    "date": df.index.date,
                    "open": df["Open"].to_numpy(),
                    "high": df["High"].to_numpy(),
                    "low": df["Low"].to_numpy(),
                    "close": df["Close"].to_numpy(),
                    "adj_close": df["Close"].to_numpy(),  # auto_adjust: Close is adjusted
                    "volume": df["Volume"].fillna(0).astype("int64").to_numpy(),
                }
            )
        )
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), errors


def fetch_prices(tickers: list[str], refresh: bool = False) -> tuple[int, int]:
    """Fetch prices into raw.daily_prices. Returns (rows written, tickers priced).

    Resumable: tickers already priced, or already confirmed missing on Yahoo
    (raw.price_fetch_misses), are skipped unless refresh=True. Batches that hit
    Yahoo's rate limit wait and retry instead of being recorded as missing.
    """
    tickers = sorted({t.upper() for t in tickers if t})
    rows = priced = 0
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "create table if not exists raw.price_fetch_misses ("
            "ticker varchar(20) primary key, reason text, checked_at timestamptz default now())"
        )
        if not refresh:
            cur.execute(
                "select ticker from raw.daily_prices group by ticker "
                "union select ticker from raw.price_fetch_misses"
            )
            done = {r[0] for r in cur.fetchall()}
            tickers = [t for t in tickers if t not in done]
        conn.commit()
        logger.info("%d tickers to fetch", len(tickers))

        i = 0
        while i < len(tickers):
            batch = tickers[i : i + _BATCH]
            for wait in [*_RATE_LIMIT_WAITS_S, None]:
                df, errors = _download(batch)
                limited = [t for t, e in errors.items() if _is_rate_limit(e)]
                if not limited:
                    break
                if wait is None:
                    raise RuntimeError(
                        "Yahoo kept rate limiting; rerun later, finished batches are kept"
                    )
                logger.warning("rate limited (%d tickers), waiting %ds", len(limited), wait)
                time.sleep(wait)

            got = set(df["ticker"].unique()) if not df.empty else set()
            if got:
                cur.execute("DELETE FROM raw.daily_prices WHERE ticker = ANY(%s)", (list(got),))
                buf = io.StringIO()
                df.to_csv(buf, index=False, header=False)
                with cur.copy(
                    "COPY raw.daily_prices "
                    "(ticker, date, open, high, low, close, adj_close, volume) "
                    "FROM STDIN WITH (FORMAT csv)"
                ) as cp:
                    cp.write(buf.getvalue())
            for t in batch:
                if t not in got:
                    cur.execute(
                        "insert into raw.price_fetch_misses (ticker, reason) values (%s, %s) "
                        "on conflict (ticker) do update "
                        "set reason = excluded.reason, checked_at = now()",
                        (t, errors.get(t, "no rows returned")[:500]),
                    )
            conn.commit()
            rows += len(df)
            priced += len(got)
            logger.info("batch %d-%d: %d of %d priced", i, i + len(batch), len(got), len(batch))
            i += _BATCH
            time.sleep(_PAUSE_S)
    return rows, priced


def tickers_for_backtest() -> list[str]:
    """Every ticker that has a cluster-buy event (needs `dbt run` of the intermediate models)."""
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "select distinct issuer_ticker from public_intermediate.int_cluster_buy_events "
            "where issuer_ticker is not null"
        )
        return [r[0] for r in cur.fetchall()]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    wanted = sys.argv[1:] or tickers_for_backtest()
    wanted.append("SPY")
    n_rows, n_priced = fetch_prices(wanted)
    print(f"Priced {n_priced} new tickers this run ({n_rows:,} rows)")
