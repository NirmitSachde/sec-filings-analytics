"""Daily price ingestion for the signal-validation backtest.

Source: Stooq free end-of-day CSV. No API key, no rate limit beyond
common-courtesy throttling. Each ticker's full history fits in a single
GET; we paginate by ticker, not by date.

The same CSV format covers SPY for the benchmark leg, so we treat it as
just another row in the input ticker list.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import date
from typing import Iterable

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from sec_filings.db import get_engine
from sec_filings.models import DailyPrice

logger = logging.getLogger(__name__)

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}.us&i=d"
SPY_URL = "https://stooq.com/q/d/l/?s=spy.us&i=d"


async def _fetch_one(client: httpx.AsyncClient, ticker: str) -> list[dict]:
    """Fetch one ticker's full daily history from Stooq."""
    url = SPY_URL if ticker.upper() == "SPY" else STOOQ_URL.format(symbol=ticker.lower())
    resp = await client.get(url, timeout=30.0)
    resp.raise_for_status()
    if not resp.text or resp.text.startswith("No data"):
        logger.warning("No data returned for %s", ticker)
        return []

    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for r in reader:
        try:
            rows.append(
                {
                    "ticker": ticker.upper(),
                    "price_date": date.fromisoformat(r["Date"]),
                    "open": float(r["Open"]),
                    "high": float(r["High"]),
                    "low": float(r["Low"]),
                    "close": float(r["Close"]),
                    "adj_close": float(r["Close"]),  # Stooq already adjusts
                    "volume": int(float(r.get("Volume") or 0)),
                }
            )
        except (KeyError, ValueError) as exc:
            logger.debug("Skipping malformed row for %s: %s", ticker, exc)
    return rows


async def fetch_prices(tickers: Iterable[str], concurrency: int = 5) -> int:
    """Fetch and upsert daily prices for the given tickers. Returns row count."""
    sem = asyncio.Semaphore(concurrency)
    written = 0

    async with httpx.AsyncClient(http2=True, headers={"User-Agent": "sec-filings-analytics/0.1"}) as client:

        async def _worker(t: str) -> list[dict]:
            async with sem:
                return await _fetch_one(client, t)

        results = await asyncio.gather(*(_worker(t) for t in tickers), return_exceptions=True)

    engine = get_engine()
    with engine.begin() as conn:
        for r in results:
            if isinstance(r, Exception):
                logger.error("Fetch failed: %s", r)
                continue
            if not r:
                continue
            stmt = insert(DailyPrice).values(r)
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker", "price_date"],
                set_={c: stmt.excluded[c] for c in ("open", "high", "low", "close", "adj_close", "volume")},
            )
            conn.execute(stmt)
            written += len(r)

    return written


async def fetch_universe_for_backtest() -> int:
    """Fetch the Russell-1000-ish universe plus SPY benchmark."""
    engine = get_engine()
    with engine.connect() as conn:
        tickers = [row[0] for row in conn.execute(text("select ticker from ref.ticker_cik where is_active"))]
    tickers.append("SPY")
    logger.info("Fetching %d tickers", len(tickers))
    return await fetch_prices(tickers)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(fetch_universe_for_backtest())
