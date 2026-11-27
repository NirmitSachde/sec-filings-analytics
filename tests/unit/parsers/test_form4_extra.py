"""Extra Form 4 parser tests: helper edge cases and sparse/odd filings."""

import datetime

import pytest
from lxml import etree

from sec_filings.parsers import form4
from sec_filings.parsers.form4 import parse_form4


def _el(text: str | None) -> etree._Element:
    el = etree.Element("value")
    el.text = text
    return el


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_text_handles_none_empty_and_whitespace():
    assert form4._text(None) is None
    assert form4._text(_el(None)) is None
    assert form4._text(_el("")) is None
    assert form4._text(_el("  AAPL \n")) == "AAPL"


@pytest.mark.parametrize(
    ("text", "expected"),
    [(None, None), ("42", 42), (" 0007 ", 7), ("4.5", None), ("abc", None)],
)
def test_int_or_none(text, expected):
    el = None if text is None else _el(text)
    assert form4._int_or_none(el) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [(None, None), ("1,234.50", 1234.5), ("0", 0.0), ("-3", -3.0), ("n/a", None)],
)
def test_float_or_none(text, expected):
    el = None if text is None else _el(text)
    assert form4._float_or_none(el) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, False),
        ("1", True),
        ("true", True),
        ("TRUE", True),
        (" Yes ", True),
        ("0", False),
        ("false", False),
        ("maybe", False),
    ],
)
def test_bool_val(text, expected):
    el = None if text is None else _el(text)
    assert form4._bool_val(el) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, None),
        ("2024-02-29", datetime.date(2024, 2, 29)),
        ("2023-02-29", None),
        ("03/15/2024", None),
    ],
)
def test_parse_date(text, expected):
    el = None if text is None else _el(text)
    assert form4._parse_date(el) == expected


@pytest.mark.parametrize(
    ("footnote", "expected"),
    [
        ("Sold under a Rule 10b5-1 plan adopted 2023.", True),
        ("Pursuant to rule  10B5-1.", True),
        ("Trading plan per 10b51 adopted earlier.", True),
        ("Shares held by family trust.", False),
    ],
)
def test_check_10b5_1(footnote, expected):
    root = etree.fromstring(
        f"<ownershipDocument><footnotes><footnote id='F1'>{footnote}</footnote>"
        "</footnotes></ownershipDocument>".encode()
    )
    assert form4._check_10b5_1(root) is expected


def test_check_10b5_1_no_footnotes_or_empty_footnote():
    assert form4._check_10b5_1(etree.fromstring(b"<ownershipDocument/>")) is False
    root = etree.fromstring(b"<ownershipDocument><footnote/></ownershipDocument>")
    assert form4._check_10b5_1(root) is False


# ---------------------------------------------------------------------------
# parse_form4 on inline fixtures
# ---------------------------------------------------------------------------

_TWO_OWNER_SALE = b"""<?xml version="1.0"?>
<ownershipDocument>
  <periodOfReport>2024-05-01</periodOfReport>
  <issuer>
    <issuerCik>0000789019</issuerCik>
    <issuerName>  Microsoft Corp </issuerName>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0000000011</rptOwnerCik>
      <rptOwnerName>Fund A LP</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isTenPercentOwner>1</isTenPercentOwner>
    </reportingOwnerRelationship>
  </reportingOwner>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0000000022</rptOwnerCik>
      <rptOwnerName>Fund A GP LLC</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isOther>1</isOther>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-04-30</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1,500</value></transactionShares>
        <transactionPricePerShare><value>410.25</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>98,500</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>I</value></directOrIndirectOwnership>
      </ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <footnotes><footnote id="F1">Held by the fund.</footnote></footnotes>
</ownershipDocument>
"""


def test_parse_form4_multiple_owners_each_get_every_transaction():
    result = parse_form4(_TWO_OWNER_SALE, "0000789019-24-000777")

    assert len(result.transactions) == 2
    a, gp = result.transactions
    assert [t.transaction_index for t in result.transactions] == [0, 1]
    assert (a.owner_cik, a.owner_name) == (11, "Fund A LP")
    assert (gp.owner_cik, gp.owner_name) == (22, "Fund A GP LLC")
    assert a.is_ten_percent_owner is True and a.is_other is False
    assert gp.is_other is True and gp.is_ten_percent_owner is False
    for tx in result.transactions:
        assert tx.accession_number == "0000789019-24-000777"
        assert tx.issuer_cik == 789019
        assert tx.issuer_name == "Microsoft Corp"
        assert tx.issuer_ticker is None
        assert tx.filing_date == datetime.date(2024, 5, 1)
        assert tx.transaction_date == datetime.date(2024, 4, 30)
        assert tx.transaction_code == "S"
        assert tx.shares == 1500.0
        assert tx.price_per_share == 410.25
        assert tx.shares_after == 98500.0
        assert tx.direct_or_indirect == "I"
        assert tx.is_derivative is False
        assert tx.is_10b5_1 is False
        assert tx.is_director is False and tx.is_officer is False
        assert tx.officer_title is None


