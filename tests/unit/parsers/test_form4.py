"""Tests for Form 4 parser using real-but-trimmed filing fixtures."""

import datetime
from pathlib import Path

from sec_filings.parsers.form4 import parse_form4

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "filings"


def test_parse_form4_basic():
    xml = (FIXTURES_DIR / "form4_sample.xml").read_text()
    result = parse_form4(xml, "0000320193-24-000042")

    assert result.accession_number == "0000320193-24-000042"
    assert len(result.transactions) == 2


def test_parse_form4_non_derivative_transaction():
    xml = (FIXTURES_DIR / "form4_sample.xml").read_text()
    result = parse_form4(xml, "0000320193-24-000042")

    nd_tx = [t for t in result.transactions if not t.is_derivative]
    assert len(nd_tx) == 1

    tx = nd_tx[0]
    assert tx.owner_name == "Cook Timothy D"
    assert tx.owner_cik == 1234567
    assert tx.is_officer is True
    assert tx.is_director is True
    assert tx.officer_title == "Chief Executive Officer"
    assert tx.issuer_name == "Apple Inc"
    assert tx.issuer_ticker == "AAPL"
    assert tx.issuer_cik == 320193
    assert tx.security_title == "Common Stock"
    assert tx.transaction_date == datetime.date(2024, 3, 15)
    assert tx.transaction_code == "P"
    assert tx.shares == 10000.0
    assert tx.price_per_share == 172.50
    assert tx.shares_after == 3500000.0
    assert tx.direct_or_indirect == "D"


def test_parse_form4_derivative_transaction():
    xml = (FIXTURES_DIR / "form4_sample.xml").read_text()
    result = parse_form4(xml, "0000320193-24-000042")

    d_tx = [t for t in result.transactions if t.is_derivative]
    assert len(d_tx) == 1

    tx = d_tx[0]
    assert tx.security_title == "Restricted Stock Units"
    assert tx.transaction_code == "A"
    assert tx.shares == 50000.0
    assert tx.is_derivative is True


def test_parse_form4_10b5_1_detection():
    xml = (FIXTURES_DIR / "form4_sample.xml").read_text()
    result = parse_form4(xml, "0000320193-24-000042")

    assert all(tx.is_10b5_1 for tx in result.transactions)


def test_parse_form4_bytes_input():
    xml = (FIXTURES_DIR / "form4_sample.xml").read_bytes()
    result = parse_form4(xml, "test-accession")
    assert len(result.transactions) > 0


def test_parse_form4_transaction_indices():
    xml = (FIXTURES_DIR / "form4_sample.xml").read_text()
    result = parse_form4(xml, "test-accession")

    indices = [tx.transaction_index for tx in result.transactions]
    assert indices == [0, 1]
