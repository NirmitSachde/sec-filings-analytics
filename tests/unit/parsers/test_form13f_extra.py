"""Extra Form 13F parser tests: namespace fallbacks, value scaling, sparse holdings."""

import datetime

import pytest
from lxml import etree

from sec_filings.parsers import form13f
from sec_filings.parsers.form13f import parse_form13f

_NS_MAIN = "http://www.sec.gov/edgar/document/thirteenf/informationtable"
_NS_ALT = "http://www.sec.gov/edgar/thirteenf"


def _primary(period: str | None = "2024-03-31", cik: str = "0001067983", name: str = "FUND") -> str:
    period_xml = f"<periodOfReport>{period}</periodOfReport>" if period is not None else ""
    return (
        "<edgarSubmission xmlns='http://www.sec.gov/edgar/thirteenffiler'>"
        f"<headerData><filer><credentials><cik>{cik}</cik></credentials></filer>{period_xml}"
        "</headerData>"
        f"<formData><coverPage><filingManager><name>{name}</name></filingManager></coverPage>"
        "<signatureBlock><name>Second Name Ignored</name></signatureBlock></formData>"
        "</edgarSubmission>"
    )


def _holding(
    name: str = "ACME CORP",
    cusip: str = "000123456",
    value: str = "1,000",
    shares: str | None = "500",
    share_type: str | None = "SH",
    voting: str = "<Sole>400</Sole><Shared>50</Shared><None>50</None>",
    discretion: str | None = "SOLE",
) -> str:
    parts = [f"<nameOfIssuer>{name}</nameOfIssuer>", f"<cusip>{cusip}</cusip>"]
    parts.append(f"<value>{value}</value>")
    if shares is not None or share_type is not None:
        inner = ""
        if shares is not None:
            inner += f"<sshPrnamt>{shares}</sshPrnamt>"
        if share_type is not None:
            inner += f"<sshPrnamtType>{share_type}</sshPrnamtType>"
        parts.append(f"<shrsOrPrnAmt>{inner}</shrsOrPrnAmt>")
    if discretion is not None:
        parts.append(f"<investmentDiscretion>{discretion}</investmentDiscretion>")
    if voting:
        parts.append(f"<votingAuthority>{voting}</votingAuthority>")
    return "<infoTable>" + "".join(parts) + "</infoTable>"


def _info(*holdings: str, ns: str | None = _NS_MAIN) -> str:
    xmlns = f" xmlns='{ns}'" if ns else ""
    return f"<informationTable{xmlns}>{''.join(holdings)}</informationTable>"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _el(text):
    el = etree.Element("v")
    el.text = text
    return el


def test_text_helper():
    assert form13f._text(None) is None
    assert form13f._text(_el(None)) is None
    assert form13f._text(_el("  x ")) == "x"


@pytest.mark.parametrize(
    ("text", "expected"),
    [(None, 0), ("12", 12), ("1,234,567", 1234567), ("1.5", 0), ("abc", 0)],
)
def test_int_or_zero(text, expected):
    el = None if text is None else _el(text)
    assert form13f._int_or_zero(el) == expected


def test_parse_date_helper():
    today = datetime.date.today()
    assert form13f._parse_date(None) == today
    assert form13f._parse_date(" 2021-12-31 ") == datetime.date(2021, 12, 31)
    assert form13f._parse_date("12-31-2021") == today


# ---------------------------------------------------------------------------
# parse_form13f
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ns", [_NS_MAIN, _NS_ALT, None], ids=["main-ns", "alt-ns", "no-ns"])
def test_parse_form13f_namespace_variants_give_same_holding(ns):
    result = parse_form13f(_info(_holding(), ns=ns), _primary(), "acc-1")

    assert result.filer_cik == 1067983
    assert result.filer_name == "FUND"
    assert result.period_of_report == datetime.date(2024, 3, 31)
    (h,) = result.holdings
    assert h.name_of_issuer == "ACME CORP"
    assert h.cusip == "000123456"
    assert h.value == 1000
    assert h.shares == 500
    assert h.share_type == "SH"
    assert h.investment_discretion == "SOLE"
    assert (h.voting_sole, h.voting_shared, h.voting_none) == (400, 50, 50)


def test_parse_form13f_bytes_input():
    result = parse_form13f(_info(_holding()).encode(), _primary().encode(), "acc-b")
    assert result.accession_number == "acc-b"
    assert len(result.holdings) == 1


def test_parse_form13f_pre_2022_values_are_in_thousands():
    result = parse_form13f(_info(_holding(value="2,500")), _primary("2021-12-31"), "acc")
    assert result.holdings[0].value == 2_500_000


