"""CUSIP/CIK/ticker normalization from SEC's company_tickers.json."""

from prefect import flow, task

from sec_filings.db import get_session
from sec_filings.http.edgar_client import EdgarClient
from sec_filings.models import TickerCik

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


@task(retries=2, retry_delay_seconds=30)
async def fetch_ticker_map(client: EdgarClient) -> list[dict]:
    """Pull the SEC company_tickers.json and parse it."""
    response = await client.get(_TICKERS_URL)
    data = response.json()

    records: list[dict] = []
    for entry in data.values():
        records.append(
            {
                "cik": int(entry["cik_str"]),
                "ticker": str(entry["ticker"]).upper(),
                "company_name": str(entry["title"]),
                "exchange": entry.get("exchange"),
            }
        )

    return records


@task
def upsert_ticker_map(records: list[dict]) -> int:
    """Upsert ticker-CIK mappings."""
    if not records:
        return 0

    session = get_session()
    inserted = 0
    try:
        existing = {
            (r.cik, r.ticker)
            for r in session.query(TickerCik.cik, TickerCik.ticker).all()
        }

        for record in records:
            key = (record["cik"], record["ticker"])
            if key not in existing:
                session.add(TickerCik(**record))
                inserted += 1
                existing.add(key)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return inserted


@flow(name="Ticker Map Refresh")
async def refresh_ticker_map() -> int:
    """Refresh the ticker-CIK mapping from SEC."""
    async with EdgarClient() as client:
        records = await fetch_ticker_map(client)
        return upsert_ticker_map(records)


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(refresh_ticker_map())
    print(f"Updated {result} ticker mappings")
