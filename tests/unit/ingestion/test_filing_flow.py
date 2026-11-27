"""Unit tests for the filing fetch-and-parse flow (no network, no database)."""

import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sec_filings.ingestion import filing_flow
from sec_filings.models import (
    FilingIndex,
    FilingSection,
    HoldingsPosition,
    InsiderTransaction,
)
from sec_filings.parsers.form4 import parse_form4

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "filings"


def _filing(form_type: str = "4", fid: int = 1, acc: str = "0000320193-24-000001") -> FilingIndex:
    return FilingIndex(
        id=fid,
        accession_number=acc,
        form_type=form_type,
        cik=320193,
        company_name="Apple Inc",
        date_filed=datetime.date(2024, 3, 18),
        filename=f"edgar/data/320193/{acc}.txt",
    )


@pytest.fixture
def raw_root(tmp_path, monkeypatch):
    monkeypatch.setattr(filing_flow, "_RAW_DIR", tmp_path / "raw")
    return tmp_path / "raw"


@pytest.fixture
def session(monkeypatch):
    s = MagicMock()
    monkeypatch.setattr(filing_flow, "get_session", lambda: s)
    return s


@pytest.fixture
def failures(monkeypatch):
    recorded: list[tuple] = []

    def fake_record(accession, form_type, exc, version):
        recorded.append((accession, form_type, type(exc).__name__, version))

    monkeypatch.setattr(filing_flow, "record_parse_failure", fake_record)
    return recorded


def _merged(session) -> list:
    return [c.args[0] for c in session.merge.call_args_list]


# ---------------------------------------------------------------- paths + fetch


def test_filing_dir_replaces_slash_in_form_type(raw_root):
    assert filing_flow._filing_dir("13F-HR/A", 42, "ACC") == raw_root / "13F-HR_A" / "42" / "ACC"


async def test_fetch_filing_downloads_primary_document(raw_root):
    client = MagicMock()
    client.get_bytes = AsyncMock(return_value=b"<ownershipDocument/>")
    filing = _filing()

    out = await filing_flow.fetch_filing.fn(client, filing)

    assert out == raw_root / "4" / "320193" / filing.accession_number
    client.get_bytes.assert_awaited_once_with(f"https://www.sec.gov/Archives/{filing.filename}")
    assert (out / "primary.txt").read_bytes() == b"<ownershipDocument/>"


async def test_fetch_filing_skips_download_when_already_on_disk(raw_root):
    filing = _filing()
    out = raw_root / "4" / "320193" / filing.accession_number
    out.mkdir(parents=True)
    (out / "primary.txt").write_text("cached")
    client = MagicMock()
    client.get_bytes = AsyncMock()

    assert await filing_flow.fetch_filing.fn(client, filing) == out
    client.get_bytes.assert_not_awaited()
    assert (out / "primary.txt").read_text() == "cached"


async def test_fetch_filing_returns_none_on_download_error(raw_root):
    client = MagicMock()
    client.get_bytes = AsyncMock(side_effect=RuntimeError("503"))
    filing = _filing()
    assert await filing_flow.fetch_filing.fn(client, filing) is None
    assert not (raw_root / "4" / "320193" / filing.accession_number / "primary.txt").exists()


# ---------------------------------------------------------------- form 4


def test_parse_form4_merges_every_transaction(tmp_path, session, failures):
    xml = (FIXTURES / "form4_sample.xml").read_text()
    (tmp_path / "primary.txt").write_text(xml)
    filing = _filing()

    assert filing_flow.parse_and_store_form4.fn(tmp_path, filing) is True

    expected = parse_form4(xml, filing.accession_number).transactions
    merged = _merged(session)
    assert len(merged) == len(expected) > 0
    assert all(isinstance(m, InsiderTransaction) for m in merged)
    assert merged[0].issuer_ticker == expected[0].issuer_ticker == "AAPL"
    assert merged[0].owner_name == expected[0].owner_name
    assert merged[0].shares == expected[0].shares
    assert [m.transaction_index for m in merged] == [t.transaction_index for t in expected]
    session.commit.assert_called_once()
    session.close.assert_called_once()
    assert failures == []


