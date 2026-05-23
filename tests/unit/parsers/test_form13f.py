"""Tests for Form 13F-HR parser using real-but-trimmed filing fixtures."""

import datetime
from pathlib import Path

from sec_filings.parsers.form13f import parse_form13f

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "filings"


def test_parse_form13f_basic():
    info_xml = (FIXTURES_DIR / "form13f_infotable.xml").read_text()
    primary_xml = (FIXTURES_DIR / "form13f_primary.xml").read_text()

    result = parse_form13f(info_xml, primary_xml, "0001067983-24-000042")

    assert result.accession_number == "0001067983-24-000042"
    assert result.filer_cik == 1067983
    assert result.filer_name == "BERKSHIRE HATHAWAY INC"
    assert result.period_of_report == datetime.date(2024, 3, 31)
    assert len(result.holdings) == 2


def test_parse_form13f_apple_holding():
    info_xml = (FIXTURES_DIR / "form13f_infotable.xml").read_text()
    primary_xml = (FIXTURES_DIR / "form13f_primary.xml").read_text()

    result = parse_form13f(info_xml, primary_xml, "test")

    apple = [h for h in result.holdings if h.name_of_issuer == "APPLE INC"]
    assert len(apple) == 1

    h = apple[0]
    assert h.cusip == "037833100"
    assert h.value == 91300000000
    assert h.shares == 503000000
    assert h.share_type == "SH"
    assert h.investment_discretion == "SOLE"
    assert h.voting_sole == 503000000
    assert h.voting_shared == 0
    assert h.voting_none == 0


def test_parse_form13f_bac_holding():
    info_xml = (FIXTURES_DIR / "form13f_infotable.xml").read_text()
    primary_xml = (FIXTURES_DIR / "form13f_primary.xml").read_text()

    result = parse_form13f(info_xml, primary_xml, "test")

    bac = [h for h in result.holdings if "BANK OF AMER" in h.name_of_issuer]
    assert len(bac) == 1

    h = bac[0]
    assert h.cusip == "060505104"
    assert h.shares == 1032000000


def test_parse_form13f_cusip_formatting():
    info_xml = (FIXTURES_DIR / "form13f_infotable.xml").read_text()
    primary_xml = (FIXTURES_DIR / "form13f_primary.xml").read_text()

    result = parse_form13f(info_xml, primary_xml, "test")

    for h in result.holdings:
        assert len(h.cusip) == 9
        assert h.cusip == h.cusip.upper()
