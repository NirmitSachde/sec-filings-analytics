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


def _real_line(form: str, company: str, cik: str, date: str, filename: str) -> str:
    """A form.idx data line: form 17, company 62, CIK 12 and date 12 chars wide."""
    return f"{form:<17}{company:<62}{cik:<12}{date:<12}{filename}"


# Real form.idx lines: columns padded to width, CIK not zero padded.
_REAL_STYLE = [
    _real_line(
        "4", "APPLE INC", "320193", "2024-01-03", "edgar/data/320193/0000320193-24-000001.txt"
    ),
    _real_line(
        "10-K",
        "MICROSOFT CORP",
        "789019",
        "2024-01-04",
        "edgar/data/789019/0000789019-24-000002.txt",
    ),
]


def _index_text(lines: list[str]) -> str:
    header = [
        "Description:           Master Index of EDGAR Dissemination Feed by Form Type",
        "Last Data Received:    March 31, 2024",
        "4 this header line looks like data but sits above the dashes",
        "",
        _real_line("Form Type", "Company Name", "CIK", "Date Filed", "File Name"),
        "-" * 140,
    ]
    return "\n".join(header + lines) + "\n"


async def _parse(lines: list[str]) -> list[dict]:
    client = MagicMock()
    client.get_text = AsyncMock(return_value=_index_text(lines))
    return await index_flow.fetch_and_parse_index.fn(client, "u")


def test_real_line_helper_matches_the_edgar_layout():
    # Copied from a real 2024 QTR1 form.idx; the helper must reproduce it exactly.
    real = (
        "4                Lackey Sarah                                                  1960982"
        "     2024-01-08  edgar/data/1960982/0001806201-24-000006.txt"
    )
    assert real == _real_line(
        "4", "Lackey Sarah", "1960982", "2024-01-08", "edgar/data/1960982/0001806201-24-000006.txt"
    )


async def test_fetch_and_parse_index_parses_both_line_shapes():
    text = _index_text(
        [
            *_REAL_STYLE,
            # Older, narrower layout with a zero-padded CIK still parses.
            f"{'13F-HR':<12} {'BERKSHIRE HATHAWAY INC':<62} 0001067983 2024-02-14 "
            "edgar/data/1067983/0000950123-24-001234.txt",
            # Ignored: unwanted form type and too few columns.
            _real_line(
                "8-K", "SOME CO", "1", "2024-01-05", "edgar/data/1/0000000001-24-000001.txt"
            ),
            "4 short",
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
    assert msft["cik"] == 789019
    assert brk["form_type"] == "13F-HR"
    assert brk["company_name"] == "BERKSHIRE HATHAWAY INC"
    assert brk["cik"] == 1067983
    assert brk["date_filed"] == datetime.date(2024, 2, 14)


async def test_fetch_and_parse_index_skips_line_with_impossible_date():
    # One bad line must not sink the rest of the quarter's index.
    records = await _parse(
        [
            _real_line(
                "4", "BAD DATE CO", "2", "2024-13-99", "edgar/data/2/0000000002-24-000001.txt"
            ),
            *_REAL_STYLE,
        ]
    )
    assert [r["cik"] for r in records] == [320193, 789019]


async def test_fetch_and_parse_index_real_lines_keep_repeated_spaces_in_company():
    records = await _parse(
        [
            _real_line(
                "4",
                "Lackey Sarah",
                "1960982",
                "2024-01-08",
                "edgar/data/1960982/0001806201-24-000006.txt",
            ),
            _real_line(
                "10-Q",
                "ALERUS FINANCIAL  NA",
                "903419",
                "2024-02-29",
                "edgar/data/903419/0000903419-24-000011.txt",
            ),
            # A seven-digit CIK, a /A form and a company name ending in a number.
            _real_line(
                "13F-HR/A",
                "FUND 2 LP",
                "1234567",
                "2024-03-28",
                "edgar/data/1234567/0001234567-24-000003.txt",
            ),
            # A name too long for its column runs into the CIK column.
            "4                "
            + "A" * 70
            + " 1000001    2024-01-09  edgar/data/1000001/0001000001-24-000001.txt",
        ]
    )

    lackey, alerus, fund, long_name = records
    assert lackey == {
        "accession_number": "0001806201-24-000006",
        "form_type": "4",
        "cik": 1960982,
        "company_name": "Lackey Sarah",
        "date_filed": datetime.date(2024, 1, 8),
        "filename": "edgar/data/1960982/0001806201-24-000006.txt",
    }
    assert alerus["company_name"] == "ALERUS FINANCIAL  NA"
    assert alerus["form_type"] == "10-Q"
    assert alerus["cik"] == 903419
    assert alerus["date_filed"] == datetime.date(2024, 2, 29)
    assert (fund["form_type"], fund["company_name"], fund["cik"]) == (
        "13F-HR/A",
        "FUND 2 LP",
        1234567,
    )
    assert fund["accession_number"] == "0001234567-24-000003"
    assert (long_name["company_name"], long_name["cik"]) == ("A" * 70, 1000001)


async def test_fetch_and_parse_index_whitespace_fallback_for_odd_dates():
    # The regex wants YYYY-MM-DD; anything else goes through the whitespace split,
    # which accepts what date.fromisoformat accepts and skips the rest.
    records = await _parse(
        [
            "4 ODD  DATE CO 7 20240105 edgar/data/7/0000000007-24-000001.txt",
            "4 WORSE DATE CO 8 2024-1-5 edgar/data/8/0000000008-24-000001.txt",
        ]
    )
    assert records == [
        {
            "accession_number": "0000000007-24-000001",
            "form_type": "4",
            "cik": 7,
            "company_name": "ODD DATE CO",
            "date_filed": datetime.date(2024, 1, 5),
            "filename": "edgar/data/7/0000000007-24-000001.txt",
        }
    ]


def test_index_line_regex_groups_on_a_real_line():
    m = index_flow._INDEX_LINE_RE.match(
        _real_line(
            "10-K/A",
            "ALERUS FINANCIAL  NA",
            "903419",
            "2024-03-01",
            "edgar/data/903419/0000903419-24-000020.txt",
        )
    )
    assert m is not None
    assert m.groups() == (
        "10-K/A",
        "ALERUS FINANCIAL  NA",
        "903419",
        "2024-03-01",
        "edgar/data/903419/0000903419-24-000020.txt",
    )


async def test_fetch_and_parse_index_strips_index_htm_suffix():
    line = _real_line(
        "4/A", "ACME CORP", "42", "2024-03-01", "edgar/data/42/0000000042-24-000009-index.htm"
    )
    records = await _parse([line])
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