def test_parse_form4_prefers_xml_file_over_primary(tmp_path, session, failures):
    (tmp_path / "doc.xml").write_text((FIXTURES / "form4_sample.xml").read_text())
    (tmp_path / "primary.txt").write_text("<ownershipDocument><broken")

    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is True
    # The XML file is tried first and succeeds, so the broken primary is never parsed.
    assert failures == []
    session.commit.assert_called_once()


def test_parse_form4_without_ownership_document(tmp_path, session, failures):
    (tmp_path / "primary.txt").write_text("<html>not a form 4</html>")
    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is False
    session.merge.assert_not_called()
    assert failures == []


def test_parse_form4_with_no_files(tmp_path, session, failures):
    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is False
    assert failures == []


def test_parse_form4_parse_error_goes_to_dead_letter(tmp_path, session, failures, monkeypatch):
    (tmp_path / "primary.txt").write_text("<ownershipDocument>")

    def boom(content, accession):
        raise ValueError("malformed")

    monkeypatch.setattr(filing_flow, "parse_form4", boom)
    filing = _filing()

    assert filing_flow.parse_and_store_form4.fn(tmp_path, filing) is False
    assert failures == [(filing.accession_number, "4", "ValueError", filing_flow._PARSER_VERSION)]


def test_parse_form4_db_error_rolls_back_and_records(tmp_path, session, failures):
    (tmp_path / "primary.txt").write_text((FIXTURES / "form4_sample.xml").read_text())
    session.commit.side_effect = RuntimeError("db down")

    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is False
    session.rollback.assert_called_once()
    session.close.assert_called_once()
    assert failures[0][1:3] == ("4", "RuntimeError")


# ---------------------------------------------------------------- form 13F


def test_parse_form13f_uses_info_table_file(tmp_path, session, failures):
    (tmp_path / "primary.txt").write_text((FIXTURES / "form13f_primary.xml").read_text())
    (tmp_path / "abc_infotable.xml").write_text((FIXTURES / "form13f_infotable.xml").read_text())
    filing = _filing("13F-HR", acc="0001067983-24-000042")

    assert filing_flow.parse_and_store_form13f.fn(tmp_path, filing) is True

    merged = _merged(session)
    assert len(merged) == 2
    assert all(isinstance(m, HoldingsPosition) for m in merged)
    apple = next(m for m in merged if m.name_of_issuer == "APPLE INC")
    assert apple.cusip == "037833100"
    assert apple.shares == 503000000
    assert apple.filer_cik == 1067983
    assert apple.accession_number == "0001067983-24-000042"
    assert apple.period_of_report == datetime.date(2024, 3, 31)
    session.commit.assert_called_once()
    assert failures == []


def test_parse_form13f_missing_primary(tmp_path, session, failures):
    assert filing_flow.parse_and_store_form13f.fn(tmp_path, _filing("13F-HR")) is False
    session.merge.assert_not_called()
    assert failures == []


def test_parse_form13f_without_info_table_reports_success_with_no_holdings(
    tmp_path, session, failures
):
    # fetch_filing only saves primary.txt, so this is the normal case in the flow:
    # the primary doc is reused as the info table, yields zero holdings, and still
    # counts as parsed. Pinned here so a change in that behaviour is noticed.
    (tmp_path / "primary.txt").write_text((FIXTURES / "form13f_primary.xml").read_text())

    assert filing_flow.parse_and_store_form13f.fn(tmp_path, _filing("13F-HR")) is True
    session.merge.assert_not_called()
    session.commit.assert_called_once()
    assert failures == []


def test_parse_form13f_db_error_rolls_back(tmp_path, session, failures):
    (tmp_path / "primary.txt").write_text((FIXTURES / "form13f_primary.xml").read_text())
    (tmp_path / "INFOTABLE.xml").write_text((FIXTURES / "form13f_infotable.xml").read_text())
    session.commit.side_effect = RuntimeError("db down")

    assert filing_flow.parse_and_store_form13f.fn(tmp_path, _filing("13F-HR")) is False
    session.rollback.assert_called_once()
    session.close.assert_called_once()
    assert failures[0][1:3] == ("13F-HR", "RuntimeError")


