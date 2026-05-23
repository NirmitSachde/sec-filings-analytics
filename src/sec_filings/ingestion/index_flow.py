"""Prefect flow to crawl EDGAR full-text index files and populate raw.filing_index."""

import datetime
import re

from prefect import flow, task

from sec_filings.config import get_settings
from sec_filings.db import get_session
from sec_filings.http.edgar_client import EDGAR_BASE, EdgarClient
from sec_filings.models import FilingIndex

_FORM_TYPES = {"4", "4/A", "13F-HR", "13F-HR/A", "10-K", "10-K/A", "10-Q", "10-Q/A"}

_INDEX_LINE_RE = re.compile(
    r"^(.{12})\s+(.{62})\s+(\d{10})\s+(\d{4}-\d{2}-\d{2})\s+(.+)$"
)


def _quarter_for_month(month: int) -> int:
    return (month - 1) // 3 + 1


def _index_urls(start_date: datetime.date, end_date: datetime.date) -> list[str]:
    urls: list[str] = []
    current = start_date.replace(day=1)
    seen: set[tuple[int, int]] = set()

    while current <= end_date:
        qtr = _quarter_for_month(current.month)
        key = (current.year, qtr)
        if key not in seen:
            seen.add(key)
            urls.append(
                f"{EDGAR_BASE}/Archives/edgar/full-index/{current.year}/QTR{qtr}/form.idx"
            )
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return urls


@task(retries=2, retry_delay_seconds=30)
async def fetch_and_parse_index(client: EdgarClient, url: str) -> list[dict]:
    """Download a form.idx file and parse it into filing records."""
    text = await client.get_text(url)
    records: list[dict] = []

    in_data = False
    for line in text.splitlines():
        if line.startswith("---"):
            in_data = True
            continue
        if not in_data:
            continue

        parts = line.split()
        if len(parts) < 5:
            continue

        form_type = parts[0]
        if form_type not in _FORM_TYPES:
            continue

        # Fixed-width parsing: form_type, company_name, cik, date, filename
        match = _INDEX_LINE_RE.match(line)
        if match:
            form_type_raw = match.group(1).strip()
            company_name = match.group(2).strip()
            cik = int(match.group(3))
            date_filed = datetime.date.fromisoformat(match.group(4))
            filename = match.group(5).strip()
        else:
            # Fallback: split by whitespace
            form_type_raw = parts[0]
            filename = parts[-1]
            date_filed_str = parts[-2]
            cik = int(parts[-3])
            company_name = " ".join(parts[1:-3])
            try:
                date_filed = datetime.date.fromisoformat(date_filed_str)
            except ValueError:
                continue

        accession = filename.split("/")[-1].replace(".txt", "").replace("-index.htm", "")
        if not accession:
            continue

        records.append(
            {
                "accession_number": accession,
                "form_type": form_type_raw,
                "cik": cik,
                "company_name": company_name,
                "date_filed": date_filed,
                "filename": filename,
            }
        )

    return records


@task
def upsert_filings(records: list[dict]) -> int:
    """Insert filing index records with UPSERT semantics (skip duplicates)."""
    if not records:
        return 0

    session = get_session()
    inserted = 0
    try:
        existing = {
            r[0]
            for r in session.query(FilingIndex.accession_number)
            .filter(
                FilingIndex.accession_number.in_([r["accession_number"] for r in records])
            )
            .all()
        }

        new_records = [r for r in records if r["accession_number"] not in existing]
        for record in new_records:
            session.add(FilingIndex(**record))
            inserted += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return inserted


@flow(name="EDGAR Index Crawler")
async def crawl_edgar_index(
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> int:
    """Crawl EDGAR full-text index files for a date range.

    Defaults to the last 5 years if no range specified.
    """
    if end_date is None:
        end_date = datetime.date.today()
    if start_date is None:
        start_date = end_date.replace(year=end_date.year - 5)

    urls = _index_urls(start_date, end_date)

    total_inserted = 0
    async with EdgarClient() as client:
        for url in urls:
            records = await fetch_and_parse_index(client, url)
            inserted = upsert_filings(records)
            total_inserted += inserted

    return total_inserted


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(crawl_edgar_index())
    print(f"Inserted {result} filing index records")
