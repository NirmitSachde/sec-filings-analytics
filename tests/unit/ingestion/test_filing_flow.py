"""Unit tests for the filing fetch-and-parse flow (no network, no database)."""

import datetime
import json
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


@pytest.fixture(autouse=True)
def raw_root(tmp_path, monkeypatch):
    # Autouse so no test can read or write the real data/raw (companyfacts cache).
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


def _fixture(name: str) -> str:
    text = (FIXTURES / name).read_text()
    # Inside a submission's <XML> block the XML declaration sits on the first line.
    return text.strip()


def _doc(doc_type: str, filename: str, body: str, seq: int = 1, xml: bool = True) -> str:
    inner = f"<XML>\n{body}\n</XML>" if xml else body
    return (
        f"<DOCUMENT>\n<TYPE>{doc_type}\n<SEQUENCE>{seq}\n<FILENAME>{filename}\n"
        f"<DESCRIPTION>{doc_type} document\n<TEXT>\n{inner}\n</TEXT>\n</DOCUMENT>\n"
    )


def _submission(*docs: str, acc: str = "0000950170-24-000001") -> str:
    """A complete submission text file, shaped like the ones EDGAR serves."""
    header = (
        f"<SEC-HEADER>{acc}.hdr.sgml : 20240315\n"
        f"<ACCEPTANCE-DATETIME>20240315163015\nACCESSION NUMBER:\t\t{acc}\n"
        "CONFORMED SUBMISSION TYPE:\t4\nPUBLIC DOCUMENT COUNT:\t\t2\n"
        "FILED AS OF DATE:\t\t20240315\n</SEC-HEADER>\n"
    )
    return f"<SEC-DOCUMENT>{acc}.txt : 20240315\n{header}{''.join(docs)}</SEC-DOCUMENT>\n"


