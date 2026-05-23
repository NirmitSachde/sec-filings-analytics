"""Prefect flow to fetch individual filings from EDGAR and run parsers."""

import datetime
import json
import traceback
from pathlib import Path

from prefect import flow, task
from sqlalchemy import func

from sec_filings.config import get_settings
from sec_filings.db import get_session
from sec_filings.http.edgar_client import EDGAR_BASE, EDGAR_DATA_BASE, EdgarClient
from sec_filings.ingestion.deadletter import record_parse_failure
from sec_filings.models import (
    FilingIndex,
    FilingSection,
    HoldingsPosition,
    InsiderTransaction,
    XbrlFact,
)
from sec_filings.parsers.form4 import parse_form4
from sec_filings.parsers.form10k import parse_form10k
from sec_filings.parsers.form13f import parse_form13f

_RAW_DIR = Path("data/raw")
_PARSER_VERSION = "0.1.0"


def _filing_dir(form_type: str, cik: int, accession: str) -> Path:
    clean_form = form_type.replace("/", "_")
    return _RAW_DIR / clean_form / str(cik) / accession


@task(retries=1, retry_delay_seconds=10)
async def fetch_filing(
    client: EdgarClient, filing: FilingIndex
) -> Path | None:
    """Download raw filing documents to the local raw zone."""
    out_dir = _filing_dir(filing.form_type, filing.cik, filing.accession_number)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_url = f"{EDGAR_BASE}/Archives/{filing.filename}"

    # Fetch the filing index page to find document URLs
    try:
        index_url = base_url.rsplit("/", 1)[0] + "/"
        index_html = await client.get_text(index_url)
    except Exception:
        index_html = ""

    # Always try to fetch the primary document
    primary_path = out_dir / "primary.txt"
    if not primary_path.exists():
        try:
            content = await client.get_bytes(base_url)
            primary_path.write_bytes(content)
        except Exception:
            return None

    return out_dir


@task
def parse_and_store_form4(raw_dir: Path, filing: FilingIndex) -> bool:
    """Parse a Form 4 filing and store transactions."""
    xml_files = list(raw_dir.glob("*.xml")) + [raw_dir / "primary.txt"]

    for xml_file in xml_files:
        if not xml_file.exists():
            continue
        try:
            content = xml_file.read_text(encoding="utf-8", errors="replace")
            if "<ownershipDocument" not in content:
                continue

            result = parse_form4(content, filing.accession_number)

            session = get_session()
            try:
                for tx in result.transactions:
                    session.merge(
                        InsiderTransaction(
                            accession_number=tx.accession_number,
                            filing_date=tx.filing_date,
                            transaction_index=tx.transaction_index,
                            owner_cik=tx.owner_cik,
                            owner_name=tx.owner_name,
                            is_director=tx.is_director,
                            is_officer=tx.is_officer,
                            is_ten_percent_owner=tx.is_ten_percent_owner,
                            is_other=tx.is_other,
                            officer_title=tx.officer_title,
                            issuer_cik=tx.issuer_cik,
                            issuer_name=tx.issuer_name,
                            issuer_ticker=tx.issuer_ticker,
                            security_title=tx.security_title,
                            transaction_date=tx.transaction_date,
                            transaction_code=tx.transaction_code,
                            shares=tx.shares,
                            price_per_share=tx.price_per_share,
                            shares_after=tx.shares_after,
                            direct_or_indirect=tx.direct_or_indirect,
                            is_derivative=tx.is_derivative,
                            is_10b5_1=tx.is_10b5_1,
                        )
                    )
                session.commit()
                return True
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        except Exception as e:
            record_parse_failure(filing.accession_number, "4", e, _PARSER_VERSION)

    return False


