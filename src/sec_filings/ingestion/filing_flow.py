"""Prefect flow to fetch individual filings from EDGAR and run parsers.

Each index entry points at the complete submission text file, which wraps every
document of the filing in <DOCUMENT> blocks. fetch_filing saves that file as
primary.txt and splits it into one file per document, listed in documents.json,
so each parser reads the document it needs: the ownership XML for Form 4, the
primary doc and the information table for 13F-HR, and the main HTML for 10-K
and 10-Q (plus the issuer's XBRL companyfacts JSON).
"""

import json
import re
from pathlib import Path
from typing import Any

from prefect import flow, task
from sqlalchemy import func

from sec_filings.db import get_session
from sec_filings.http.edgar_client import EDGAR_BASE, EdgarClient
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
_PARSER_VERSION = "0.2.0"
_MANIFEST = "documents.json"
_FACTS = "companyfacts.json"
_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_XBRL_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}

_DOC_RE = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.DOTALL | re.IGNORECASE)
_TAG_RE = {
    name: re.compile(rf"^<{name}>([^\r\n<]*)", re.MULTILINE | re.IGNORECASE)
    for name in ("TYPE", "SEQUENCE", "FILENAME")
}
_TEXT_RE = re.compile(r"<TEXT>(.*?)</TEXT>", re.DOTALL | re.IGNORECASE)
_XML_RE = re.compile(r"<XML>\s*(.*?)\s*</XML>", re.DOTALL | re.IGNORECASE)
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _filing_dir(form_type: str, cik: int, accession: str) -> Path:
    clean_form = form_type.replace("/", "_")
    return _RAW_DIR / clean_form / str(cik) / accession


def split_submission(text: str) -> list[dict[str, str]]:
    """Split a complete submission text file into its documents.

    Returns one dict per document with its type, sequence, file name and body.
    The body is the inner XML when the document is wrapped in <XML>, else the
    raw <TEXT> content (HTML or plain text).
    """
    docs: list[dict[str, str]] = []
    for block in _DOC_RE.findall(text):
        fields = {}
        for name, rx in _TAG_RE.items():
            m = rx.search(block)
            fields[name] = m.group(1).strip() if m else ""
        text_m = _TEXT_RE.search(block)
        body = text_m.group(1) if text_m else ""
        xml_m = _XML_RE.search(body)
        if xml_m:
            body = xml_m.group(1)
        docs.append(
            {
                "type": fields["TYPE"].upper(),
                "sequence": fields["SEQUENCE"],
                "filename": fields["FILENAME"],
                "body": body.strip(),
            }
        )
    return docs


def _write_documents(out_dir: Path, submission: str) -> list[dict[str, str]]:
    """Write each document of a submission to disk and record them in the manifest."""
    manifest: list[dict[str, str]] = []
    for i, doc in enumerate(split_submission(submission), start=1):
        name = _SAFE_RE.sub("_", doc["filename"]) or f"document_{i}.txt"
        path = out_dir / f"{i:03d}_{name}"
        path.write_text(doc["body"], encoding="utf-8")
        manifest.append({"type": doc["type"], "file": path.name})
    (out_dir / _MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def _documents(raw_dir: Path, *types: str) -> list[Path]:
    """Paths of the split documents whose TYPE is one of `types` (all if none given)."""
    manifest_path = raw_dir / _MANIFEST
    if not manifest_path.exists():
        return []
    wanted = {t.upper() for t in types}
    return [
        raw_dir / d["file"]
        for d in json.loads(manifest_path.read_text(encoding="utf-8"))
        if not wanted or d["type"] in wanted
    ]


async def _fetch_companyfacts(client: EdgarClient, filing: FilingIndex) -> None:
    """Cache the issuer's XBRL companyfacts JSON, refreshing it if this filing is not in it."""
    cache = _RAW_DIR / "companyfacts" / f"{filing.cik}.json"
    if cache.exists() and filing.accession_number in cache.read_text(encoding="utf-8"):
        return
    try:
        content = await client.get_bytes(_COMPANYFACTS_URL.format(cik=filing.cik))
    except Exception:
        return  # facts are optional: sections are still parsed without them
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(content)


def _load_companyfacts(cik: int) -> dict[str, Any] | None:
    cache = _RAW_DIR / "companyfacts" / f"{cik}.json"
    if not cache.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return data


@task(retries=1, retry_delay_seconds=10)
async def fetch_filing(client: EdgarClient, filing: FilingIndex) -> Path | None:
    """Download a filing's complete submission and split it into its documents."""
    out_dir = _filing_dir(filing.form_type, filing.cik, filing.accession_number)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_url = f"{EDGAR_BASE}/Archives/{filing.filename}"

    primary_path = out_dir / "primary.txt"
    if not primary_path.exists():
        try:
            content = await client.get_bytes(base_url)
            primary_path.write_bytes(content)
        except Exception:
            return None

    if not (out_dir / _MANIFEST).exists():
        _write_documents(out_dir, primary_path.read_text(encoding="utf-8", errors="replace"))

    if filing.form_type in _XBRL_FORMS:
        await _fetch_companyfacts(client, filing)

    return out_dir


@task
def parse_and_store_form4(raw_dir: Path, filing: FilingIndex) -> bool:
    """Parse a Form 4 filing and store transactions.

    The ownership document is usually the TYPE 4 (or 4/A) document; any other
    XML document is tried after it. A failure is recorded once per filing, and
    only when no candidate could be parsed and stored.
    """
    candidates = _documents(raw_dir, filing.form_type, "4", "4/A")
    candidates += [p for p in _documents(raw_dir) if p not in candidates]
    candidates += [p for p in sorted(raw_dir.glob("*.xml")) if p not in candidates]
    last_error: Exception | None = None

    for xml_file in candidates:
        if not xml_file.exists():
            continue
        try:
            content = xml_file.read_text(encoding="utf-8", errors="replace")
            if "<ownershipDocument" not in content:
                continue

            result = parse_form4(content, filing.accession_number, filing_date=filing.date_filed)

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
            last_error = e

    if last_error is not None:
        record_parse_failure(filing.accession_number, "4", last_error, _PARSER_VERSION)
    return False


@task
def parse_and_store_form13f(raw_dir: Path, filing: FilingIndex) -> bool:
    """Parse a Form 13F-HR filing and store holdings."""
    try:
        primary_docs = _documents(raw_dir, filing.form_type, "13F-HR", "13F-HR/A")
        info_docs = _documents(raw_dir, "INFORMATION TABLE")
        if not primary_docs:
            return False
        if not info_docs:
            # A 13F-HR always carries an information table; without one there is
            # nothing to store, so do not mark the filing parsed.
            raise ValueError("13F-HR submission has no INFORMATION TABLE document")

        content = primary_docs[0].read_text(encoding="utf-8", errors="replace")
        info_content = info_docs[0].read_text(encoding="utf-8", errors="replace")

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
        main_docs = _documents(raw_dir, filing.form_type)
        html_content = None
        if main_docs:
            html_content = main_docs[0].read_text(encoding="utf-8", errors="replace")

        result = parse_form10k(
            html_content=html_content,
            xbrl_facts_json=_load_companyfacts(filing.cik),
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
