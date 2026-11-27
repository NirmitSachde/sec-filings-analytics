"""Unit tests for the EDGAR full-index crawler (no network, no database)."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from sec_filings.ingestion import index_flow
from sec_filings.ingestion.index_flow import _index_urls, _quarter_for_month
from sec_filings.models import FilingIndex

BASE = "https://www.sec.gov/Archives/edgar/full-index"


def test_quarter_for_month():
    assert [_quarter_for_month(m) for m in range(1, 13)] == [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]


def test_index_urls_one_per_quarter_across_year_boundary():
    urls = _index_urls(datetime.date(2023, 11, 15), datetime.date(2024, 4, 2))
    assert urls == [
        f"{BASE}/2023/QTR4/form.idx",
        f"{BASE}/2024/QTR1/form.idx",
        f"{BASE}/2024/QTR2/form.idx",
    ]


def test_index_urls_single_day():
    assert _index_urls(datetime.date(2024, 8, 9), datetime.date(2024, 8, 9)) == [
        f"{BASE}/2024/QTR3/form.idx"
    ]


def test_index_urls_empty_when_start_after_end():
    assert _index_urls(datetime.date(2025, 1, 1), datetime.date(2024, 1, 1)) == []


def _fixed_width_line(form: str, name: str, cik: str, date: str, filename: str) -> str:
    """A line shaped exactly the way _INDEX_LINE_RE expects (12 + 62 char columns)."""
    return f"{form:<12} {name:<62} {cik} {date} {filename}"


# A real form.idx pads columns without a separating space and does not zero pad the
# CIK, so these lines go through the whitespace-split fallback.
_REAL_STYLE = [
    "4           APPLE INC                                                     320193"
    "      2024-01-03  edgar/data/320193/0000320193-24-000001.txt",
    "10-K        MICROSOFT CORP                                                789019"
    "      2024-01-04  edgar/data/789019/0000789019-24-000002.txt",
]


def _index_text(lines: list[str]) -> str:
    header = [
        "Description:           Master Index of EDGAR Dissemination Feed by Form Type",
        "Last Data Received:    March 31, 2024",
        "4 this header line looks like data but sits above the dashes",
        "",
        "Form Type   Company Name                                                  CIK"
        "         Date Filed  File Name",
        "-" * 140,
    ]
    return "\n".join(header + lines) + "\n"


async def test_fetch_and_parse_index_parses_both_line_shapes():
    text = _index_text(
        [
            *_REAL_STYLE,
            _fixed_width_line(
                "13F-HR",
                "BERKSHIRE HATHAWAY INC",
                "0001067983",
                "2024-02-14",
                "edgar/data/1067983/0000950123-24-001234.txt",
            ),
            # Ignored: unwanted form type, too few columns, and an unparseable date.
            "8-K         SOME CO                                                       1"
            "           2024-01-05  edgar/data/1/0000000001-24-000001.txt",
            "4 short",
            "4           BAD DATE CO                                                   2"
            "           2024-13-99  edgar/data/2/0000000002-24-000001.txt",
        ]
    )
    client = MagicMock()
    client.get_text = AsyncMock(return_value=text)

    records = await index_flow.fetch_and_parse_index.fn(client, f"{BASE}/2024/QTR1/form.idx")

    client.get_text.assert_awaited_once_with(f"{BASE}/2024/QTR1/form.idx")
    assert [r["accession_number"] for r in records] == [
        "0000320193-24-000001",
        "0000789019-24-000002",
        "0000950123-24-001234",
    ]
    apple, msft, brk = records
    assert apple == {
        "accession_number": "0000320193-24-000001",
        "form_type": "4",
        "cik": 320193,
        "company_name": "APPLE INC",
        "date_filed": datetime.date(2024, 1, 3),
        "filename": "edgar/data/320193/0000320193-24-000001.txt",
    }
    assert msft["form_type"] == "10-K"
    assert msft["company_name"] == "MICROSOFT CORP"
    # Regex path: stripped fixed-width columns.
    assert brk["form_type"] == "13F-HR"
    assert brk["company_name"] == "BERKSHIRE HATHAWAY INC"
    assert brk["cik"] == 1067983
    assert brk["date_filed"] == datetime.date(2024, 2, 14)


async def test_fetch_and_parse_index_strips_index_htm_suffix():
    line = (
        "4/A         ACME CORP                                                     42"
        "          2024-03-01  edgar/data/42/0000000042-24-000009-index.htm"
    )
    client = MagicMock()
    client.get_text = AsyncMock(return_value=_index_text([line]))
    records = await index_flow.fetch_and_parse_index.fn(client, "u")
    assert records[0]["accession_number"] == "0000000042-24-000009"
    assert records[0]["form_type"] == "4/A"


async def test_fetch_and_parse_index_without_data_section_returns_nothing():
    client = MagicMock()
    client.get_text = AsyncMock(return_value="\n".join(_REAL_STYLE))  # no dashes line
    assert await index_flow.fetch_and_parse_index.fn(client, "u") == []


# ---------------------------------------------------------------- upsert


def _record(acc: str) -> dict:
    return {
        "accession_number": acc,
        "form_type": "4",
        "cik": 1,
        "company_name": "X",
        "date_filed": datetime.date(2024, 1, 1),
        "filename": f"edgar/data/1/{acc}.txt",
    }


def test_upsert_filings_empty_does_not_open_session(monkeypatch):
    get_session = MagicMock()
    monkeypatch.setattr(index_flow, "get_session", get_session)
    assert index_flow.upsert_filings.fn([]) == 0
    get_session.assert_not_called()


def test_upsert_filings_skips_existing_accessions(monkeypatch):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [("A-1",)]
    monkeypatch.setattr(index_flow, "get_session", lambda: session)

    inserted = index_flow.upsert_filings.fn([_record("A-1"), _record("A-2"), _record("A-3")])

    assert inserted == 2
    added = [c.args[0] for c in session.add.call_args_list]
    assert all(isinstance(a, FilingIndex) for a in added)
    assert [a.accession_number for a in added] == ["A-2", "A-3"]
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.close.assert_called_once()


def test_upsert_filings_rolls_back_and_reraises(monkeypatch):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    session.commit.side_effect = RuntimeError("db down")
    monkeypatch.setattr(index_flow, "get_session", lambda: session)

    with pytest.raises(RuntimeError, match="db down"):
        index_flow.upsert_filings.fn([_record("A-1")])
    session.rollback.assert_called_once()
    session.close.assert_called_once()


# ---------------------------------------------------------------- flow


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _patch_flow(monkeypatch, per_url_records):
    fetched: list[str] = []

    async def fake_fetch(client, url):
        fetched.append(url)
        return per_url_records.get(url, [])

    monkeypatch.setattr(index_flow, "EdgarClient", _FakeClient)
    monkeypatch.setattr(index_flow, "fetch_and_parse_index", fake_fetch)
    monkeypatch.setattr(index_flow, "upsert_filings", lambda records: len(records))
    return fetched


async def test_crawl_edgar_index_sums_inserted_over_quarters(monkeypatch):
    q1 = f"{BASE}/2024/QTR1/form.idx"
    q2 = f"{BASE}/2024/QTR2/form.idx"
    fetched = _patch_flow(monkeypatch, {q1: [_record("A"), _record("B")], q2: [_record("C")]})

    total = await index_flow.crawl_edgar_index.fn(
        start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 6, 30)
    )

    assert total == 3
    assert fetched == [q1, q2]


async def test_crawl_edgar_index_defaults_to_five_years(monkeypatch):
    fetched = _patch_flow(monkeypatch, {})
    today = datetime.date.today()

    total = await index_flow.crawl_edgar_index.fn()

    assert total == 0
    assert fetched == _index_urls(today.replace(year=today.year - 5), today)
    assert f"/{today.year - 5}/" in fetched[0]
    assert f"/{today.year}/" in fetched[-1]


async def test_crawl_edgar_index_default_start_uses_given_end(monkeypatch):
    fetched = _patch_flow(monkeypatch, {})
    await index_flow.crawl_edgar_index.fn(end_date=datetime.date(2020, 2, 10))
    assert fetched[0] == f"{BASE}/2015/QTR1/form.idx"
    assert fetched[-1] == f"{BASE}/2020/QTR1/form.idx"
    assert len(fetched) == 21
