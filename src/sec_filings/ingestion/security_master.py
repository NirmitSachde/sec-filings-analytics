"""Build raw.security_master and ref.ticker_cik from the SEC's own data.

- ref.ticker_cik: every current ticker from https://www.sec.gov/files/company_tickers.json
  (the first ticker listed for a CIK is treated as its primary listing). The backtest
  uses it to price a company under its current ticker, so a company that renamed its
  ticker after a filing (FB to META) still gets prices.
- raw.security_master: one row per backtest ticker with the SEC industry office
  (ownerOrg, e.g. "Technology", "Energy & Transportation") as the sector and the SIC
  description as the industry, read from https://data.sec.gov/submissions/CIK##########.json.
  These are SEC classifications, not MSCI GICS.

All requests go through EdgarClient, which stays under the 10 requests per second limit.

Usage:
    uv run python -m sec_filings.ingestion.security_master tickers   # before dbt run
    uv run python -m sec_filings.ingestion.security_master sectors   # after dbt run
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys

import psycopg

from sec_filings.config import get_settings
from sec_filings.http.edgar_client import EdgarClient

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def _dsn() -> str:
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


async def refresh_ticker_cik() -> int:
    async with EdgarClient() as client:
        data = (await client.get(_TICKERS_URL)).json()
    rows = [
        (int(e["cik_str"]), str(e["ticker"]).upper(), str(e["title"])[:200]) for e in data.values()
    ]
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE ref.ticker_cik RESTART IDENTITY")
        # Insert in SEC order so the lowest id per CIK is its primary ticker.
        with cur.copy("COPY ref.ticker_cik (cik, ticker, company_name) FROM STDIN") as cp:
            for row in rows:
                cp.write_row(row)
        conn.commit()
    return len(rows)


def _office(owner_org: str | None) -> str | None:
    """'06 Technology' -> 'Technology'."""
    if not owner_org:
        return None
    return re.sub(r"^\d+\s*", "", owner_org).strip() or None


async def refresh_sectors(concurrency: int = 2) -> int:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "select distinct on (e.issuer_ticker) e.issuer_ticker, e.issuer_cik "
            "from public_intermediate.int_cluster_buy_events e "
            "left join raw.security_master m on m.ticker = e.issuer_ticker "
            "where e.issuer_ticker is not null and m.ticker is null "
            "order by e.issuer_ticker, e.signal_date desc"
        )
        pairs = cur.fetchall()

    sem = asyncio.Semaphore(concurrency)
    results: list[tuple] = []

    async with EdgarClient() as client:

        async def one(ticker: str, cik: int) -> None:
            async with sem:
                try:
                    d = (await client.get(_SUBMISSIONS_URL.format(cik=cik))).json()
                except Exception as exc:  # noqa: BLE001  (record as unclassified, keep going)
                    logger.warning("submissions failed for %s (%s): %s", ticker, cik, exc)
                    return
                results.append(
                    (
                        ticker,
                        cik,
                        (d.get("name") or "")[:200],
                        _office(d.get("ownerOrg")),
                        str(d.get("sic") or "")[:100] or None,
                        (d.get("sicDescription") or "")[:200] or None,
                        bool(d.get("tickers")),
                    )
                )

        await asyncio.gather(*(one(t, c) for t, c in pairs))

    # Upsert, so a run that hits SEC throttling can simply be repeated for the rest.
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.executemany(
            "insert into raw.security_master (ticker, cik, company_name, gics_sector, "
            "gics_industry_group, gics_industry, is_active) values (%s, %s, %s, %s, %s, %s, %s) "
            "on conflict (ticker) do update set cik = excluded.cik, "
            "company_name = excluded.company_name, gics_sector = excluded.gics_sector, "
            "gics_industry_group = excluded.gics_industry_group, "
            "gics_industry = excluded.gics_industry, is_active = excluded.is_active",
            results,
        )
        conn.commit()
    return len(results)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    step = sys.argv[1] if len(sys.argv) > 1 else "tickers"
    if step == "tickers":
        print(f"ref.ticker_cik: {asyncio.run(refresh_ticker_cik()):,} tickers")
    elif step == "sectors":
        print(f"raw.security_master: {asyncio.run(refresh_sectors()):,} tickers classified")
    else:
        raise SystemExit("step must be 'tickers' or 'sectors'")