# ---------------------------------------------------------------- form 10-K


_TEN_K_HTML = """
<html><body>
<h2>Item 1. Business</h2>
<p>We design, manufacture and market smartphones, personal computers and tablets
around the world, along with a range of related services and accessories.</p>
<h2>Item 1A. Risk Factors</h2>
<p>Our business is subject to many risks, including global economic conditions,
supply chain disruption, competition and changes in laws and regulations.</p>
<h2>Item 7. Management's Discussion and Analysis</h2>
<p>Net sales increased during the year due to higher sales of services and wearables.</p>
</body></html>
"""


def test_parse_form10k_merges_sections(tmp_path, session, failures):
    (tmp_path / "primary.txt").write_text(_TEN_K_HTML)
    filing = _filing("10-K")

    assert filing_flow.parse_and_store_form10k.fn(tmp_path, filing) is True

    merged = _merged(session)
    assert merged, "expected at least one section"
    assert all(isinstance(m, FilingSection) for m in merged)
    assert all(m.accession_number == filing.accession_number for m in merged)
    assert all(m.cik == 320193 for m in merged)
    assert all(m.char_count == len(m.text) for m in merged)
    session.commit.assert_called_once()
    assert failures == []


def test_parse_form10k_stores_xbrl_facts(tmp_path, session, failures, monkeypatch):
    from sec_filings.models import XbrlFact
    from sec_filings.parsers.contracts import Form10KFiling, XbrlFactRecord

    fact = XbrlFactRecord(
        accession_number="A",
        cik=1,
        concept="Revenues",
        value="10.0",
        unit="USD",
        decimals="-6",
        period_start=datetime.date(2023, 1, 1),
        period_end=datetime.date(2023, 12, 31),
        context_id="FY23",
        is_instant=False,
    )
    monkeypatch.setattr(
        filing_flow,
        "parse_form10k",
        lambda **kw: Form10KFiling(accession_number="A", cik=1, sections=[], xbrl_facts=[fact]),
    )

    assert filing_flow.parse_and_store_form10k.fn(tmp_path, _filing("10-K")) is True
    merged = _merged(session)
    assert len(merged) == 1 and isinstance(merged[0], XbrlFact)
    assert merged[0].concept == "Revenues"
    assert merged[0].value == "10.0"


def test_parse_form10k_without_primary_passes_none(tmp_path, session, failures, monkeypatch):
    seen = {}
    real = filing_flow.parse_form10k

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(filing_flow, "parse_form10k", spy)
    assert filing_flow.parse_and_store_form10k.fn(tmp_path, _filing("10-K")) is True
    assert seen["html_content"] is None
    assert seen["xbrl_facts_json"] is None
    session.merge.assert_not_called()


def test_parse_form10k_error_goes_to_dead_letter(tmp_path, session, failures, monkeypatch):
    def boom(**kwargs):
        raise KeyError("x")

    monkeypatch.setattr(filing_flow, "parse_form10k", boom)
    assert filing_flow.parse_and_store_form10k.fn(tmp_path, _filing("10-K")) is False
    assert failures[0][1:3] == ("10-K", "KeyError")


def test_parse_form10k_db_error_rolls_back(tmp_path, session, failures):
    (tmp_path / "primary.txt").write_text(_TEN_K_HTML)
    session.commit.side_effect = RuntimeError("db down")
    assert filing_flow.parse_and_store_form10k.fn(tmp_path, _filing("10-K")) is False
    session.rollback.assert_called_once()
    session.close.assert_called_once()
    assert failures[0][1:3] == ("10-K", "RuntimeError")


# ---------------------------------------------------------------- mark parsed


def test_mark_filing_parsed_updates_parsed_at(session):
    filing_flow.mark_filing_parsed.fn(7)
    update = session.query.return_value.filter.return_value.update
    update.assert_called_once()
    assert list(update.call_args.args[0]) == ["parsed_at"]
    session.commit.assert_called_once()
    session.close.assert_called_once()