def _split(raw_dir: Path, *docs: str) -> list[dict[str, str]]:
    """Lay out a raw filing dir the way fetch_filing does: primary.txt plus split docs."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    text = _submission(*docs)
    (raw_dir / "primary.txt").write_text(text)
    return filing_flow._write_documents(raw_dir, text)


_EXHIBIT_HTML = (
    "<html><body><p>Exhibit 99.1: explanation of responses. The reporting person "
    "disclaims beneficial ownership.</p></body></html>"
)


def _form4_doc(seq: int = 1, doc_type: str = "4") -> str:
    return _doc(doc_type, "wk-form4_1710534615.xml", _fixture("form4_sample.xml"), seq=seq)


def _13f_docs(primary_type: str = "13F-HR") -> list[str]:
    return [
        _doc(primary_type, "primary_doc.xml", _fixture("form13f_primary.xml"), seq=1),
        _doc("INFORMATION TABLE", "infotable.xml", _fixture("form13f_infotable.xml"), seq=2),
    ]


# ---------------------------------------------------------------- split_submission


def test_split_submission_realistic_form4_with_exhibit():
    ownership = _fixture("form4_sample.xml")
    text = _submission(
        _form4_doc(),
        _doc("EX-99.1", "ex99-1.htm", _EXHIBIT_HTML, seq=2, xml=False),
    )

    docs = filing_flow.split_submission(text)

    assert [(d["type"], d["sequence"], d["filename"]) for d in docs] == [
        ("4", "1", "wk-form4_1710534615.xml"),
        ("EX-99.1", "2", "ex99-1.htm"),
    ]
    # The ownership document is unwrapped from <XML>, starting at its declaration.
    assert docs[0]["body"] == ownership
    assert docs[0]["body"].startswith("<?xml")
    assert "<XML>" not in docs[0]["body"] and "</TEXT>" not in docs[0]["body"]
    # The exhibit has no <XML> wrapper, so the raw <TEXT> content is kept.
    assert docs[1]["body"] == _EXHIBIT_HTML
    # Nothing from the SGML header leaks into a document.
    assert all("ACCESSION NUMBER" not in d["body"] for d in docs)


def test_split_submission_13f_types_and_bodies():
    docs = filing_flow.split_submission(_submission(*_13f_docs()))
    assert [d["type"] for d in docs] == ["13F-HR", "INFORMATION TABLE"]
    assert docs[0]["body"] == _fixture("form13f_primary.xml")
    assert docs[1]["body"] == _fixture("form13f_infotable.xml")


def test_split_submission_tolerates_odd_documents():
    text = (
        "<SEC-DOCUMENT>\n"
        # Lower-case type is normalised; CRLF line ends do not leak into fields.
        "<document>\r\n<type>information table\r\n<sequence>3\r\n"
        "<filename>t.xml\r\n<text>\r\n<xml>\r\n<a/>\r\n</xml>\r\n</text>\r\n</document>\n"
        # No FILENAME, no SEQUENCE and no TEXT block at all.
        "<DOCUMENT>\n<TYPE>GRAPHIC\n</DOCUMENT>\n"
        "</SEC-DOCUMENT>"
    )
    first, second = filing_flow.split_submission(text)
    assert first == {
        "type": "INFORMATION TABLE",
        "sequence": "3",
        "filename": "t.xml",
        "body": "<a/>",
    }
    assert second == {"type": "GRAPHIC", "sequence": "", "filename": "", "body": ""}


def test_split_submission_without_documents():
    assert filing_flow.split_submission("<ownershipDocument/>") == []
    assert filing_flow.split_submission("") == []


def test_write_documents_writes_bodies_and_manifest(tmp_path):
    text = _submission(
        _form4_doc(),
        _doc("EX-99.1", "ex 99/1 (final).htm", _EXHIBIT_HTML, seq=2, xml=False),
        "<DOCUMENT>\n<TYPE>EX-24\n<TEXT>\npower of attorney\n</TEXT>\n</DOCUMENT>\n",
    )

    manifest = filing_flow._write_documents(tmp_path, text)

    assert manifest == [
        {"type": "4", "file": "001_wk-form4_1710534615.xml"},
        # Unsafe characters are replaced, so the name stays inside the filing dir.
        {"type": "EX-99.1", "file": "002_ex_99_1_final_.htm"},
        # A document without a file name gets a numbered one.
        {"type": "EX-24", "file": "003_document_3.txt"},
    ]
    assert json.loads((tmp_path / "documents.json").read_text()) == manifest
    assert (tmp_path / "001_wk-form4_1710534615.xml").read_text() == _fixture("form4_sample.xml")
    assert (tmp_path / "002_ex_99_1_final_.htm").read_text() == _EXHIBIT_HTML
    assert (tmp_path / "003_document_3.txt").read_text() == "power of attorney"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        ["documents.json", *(m["file"] for m in manifest)]
    )


def test_documents_selects_by_type_in_manifest_order(tmp_path):
    _split(
        tmp_path,
        _doc("13F-HR", "primary_doc.xml", "<a/>", seq=1),
        _doc("INFORMATION TABLE", "infotable.xml", "<b/>", seq=2),
        _doc("INFORMATION TABLE", "infotable2.xml", "<c/>", seq=3),
    )
    assert filing_flow._documents(tmp_path, "information table") == [
        tmp_path / "002_infotable.xml",
        tmp_path / "003_infotable2.xml",
    ]
    assert filing_flow._documents(tmp_path, "13F-HR", "13F-HR/A") == [
        tmp_path / "001_primary_doc.xml"
    ]
    assert filing_flow._documents(tmp_path, "10-K") == []
    # No types: every document.
    assert len(filing_flow._documents(tmp_path)) == 3


def test_documents_without_manifest_is_empty(tmp_path):
    (tmp_path / "primary.txt").write_text("anything")
    assert filing_flow._documents(tmp_path) == []
    assert filing_flow._documents(tmp_path, "4") == []


# ---------------------------------------------------------------- paths + fetch


def test_filing_dir_replaces_slash_in_form_type(raw_root):
    assert filing_flow._filing_dir("13F-HR/A", 42, "ACC") == raw_root / "13F-HR_A" / "42" / "ACC"


def _client(responses: dict[str, object]) -> MagicMock:
    """EdgarClient stand-in answering get_bytes by URL (str is encoded, an Exception raised)."""

    async def get_bytes(url):
        value = responses[url]
        if isinstance(value, Exception):
            raise value
        return value.encode() if isinstance(value, str) else value

    client = MagicMock()
    client.get_bytes = AsyncMock(side_effect=get_bytes)
    return client


def _archive_url(filing: FilingIndex) -> str:
    return f"https://www.sec.gov/Archives/{filing.filename}"


_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


async def test_fetch_filing_saves_submission_and_splits_documents(raw_root):
    filing = _filing()
    submission = _submission(
        _form4_doc(), _doc("EX-99.1", "ex99-1.htm", _EXHIBIT_HTML, seq=2, xml=False)
    ).encode()
    client = _client({_archive_url(filing): submission})

    out = await filing_flow.fetch_filing.fn(client, filing)

    assert out == raw_root / "4" / "320193" / filing.accession_number
    client.get_bytes.assert_awaited_once_with(_archive_url(filing))
    # The complete submission is kept as-is next to the split documents.
    assert (out / "primary.txt").read_bytes() == submission
    assert json.loads((out / "documents.json").read_text()) == [
        {"type": "4", "file": "001_wk-form4_1710534615.xml"},
        {"type": "EX-99.1", "file": "002_ex99-1.htm"},
    ]
    assert (out / "001_wk-form4_1710534615.xml").read_text() == _fixture("form4_sample.xml")
    # A Form 4 has no XBRL, so companyfacts is never requested.
    assert not (raw_root / "companyfacts").exists()


async def test_fetch_filing_splits_cached_submission_without_download(raw_root):
    filing = _filing()
    out = raw_root / "4" / "320193" / filing.accession_number
    out.mkdir(parents=True)
    (out / "primary.txt").write_text(_submission(_form4_doc()))
    client = _client({})

    assert await filing_flow.fetch_filing.fn(client, filing) == out
    client.get_bytes.assert_not_awaited()
    assert filing_flow._documents(out, "4") == [out / "001_wk-form4_1710534615.xml"]


async def test_fetch_filing_does_not_resplit_when_manifest_exists(raw_root):
    filing = _filing()
    out = raw_root / "4" / "320193" / filing.accession_number
    out.mkdir(parents=True)
    (out / "primary.txt").write_text(_submission(_form4_doc()))
    (out / "documents.json").write_text('[{"type": "4", "file": "kept.xml"}]')
    client = _client({})

    assert await filing_flow.fetch_filing.fn(client, filing) == out
    client.get_bytes.assert_not_awaited()
    assert (out / "documents.json").read_text() == '[{"type": "4", "file": "kept.xml"}]'
    assert sorted(p.name for p in out.iterdir()) == ["documents.json", "primary.txt"]


async def test_fetch_filing_returns_none_on_download_error(raw_root):
    filing = _filing()
    client = _client({_archive_url(filing): RuntimeError("503")})
    assert await filing_flow.fetch_filing.fn(client, filing) is None
    out = raw_root / "4" / "320193" / filing.accession_number
    assert not (out / "primary.txt").exists()
    assert not (out / "documents.json").exists()


def _companyfacts(*accessions: str) -> bytes:
    entries = [{"val": i + 1, "accn": a, "end": "2023-09-30"} for i, a in enumerate(accessions)]
    return json.dumps(
        {"cik": 320193, "facts": {"dei": {"X": {"units": {"USD": entries}}}}}
    ).encode()


@pytest.mark.parametrize("form_type", ["10-K", "10-K/A", "10-Q", "10-Q/A"])
async def test_fetch_filing_caches_companyfacts_for_xbrl_forms(raw_root, form_type):
    filing = _filing(form_type)
    facts = _companyfacts(filing.accession_number)
    client = _client(
        {
            _archive_url(filing): _submission(_doc(form_type, "a.htm", "<html/>", xml=False)),
            _FACTS_URL: facts,
        }
    )

    assert await filing_flow.fetch_filing.fn(client, filing) is not None

    assert (raw_root / "companyfacts" / "320193.json").read_bytes() == facts
    assert [c.args[0] for c in client.get_bytes.await_args_list] == [
        _archive_url(filing),
        _FACTS_URL,
    ]


async def test_fetch_filing_reuses_companyfacts_that_contain_the_filing(raw_root):
    filing = _filing("10-K")
    cache = raw_root / "companyfacts" / "320193.json"
    cache.parent.mkdir(parents=True)
    cached = _companyfacts("0000320193-23-000106", filing.accession_number)
    cache.write_bytes(cached)
    client = _client({_archive_url(filing): _submission()})

    await filing_flow.fetch_filing.fn(client, filing)

    client.get_bytes.assert_awaited_once_with(_archive_url(filing))
    assert cache.read_bytes() == cached


async def test_fetch_filing_refreshes_companyfacts_missing_the_filing(raw_root):
    filing = _filing("10-K")
    cache = raw_root / "companyfacts" / "320193.json"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(_companyfacts("0000320193-23-000106"))
    fresh = _companyfacts("0000320193-23-000106", filing.accession_number)
    client = _client({_archive_url(filing): _submission(), _FACTS_URL: fresh})

    await filing_flow.fetch_filing.fn(client, filing)

    assert client.get_bytes.await_count == 2
    assert cache.read_bytes() == fresh


async def test_fetch_filing_tolerates_companyfacts_error(raw_root):
    filing = _filing("10-K")
    client = _client({_archive_url(filing): _submission(), _FACTS_URL: RuntimeError("404")})

    out = await filing_flow.fetch_filing.fn(client, filing)

    assert out == raw_root / "10-K" / "320193" / filing.accession_number
    assert (out / "documents.json").exists()
    assert not (raw_root / "companyfacts" / "320193.json").exists()


async def test_fetch_filing_keeps_stale_companyfacts_when_refresh_fails(raw_root):
    filing = _filing("10-Q")
    cache = raw_root / "companyfacts" / "320193.json"
    cache.parent.mkdir(parents=True)
    stale = _companyfacts("0000320193-23-000106")
    cache.write_bytes(stale)
    client = _client({_archive_url(filing): _submission(), _FACTS_URL: RuntimeError("503")})

    assert await filing_flow.fetch_filing.fn(client, filing) is not None
    assert cache.read_bytes() == stale


def test_load_companyfacts(raw_root):
    assert filing_flow._load_companyfacts(320193) is None
    cache = raw_root / "companyfacts" / "320193.json"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(_companyfacts("acc"))
    assert filing_flow._load_companyfacts(320193)["cik"] == 320193
    cache.write_text("{not json")
    assert filing_flow._load_companyfacts(320193) is None


# ---------------------------------------------------------------- form 4


def test_parse_form4_merges_every_transaction(tmp_path, session, failures):
    _split(tmp_path, _form4_doc())
    filing = _filing()

    assert filing_flow.parse_and_store_form4.fn(tmp_path, filing) is True

    xml = _fixture("form4_sample.xml")
    expected = parse_form4(xml, filing.accession_number, filing_date=filing.date_filed)
    merged = _merged(session)
    assert len(merged) == len(expected.transactions) > 0
    assert all(isinstance(m, InsiderTransaction) for m in merged)
    assert merged[0].issuer_ticker == expected.transactions[0].issuer_ticker == "AAPL"
    assert merged[0].owner_name == expected.transactions[0].owner_name
    assert merged[0].shares == expected.transactions[0].shares
    assert [m.transaction_index for m in merged] == [
        t.transaction_index for t in expected.transactions
    ]
    # The index's filing date is stored, not the XML's periodOfReport (2024-03-15).
    assert {m.filing_date for m in merged} == {datetime.date(2024, 3, 18)}
    session.commit.assert_called_once()
    session.close.assert_called_once()
    assert failures == []


def test_parse_form4_passes_filing_date_from_index(tmp_path, session, failures, monkeypatch):
    _split(tmp_path, _form4_doc(doc_type="4/A"))
    seen = []
    real = filing_flow.parse_form4

    def spy(content, accession, filing_date=None):
        seen.append((accession, filing_date))
        return real(content, accession, filing_date=filing_date)

    monkeypatch.setattr(filing_flow, "parse_form4", spy)
    filing = _filing("4/A")
    filing.date_filed = datetime.date(2024, 3, 20)

    assert filing_flow.parse_and_store_form4.fn(tmp_path, filing) is True
    assert seen == [(filing.accession_number, datetime.date(2024, 3, 20))]
    assert {m.filing_date for m in _merged(session)} == {datetime.date(2024, 3, 20)}


def test_parse_form4_tries_type_4_document_first(tmp_path, session, failures, monkeypatch):
    # A broken ownership XML in an exhibit comes first in the submission, but the
    # TYPE 4 document is tried first and succeeds, so the exhibit is never parsed.
    _split(
        tmp_path,
        _doc("EX-99", "broken.xml", "<ownershipDocument><broken", seq=1),
        _form4_doc(seq=2),
    )
    calls = []
    real = filing_flow.parse_form4

    def spy(content, accession, filing_date=None):
        calls.append(content)
        return real(content, accession, filing_date=filing_date)

    monkeypatch.setattr(filing_flow, "parse_form4", spy)

    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is True
    assert calls == [_fixture("form4_sample.xml")]
    assert failures == []
    session.commit.assert_called_once()


def test_parse_form4_falls_back_to_other_documents(tmp_path, session, failures):
    # Mislabelled: the ownership XML sits in a non-4 document.
    _split(
        tmp_path,
        _doc("4", "cover.htm", "<html>cover letter</html>", seq=1, xml=False),
        _doc("EX-99", "own.xml", _fixture("form4_sample.xml"), seq=2),
    )
    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is True
    assert failures == []


def test_parse_form4_without_manifest_uses_loose_xml_files(tmp_path, session, failures):
    (tmp_path / "doc.xml").write_text(_fixture("form4_sample.xml"))
    # The complete submission itself is not a candidate: it is not one document.
    (tmp_path / "primary.txt").write_text("<ownershipDocument><broken")

    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is True
    assert failures == []
    session.commit.assert_called_once()


def test_parse_form4_skips_manifest_entries_missing_on_disk(tmp_path, session, failures):
    _split(tmp_path, _form4_doc())
    (tmp_path / "001_wk-form4_1710534615.xml").unlink()
    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is False
    session.merge.assert_not_called()
    assert failures == []


def test_parse_form4_without_ownership_document(tmp_path, session, failures):
    _split(tmp_path, _doc("4", "a.htm", "<html>not a form 4</html>", xml=False))
    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is False
    session.merge.assert_not_called()
    assert failures == []


def test_parse_form4_with_no_files(tmp_path, session, failures):
    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is False
    assert failures == []


def test_parse_form4_parse_error_goes_to_dead_letter(tmp_path, session, failures, monkeypatch):
    _split(tmp_path, _form4_doc())

    def boom(content, accession, filing_date=None):
        raise ValueError("malformed")

    monkeypatch.setattr(filing_flow, "parse_form4", boom)
    filing = _filing()

    assert filing_flow.parse_and_store_form4.fn(tmp_path, filing) is False
    assert failures == [(filing.accession_number, "4", "ValueError", filing_flow._PARSER_VERSION)]


def test_parse_form4_records_one_failure_with_the_last_error(
    tmp_path, session, failures, monkeypatch
):
    _split(
        tmp_path,
        _doc("4", "a.xml", "<ownershipDocument>A</ownershipDocument>", seq=1),
        _doc("EX-99", "b.xml", "<ownershipDocument>B</ownershipDocument>", seq=2),
    )
    errors = iter([ValueError("first"), KeyError("second")])

    def boom(content, accession, filing_date=None):
        raise next(errors)

    monkeypatch.setattr(filing_flow, "parse_form4", boom)

    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is False
    assert [f[2] for f in failures] == ["KeyError"]


def test_parse_form4_no_failure_recorded_when_a_later_candidate_succeeds(
    tmp_path, session, failures
):
    _split(
        tmp_path,
        _doc("4", "broken.xml", "<ownershipDocument><broken", seq=1),
        _doc("EX-99", "own.xml", _fixture("form4_sample.xml"), seq=2),
    )
    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is True
    assert failures == []
    session.commit.assert_called_once()


def test_parse_form4_db_error_rolls_back_and_records(tmp_path, session, failures):
    _split(tmp_path, _form4_doc())
    session.commit.side_effect = RuntimeError("db down")

    assert filing_flow.parse_and_store_form4.fn(tmp_path, _filing()) is False
    session.rollback.assert_called_once()
    session.close.assert_called_once()
    assert failures == [("0000320193-24-000001", "4", "RuntimeError", filing_flow._PARSER_VERSION)]


# ---------------------------------------------------------------- form 13F


@pytest.mark.parametrize("form_type", ["13F-HR", "13F-HR/A"])
def test_parse_form13f_uses_information_table_document(tmp_path, session, failures, form_type):
    _split(tmp_path, *_13f_docs(form_type))
    filing = _filing(form_type, acc="0001067983-24-000042")

    assert filing_flow.parse_and_store_form13f.fn(tmp_path, filing) is True

    merged = _merged(session)
    assert len(merged) == 2
    assert all(isinstance(m, HoldingsPosition) for m in merged)
    apple = next(m for m in merged if m.name_of_issuer == "APPLE INC")
    assert apple.cusip == "037833100"
    assert apple.shares == 503000000
    assert apple.filer_cik == 1067983
    assert apple.filer_name == "BERKSHIRE HATHAWAY INC"
    assert apple.accession_number == "0001067983-24-000042"
    assert apple.period_of_report == datetime.date(2024, 3, 31)
    session.commit.assert_called_once()
    assert failures == []


def test_parse_form13f_missing_primary(tmp_path, session, failures):
    assert filing_flow.parse_and_store_form13f.fn(tmp_path, _filing("13F-HR")) is False
    session.merge.assert_not_called()
    assert failures == []


def test_parse_form13f_info_table_without_primary_document(tmp_path, session, failures):
    _split(tmp_path, _13f_docs()[1])
    assert filing_flow.parse_and_store_form13f.fn(tmp_path, _filing("13F-HR")) is False
    session.merge.assert_not_called()
    assert failures == []


def test_parse_form13f_without_info_table_goes_to_dead_letter(tmp_path, session, failures):
    # A 13F-HR always carries an information table. Without one nothing is
    # stored and the filing is not reported as parsed (so it is not marked).
    _split(tmp_path, _13f_docs()[0])
    filing = _filing("13F-HR")

    assert filing_flow.parse_and_store_form13f.fn(tmp_path, filing) is False
    session.merge.assert_not_called()
    session.commit.assert_not_called()
    assert failures == [
        (filing.accession_number, "13F-HR", "ValueError", filing_flow._PARSER_VERSION)
    ]


def test_parse_form13f_parse_error_goes_to_dead_letter(tmp_path, session, failures):
    _split(
        tmp_path,
        _doc("13F-HR", "primary_doc.xml", "<edgarSubmission><cik>1</cik></edgarSubmission>"),
        _13f_docs()[1],
    )
    # No periodOfReport in the primary doc: the parser refuses to guess the scaling.
    assert filing_flow.parse_and_store_form13f.fn(tmp_path, _filing("13F-HR")) is False
    session.merge.assert_not_called()
    assert failures[0][1:3] == ("13F-HR", "ValueError")


def test_parse_form13f_db_error_rolls_back(tmp_path, session, failures):
    _split(tmp_path, *_13f_docs())
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


_EX21_HTML = (
    "<html><body><h2>Item 1A. Risk Factors</h2><p>Subsidiaries of the registrant: Apple "
    "Operations International Limited, Apple Sales International Limited, Braeburn "
    "Capital, Inc.</p></body></html>"
)


def _ten_k_docs(form_type: str = "10-K") -> list[str]:
    return [
        _doc(form_type, "aapl-20230930.htm", _TEN_K_HTML, seq=1, xml=False),
        _doc("EX-21.1", "ex21.htm", _EX21_HTML, seq=2, xml=False),
    ]


def test_parse_form10k_merges_sections(tmp_path, session, failures):
    _split(tmp_path, *_ten_k_docs())
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


def _spy_parse_form10k(monkeypatch) -> dict:
    seen: dict = {}
    real = filing_flow.parse_form10k

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(filing_flow, "parse_form10k", spy)
    return seen


@pytest.mark.parametrize("form_type", ["10-K", "10-K/A", "10-Q", "10-Q/A"])
def test_parse_form10k_reads_main_document_by_form_type(
    tmp_path, session, failures, monkeypatch, form_type
):
    _split(tmp_path, *_ten_k_docs(form_type))
    seen = _spy_parse_form10k(monkeypatch)

    assert filing_flow.parse_and_store_form10k.fn(tmp_path, _filing(form_type)) is True
    # The filing's own document, not the exhibit and not the whole submission.
    assert seen["html_content"] == _TEN_K_HTML.strip()
    assert "Subsidiaries" not in seen["html_content"]


def test_parse_form10k_loads_cached_companyfacts(
    tmp_path, raw_root, session, failures, monkeypatch
):
    from sec_filings.models import XbrlFact

    filing = _filing("10-K")
    facts = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "val": 383285000000,
                                "accn": filing.accession_number,
                                "start": "2022-09-25",
                                "end": "2023-09-30",
                                "frame": "CY2023",
                            },
                            {"val": 1, "accn": "0000320193-22-000108", "end": "2022-09-24"},
                        ]
                    }
                }
            }
        },
    }
    cache = raw_root / "companyfacts" / "320193.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps(facts))
    _split(tmp_path, *_ten_k_docs())
    seen = _spy_parse_form10k(monkeypatch)

    assert filing_flow.parse_and_store_form10k.fn(tmp_path, filing) is True

    assert seen["xbrl_facts_json"] == facts
    stored = [m for m in _merged(session) if isinstance(m, XbrlFact)]
    # Only this filing's fact is stored, not the other accession's.
    assert [(f.concept, f.value, f.context_id) for f in stored] == [
        ("us-gaap:Revenues", "383285000000", "CY2023")
    ]
    assert stored[0].period_start == datetime.date(2022, 9, 25)
    assert any(isinstance(m, FilingSection) for m in _merged(session))
    assert failures == []


def test_parse_form10k_corrupt_companyfacts_still_stores_sections(
    tmp_path, raw_root, session, failures, monkeypatch
):
    cache = raw_root / "companyfacts" / "320193.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{truncated")
    _split(tmp_path, *_ten_k_docs())
    seen = _spy_parse_form10k(monkeypatch)

    assert filing_flow.parse_and_store_form10k.fn(tmp_path, _filing("10-K")) is True
    assert seen["xbrl_facts_json"] is None
    assert _merged(session) and all(isinstance(m, FilingSection) for m in _merged(session))
    assert failures == []


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
    _split(tmp_path, *_ten_k_docs())
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