@task
def parse_and_store_form13f(raw_dir: Path, filing: FilingIndex) -> bool:
    """Parse a Form 13F-HR filing and store holdings."""
    try:
        primary = raw_dir / "primary.txt"
        if not primary.exists():
            return False

        content = primary.read_text(encoding="utf-8", errors="replace")

        # 13F-HR needs both the primary doc and info table
        # For now, attempt to parse the primary document as both
        info_table_files = list(raw_dir.glob("*infotable*")) + list(raw_dir.glob("*INFOTABLE*"))
        info_content = content
        if info_table_files:
            info_content = info_table_files[0].read_text(encoding="utf-8", errors="replace")

        result = parse_form13f(info_content, content, filing.accession_number)

        session = get_session()
        try:
            for h in result.holdings:
                session.merge(
                    HoldingsPosition(
                        accession_number=result.accession_number,
                        filer_cik=result.filer_cik,
                        filer_name=result.filer_name,
                        period_of_report=result.period_of_report,
                        name_of_issuer=h.name_of_issuer,
                        cusip=h.cusip,
                        ticker=h.ticker,
                        value=h.value,
                        shares=h.shares,
                        share_type=h.share_type,
                        investment_discretion=h.investment_discretion,
                        voting_sole=h.voting_sole,
                        voting_shared=h.voting_shared,
                        voting_none=h.voting_none,
                    )
                )
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    except Exception as e:
        record_parse_failure(filing.accession_number, "13F-HR", e, _PARSER_VERSION)

    return False


@task
def parse_and_store_form10k(raw_dir: Path, filing: FilingIndex) -> bool:
    """Parse a Form 10-K filing and store XBRL facts + text sections."""
    try:
        primary = raw_dir / "primary.txt"
        html_content = None
        if primary.exists():
            html_content = primary.read_text(encoding="utf-8", errors="replace")

        result = parse_form10k(
            html_content=html_content,
            xbrl_facts_json=None,
            accession_number=filing.accession_number,
            cik=filing.cik,
        )

        session = get_session()
        try:
            for section in result.sections:
                session.merge(
                    FilingSection(
                        accession_number=section.accession_number,
                        cik=section.cik,
                        section=section.section,
                        text=section.text,
                        char_count=section.char_count,
                    )
                )

            for fact in result.xbrl_facts:
                session.merge(
                    XbrlFact(
                        accession_number=fact.accession_number,
                        cik=fact.cik,
                        concept=fact.concept,
                        value=fact.value,
                        unit=fact.unit,
                        decimals=fact.decimals,
                        period_start=fact.period_start,
                        period_end=fact.period_end,
                        context_id=fact.context_id,
                        is_instant=fact.is_instant,
                    )
                )

            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    except Exception as e:
        record_parse_failure(filing.accession_number, "10-K", e, _PARSER_VERSION)

    return False


@task
def mark_filing_parsed(filing_id: int) -> None:
    session = get_session()
    try:
        session.query(FilingIndex).filter(FilingIndex.id == filing_id).update(
            {"parsed_at": func.now()}
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_FORM_PARSERS = {
    "4": parse_and_store_form4,
    "4/A": parse_and_store_form4,
    "13F-HR": parse_and_store_form13f,
    "13F-HR/A": parse_and_store_form13f,
    "10-K": parse_and_store_form10k,
    "10-K/A": parse_and_store_form10k,
    "10-Q": parse_and_store_form10k,
    "10-Q/A": parse_and_store_form10k,
}


@flow(name="EDGAR Filing Fetcher")
async def fetch_and_parse_filings(
    batch_size: int = 100,
    form_types: list[str] | None = None,
) -> dict[str, int]:
    """Fetch and parse unfetched filings from the index."""
    session = get_session()
    try:
        query = session.query(FilingIndex).filter(FilingIndex.parsed_at.is_(None))

        if form_types:
            query = query.filter(FilingIndex.form_type.in_(form_types))

        filings = query.order_by(FilingIndex.date_filed.desc()).limit(batch_size).all()
    finally:
        session.close()

    stats: dict[str, int] = {"fetched": 0, "parsed": 0, "failed": 0}

    async with EdgarClient() as client:
        for filing in filings:
            raw_dir = await fetch_filing(client, filing)
            if raw_dir is None:
                stats["failed"] += 1
                continue
            stats["fetched"] += 1

            # Mark fetched
            s = get_session()
            try:
                s.query(FilingIndex).filter(FilingIndex.id == filing.id).update(
                    {"fetched_at": func.now()}
                )
                s.commit()
            finally:
                s.close()

            parser = _FORM_PARSERS.get(filing.form_type)
            if parser and parser(raw_dir, filing):
                mark_filing_parsed(filing.id)
                stats["parsed"] += 1
            else:
                stats["failed"] += 1

    return stats


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(fetch_and_parse_filings())
    print(f"Filing fetch results: {result}")