def test_mark_filing_parsed_rolls_back_and_reraises(session):
    session.commit.side_effect = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        filing_flow.mark_filing_parsed.fn(7)
    session.rollback.assert_called_once()
    session.close.assert_called_once()


def test_form_parser_registry():
    reg = filing_flow._FORM_PARSERS
    assert reg["4"] is reg["4/A"] is filing_flow.parse_and_store_form4
    assert reg["13F-HR"] is reg["13F-HR/A"] is filing_flow.parse_and_store_form13f
    for form in ("10-K", "10-K/A", "10-Q", "10-Q/A"):
        assert reg[form] is filing_flow.parse_and_store_form10k
    assert "8-K" not in reg


# ---------------------------------------------------------------- flow


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _flow_setup(monkeypatch, filings, fetch_results, parser_results):
    """Wire the flow to fakes. Returns (sessions created, marked ids, parser calls)."""
    sessions: list[MagicMock] = []

    def make_session():
        s = MagicMock()
        q = s.query.return_value
        q.filter.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        q.all.return_value = filings
        sessions.append(s)
        return s

    async def fake_fetch(client, filing):
        return fetch_results[filing.accession_number]

    marked: list[int] = []
    parser_calls: list[str] = []

    def parser(raw_dir, filing):
        parser_calls.append(filing.accession_number)
        return parser_results[filing.accession_number]

    monkeypatch.setattr(filing_flow, "get_session", make_session)
    monkeypatch.setattr(filing_flow, "EdgarClient", _FakeClient)
    monkeypatch.setattr(filing_flow, "fetch_filing", fake_fetch)
    monkeypatch.setattr(filing_flow, "mark_filing_parsed", marked.append)
    monkeypatch.setattr(filing_flow, "_FORM_PARSERS", dict.fromkeys(["4", "10-K"], parser))
    return sessions, marked, parser_calls


async def test_flow_counts_fetched_parsed_and_failed(monkeypatch, tmp_path):
    filings = [
        _filing("4", 1, "OK-4"),
        _filing("4", 2, "FETCH-FAIL"),
        _filing("8-K", 3, "NO-PARSER"),
        _filing("10-K", 4, "PARSE-FAIL"),
    ]
    sessions, marked, parser_calls = _flow_setup(
        monkeypatch,
        filings,
        fetch_results={
            "OK-4": tmp_path,
            "FETCH-FAIL": None,
            "NO-PARSER": tmp_path,
            "PARSE-FAIL": tmp_path,
        },
        parser_results={"OK-4": True, "PARSE-FAIL": False},
    )

    stats = await filing_flow.fetch_and_parse_filings.fn(batch_size=10)

    assert stats == {"fetched": 3, "parsed": 1, "failed": 3}
    assert marked == [1]
    assert parser_calls == ["OK-4", "PARSE-FAIL"]
    # Query session + one fetched_at update per successfully fetched filing.
    assert len(sessions) == 4
    sessions[0].query.return_value.limit.assert_called_once_with(10)
    for s in sessions[1:]:
        update = s.query.return_value.filter.return_value.update
        assert list(update.call_args.args[0]) == ["fetched_at"]
        s.commit.assert_called_once()
        s.close.assert_called_once()


async def test_flow_filters_by_form_types(monkeypatch):
    sessions, _, _ = _flow_setup(monkeypatch, [], {}, {})
    stats = await filing_flow.fetch_and_parse_filings.fn(batch_size=5, form_types=["4"])
    assert stats == {"fetched": 0, "parsed": 0, "failed": 0}
    q = sessions[0].query.return_value
    # parsed_at IS NULL filter, then the form_type IN filter.
    assert q.filter.call_count == 2
    sessions[0].close.assert_called_once()


async def test_flow_without_form_types_filters_once(monkeypatch):
    sessions, _, _ = _flow_setup(monkeypatch, [], {}, {})
    await filing_flow.fetch_and_parse_filings.fn()
    q = sessions[0].query.return_value
    assert q.filter.call_count == 1
    q.limit.assert_called_once_with(100)
