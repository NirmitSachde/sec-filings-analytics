"""Parser for SEC Form 4 (insider transaction) XML filings."""

import datetime
import re

from lxml import etree

from sec_filings.parsers.contracts import Form4Filing, Form4Transaction

_NAMESPACE = {"o": "http://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000000000&type=4&dateb=&owner=include&count=40"}


def _text(element: etree._Element | None) -> str | None:
    if element is None:
        return None
    text = element.text
    return text.strip() if text else None


def _int_or_none(element: etree._Element | None) -> int | None:
    val = _text(element)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _float_or_none(element: etree._Element | None) -> float | None:
    val = _text(element)
    if val is None:
        return None
    try:
        return float(val.replace(",", ""))
    except ValueError:
        return None


def _bool_val(element: etree._Element | None) -> bool:
    val = _text(element)
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes")


def _parse_date(element: etree._Element | None) -> datetime.date | None:
    val = _text(element)
    if val is None:
        return None
    try:
        return datetime.date.fromisoformat(val)
    except ValueError:
        return None


def _check_10b5_1(root: etree._Element) -> bool:
    """Check footnotes for 10b5-1 plan references."""
    for footnote in root.iter("footnote"):
        text = footnote.text or ""
        if re.search(r"10b5-1|Rule\s+10b5-1|10b-?5-?1", text, re.IGNORECASE):
            return True
    return False


def parse_form4(xml_content: str | bytes, accession_number: str) -> Form4Filing:
    if isinstance(xml_content, str):
        xml_content = xml_content.encode("utf-8")

    root = etree.fromstring(xml_content)

    issuer = root.find(".//issuer")
    issuer_cik = int(_text(issuer.find("issuerCik")) or "0") if issuer is not None else 0
    issuer_name = _text(issuer.find("issuerName")) or "" if issuer is not None else ""
    issuer_ticker = _text(issuer.find("issuerTradingSymbol")) if issuer is not None else None

    is_10b5_1 = _check_10b5_1(root)
    transactions: list[Form4Transaction] = []
    tx_index = 0

    for owner_el in root.findall(".//reportingOwner"):
        owner_id = owner_el.find("reportingOwnerId")
        owner_rel = owner_el.find("reportingOwnerRelationship")

        owner_cik = int(_text(owner_id.find("rptOwnerCik")) or "0") if owner_id is not None else 0
        owner_name = _text(owner_id.find("rptOwnerName")) or "" if owner_id is not None else ""

        is_director = _bool_val(owner_rel.find("isDirector")) if owner_rel is not None else False
        is_officer = _bool_val(owner_rel.find("isOfficer")) if owner_rel is not None else False
        is_ten_pct = _bool_val(owner_rel.find("isTenPercentOwner")) if owner_rel is not None else False
        is_other = _bool_val(owner_rel.find("isOther")) if owner_rel is not None else False
        officer_title = _text(owner_rel.find("officerTitle")) if owner_rel is not None else None

        filing_date_el = root.find(".//periodOfReport")
        filing_date = _parse_date(filing_date_el) or datetime.date.today()

        for nd_tx in root.findall(".//nonDerivativeTransaction"):
            sec_title = _text(nd_tx.find(".//securityTitle/value")) or ""
            tx_date = _parse_date(nd_tx.find(".//transactionDate/value"))
            tx_code = _text(nd_tx.find(".//transactionCoding/transactionCode"))

            amounts = nd_tx.find(".//transactionAmounts")
            shares = _float_or_none(
                amounts.find("transactionShares/value") if amounts is not None else None
            )
            price = _float_or_none(
                amounts.find("transactionPricePerShare/value") if amounts is not None else None
            )

            post_el = nd_tx.find(".//postTransactionAmounts/sharesOwnedFollowingTransaction/value")
            shares_after = _float_or_none(post_el)

            ownership_el = nd_tx.find(".//ownershipNature/directOrIndirectOwnership/value")
            d_or_i = _text(ownership_el)

            transactions.append(
                Form4Transaction(
                    accession_number=accession_number,
                    filing_date=filing_date,
                    transaction_index=tx_index,
                    owner_cik=owner_cik,
                    owner_name=owner_name,
                    is_director=is_director,
                    is_officer=is_officer,
                    is_ten_percent_owner=is_ten_pct,
                    is_other=is_other,
                    officer_title=officer_title,
                    issuer_cik=issuer_cik,
                    issuer_name=issuer_name,
                    issuer_ticker=issuer_ticker,
                    security_title=sec_title,
                    transaction_date=tx_date,
                    transaction_code=tx_code,
                    shares=shares,
                    price_per_share=price,
                    shares_after=shares_after,
                    direct_or_indirect=d_or_i,
                    is_derivative=False,
                    is_10b5_1=is_10b5_1,
                )
            )
            tx_index += 1

        for d_tx in root.findall(".//derivativeTransaction"):
            sec_title = _text(d_tx.find(".//securityTitle/value")) or ""
            tx_date = _parse_date(d_tx.find(".//transactionDate/value"))
            tx_code = _text(d_tx.find(".//transactionCoding/transactionCode"))

            amounts = d_tx.find(".//transactionAmounts")
            shares = _float_or_none(
                amounts.find("transactionShares/value") if amounts is not None else None
            )
            price = _float_or_none(
                amounts.find("transactionPricePerShare/value") if amounts is not None else None
            )

            transactions.append(
                Form4Transaction(
                    accession_number=accession_number,
                    filing_date=filing_date,
                    transaction_index=tx_index,
                    owner_cik=owner_cik,
                    owner_name=owner_name,
                    is_director=is_director,
                    is_officer=is_officer,
                    is_ten_percent_owner=is_ten_pct,
                    is_other=is_other,
                    officer_title=officer_title,
                    issuer_cik=issuer_cik,
                    issuer_name=issuer_name,
                    issuer_ticker=issuer_ticker,
                    security_title=sec_title,
                    transaction_date=tx_date,
                    transaction_code=tx_code,
                    shares=shares,
                    price_per_share=price,
                    shares_after=None,
                    direct_or_indirect=None,
                    is_derivative=True,
                    is_10b5_1=is_10b5_1,
                )
            )
            tx_index += 1

    return Form4Filing(accession_number=accession_number, transactions=transactions)