_SPARSE = """<ownershipDocument>
  <periodOfReport>not-a-date</periodOfReport>
  <reportingOwner/>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>bad</value></transactionDate>
      <transactionAmounts>
        <transactionShares><value></value></transactionShares>
        <transactionPricePerShare><value>see footnote</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction/>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction>
      <securityTitle><value>Stock Option</value></securityTitle>
    </derivativeTransaction>
  </derivativeTable>
</ownershipDocument>
"""


def test_parse_form4_sparse_filing_uses_safe_defaults():
    result = parse_form4(_SPARSE, "acc-sparse")

    assert len(result.transactions) == 3
    first, empty, deriv = result.transactions

    for tx in result.transactions:
        # No issuer block and no owner id/relationship.
        assert tx.issuer_cik == 0
        assert tx.issuer_name == ""
        assert tx.issuer_ticker is None
        assert tx.owner_cik == 0
        assert tx.owner_name == ""
        assert not any([tx.is_director, tx.is_officer, tx.is_ten_percent_owner, tx.is_other])
        # Unparseable periodOfReport falls back to today.
        assert tx.filing_date == datetime.date.today()

    assert first.transaction_date is None
    assert first.shares is None
    assert first.price_per_share is None
    assert first.security_title == ""
    assert first.transaction_code is None
    assert first.shares_after is None
    assert first.direct_or_indirect is None

    # Transaction with no child elements at all (no transactionAmounts).
    assert empty.shares is None and empty.price_per_share is None

    assert deriv.is_derivative is True
    assert deriv.security_title == "Stock Option"
    assert deriv.shares is None and deriv.price_per_share is None
    assert deriv.transaction_index == 2


def test_parse_form4_owner_without_transactions():
    xml = (
        "<ownershipDocument><periodOfReport>2024-01-02</periodOfReport>"
        "<issuer><issuerCik>5</issuerCik><issuerName>X</issuerName></issuer>"
        "<reportingOwner><reportingOwnerId><rptOwnerCik>9</rptOwnerCik>"
        "</reportingOwnerId></reportingOwner></ownershipDocument>"
    )
    result = parse_form4(xml, "acc-empty")
    assert result.accession_number == "acc-empty"
    assert result.transactions == []


def test_parse_form4_no_reporting_owner_yields_nothing():
    xml = b"""<ownershipDocument>
      <nonDerivativeTable><nonDerivativeTransaction>
        <securityTitle><value>Common Stock</value></securityTitle>
      </nonDerivativeTransaction></nonDerivativeTable>
    </ownershipDocument>"""
    assert parse_form4(xml, "acc").transactions == []


def test_parse_form4_derivative_ignores_post_amounts_and_flags_10b5_1():
    xml = """<ownershipDocument>
      <periodOfReport>2024-06-30</periodOfReport>
      <issuer><issuerCik>1</issuerCik><issuerName>Co</issuerName>
        <issuerTradingSymbol>CO</issuerTradingSymbol></issuer>
      <reportingOwner>
        <reportingOwnerId><rptOwnerCik>2</rptOwnerCik><rptOwnerName>Exec</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship><isOfficer>1</isOfficer>
          <officerTitle> CFO </officerTitle></reportingOwnerRelationship>
      </reportingOwner>
      <derivativeTable><derivativeTransaction>
        <securityTitle><value>Option</value></securityTitle>
        <transactionDate><value>2024-06-28</value></transactionDate>
        <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>2,000</value></transactionShares>
          <transactionPricePerShare><value>12.5</value></transactionPricePerShare>
        </transactionAmounts>
        <postTransactionAmounts>
          <sharesOwnedFollowingTransaction><value>10</value></sharesOwnedFollowingTransaction>
        </postTransactionAmounts>
        <ownershipNature>
          <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
        </ownershipNature>
      </derivativeTransaction></derivativeTable>
      <footnotes><footnote id="F1">Exercised under a 10b5-1 plan.</footnote></footnotes>
    </ownershipDocument>"""
    (tx,) = parse_form4(xml, "acc-d").transactions
    assert tx.is_derivative is True
    assert tx.transaction_code == "M"
    assert tx.shares == 2000.0
    assert tx.price_per_share == 12.5
    assert tx.shares_after is None
    assert tx.direct_or_indirect is None
    assert tx.is_10b5_1 is True
    assert tx.officer_title == "CFO"
    assert tx.issuer_ticker == "CO"
    assert tx.transaction_date == datetime.date(2024, 6, 28)


def test_parse_form4_invalid_xml_raises():
    with pytest.raises(etree.XMLSyntaxError):
        parse_form4("<ownershipDocument><issuer>", "acc")