def test_parse_form13f_2022_and_later_values_are_dollars():
    result = parse_form13f(_info(_holding(value="2500")), _primary("2022-03-31"), "acc")
    assert result.holdings[0].value == 2500


def test_parse_form13f_missing_period_defaults_to_today_and_dollars():
    result = parse_form13f(_info(_holding(value="7")), _primary(period=None), "acc")
    assert result.period_of_report == datetime.date.today()
    assert result.holdings[0].value == 7


def test_parse_form13f_report_calendar_or_quarter_is_used():
    primary = (
        "<edgarSubmission><cik>12</cik>"
        "<reportCalendarOrQuarter>2020-06-30</reportCalendarOrQuarter></edgarSubmission>"
    )
    result = parse_form13f(_info(_holding(value="3")), primary, "acc")
    assert result.period_of_report == datetime.date(2020, 6, 30)
    assert result.filer_cik == 12
    assert result.filer_name == ""
    assert result.holdings[0].value == 3000


def test_parse_form13f_empty_first_name_and_cik():
    primary = "<s><cik></cik><name></name><name>Later</name></s>"
    result = parse_form13f(_info(), primary, "acc")
    assert result.filer_cik == 0
    # An empty first <name> leaves filer_name empty, so the next one is taken.
    assert result.filer_name == "Later"
    assert result.holdings == []


def test_parse_form13f_cusip_normalized():
    result = parse_form13f(
        _info(_holding(cusip="g5960l10"), _holding(cusip="1234567890AB")),
        _primary(),
        "acc",
    )
    assert [h.cusip for h in result.holdings] == ["G5960L100", "123456789"]


def test_parse_form13f_missing_shares_block_defaults():
    result = parse_form13f(
        _info(_holding(shares=None, share_type=None, voting="", discretion=None)),
        _primary(),
        "acc",
    )
    (h,) = result.holdings
    assert h.shares == 0
    assert h.share_type == "SH"
    assert h.investment_discretion is None
    assert (h.voting_sole, h.voting_shared, h.voting_none) == (0, 0, 0)


@pytest.mark.parametrize("ns", [_NS_MAIN, _NS_ALT, None], ids=["main-ns", "alt-ns", "no-ns"])
def test_parse_form13f_principal_amount_type(ns):
    result = parse_form13f(
        _info(_holding(shares="1,000,000", share_type="PRN"), ns=ns), _primary(), "acc"
    )
    (h,) = result.holdings
    assert h.shares == 1_000_000
    assert h.share_type == "PRN"


@pytest.mark.parametrize("ns", [_NS_MAIN, _NS_ALT, None], ids=["main-ns", "alt-ns", "no-ns"])
def test_parse_form13f_shares_without_type_and_type_without_shares(ns):
    result = parse_form13f(
        _info(
            _holding(name="A", shares="10", share_type=None),
            _holding(name="B", shares=None, share_type="PRN"),
            ns=ns,
        ),
        _primary(),
        "acc",
    )
    a, b = result.holdings
    assert (a.shares, a.share_type) == (10, "SH")
    assert (b.shares, b.share_type) == (0, "PRN")


def test_parse_form13f_partial_voting_and_bad_numbers():
    result = parse_form13f(
        _info(_holding(value="n/a", shares="lots", voting="<Sole>9</Sole>")),
        _primary(),
        "acc",
    )
    (h,) = result.holdings
    assert h.value == 0
    assert h.shares == 0
    assert (h.voting_sole, h.voting_shared, h.voting_none) == (9, 0, 0)


def test_parse_form13f_mixed_namespace_children_fall_back_to_localname():
    # Table in the main namespace, children in some other namespace.
    holding = (
        "<infoTable xmlns:x='urn:other'>"
        "<x:nameOfIssuer>MIXED INC</x:nameOfIssuer><x:cusip>111111111</x:cusip>"
        "<x:value>5</x:value>"
        "<x:shrsOrPrnAmt><x:sshPrnamt>6</x:sshPrnamt><x:sshPrnamtType>SH</x:sshPrnamtType>"
        "</x:shrsOrPrnAmt>"
        "</infoTable>"
    )
    (h,) = parse_form13f(_info(holding), _primary(), "acc").holdings
    assert h.name_of_issuer == "MIXED INC"
    assert h.cusip == "111111111"
    assert h.value == 5
    assert h.shares == 6


def test_parse_form13f_empty_information_table():
    result = parse_form13f(_info(ns=None), _primary(), "acc")
    assert result.holdings == []


def test_parse_form13f_holding_without_name_or_cusip():
    # Missing cusip is padded to nine zeros rather than failing validation.
    holding = "<infoTable><value>1</value></infoTable>"
    (h,) = parse_form13f(_info(holding), _primary(), "acc").holdings
    assert h.name_of_issuer == ""
    assert h.cusip == "000000000"
