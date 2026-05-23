"""Parser for SEC Form 13F-HR (institutional holdings) XML filings."""

import datetime

from lxml import etree

from sec_filings.parsers.contracts import Form13FFiling, Form13FHolding

_NS_13F = {
    "ns": "http://www.sec.gov/edgar/document/thirteenf/informationtable",
}
_NS_13F_ALT = {
    "ns": "http://www.sec.gov/edgar/thirteenf",
}


def _text(element: etree._Element | None) -> str | None:
    if element is None:
        return None
    text = element.text
    return text.strip() if text else None


def _int_or_zero(element: etree._Element | None) -> int:
    val = _text(element)
    if val is None:
        return 0
    try:
        return int(val.replace(",", ""))
    except ValueError:
        return 0


def _parse_date(val: str | None) -> datetime.date:
    if val is None:
        return datetime.date.today()
    try:
        return datetime.date.fromisoformat(val.strip())
    except ValueError:
        return datetime.date.today()


def parse_form13f(
    info_table_xml: str | bytes,
    primary_doc_xml: str | bytes,
    accession_number: str,
) -> Form13FFiling:
    if isinstance(primary_doc_xml, str):
        primary_doc_xml = primary_doc_xml.encode("utf-8")
    if isinstance(info_table_xml, str):
        info_table_xml = info_table_xml.encode("utf-8")

    primary_root = etree.fromstring(primary_doc_xml)
    filer_cik = 0
    filer_name = ""
    period_of_report = datetime.date.today()

    for el in primary_root.iter():
        tag = etree.QName(el).localname if isinstance(el.tag, str) else ""
        if tag == "cik":
            filer_cik = int(el.text.strip()) if el.text else 0
        elif tag == "name" and filer_name == "":
            filer_name = el.text.strip() if el.text else ""
        elif tag == "periodOfReport":
            period_of_report = _parse_date(el.text)

    info_root = etree.fromstring(info_table_xml)

    holdings: list[Form13FHolding] = []

    info_tables = info_root.findall(".//ns:infoTable", _NS_13F)
    if not info_tables:
        info_tables = info_root.findall(".//ns:infoTable", _NS_13F_ALT)
    if not info_tables:
        info_tables = [el for el in info_root.iter() if etree.QName(el).localname == "infoTable"]

    # Detect if pre-2022 (values in thousands) or post-2022 (values in dollars)
    is_pre_2022 = period_of_report.year < 2022

    for table in info_tables:
        def _find(tag: str) -> etree._Element | None:
            el = table.find(f"ns:{tag}", _NS_13F)
            if el is None:
                el = table.find(f"ns:{tag}", _NS_13F_ALT)
            if el is None:
                for child in table.iter():
                    if etree.QName(child).localname == tag:
                        return child
            return el

        name_of_issuer = _text(_find("nameOfIssuer")) or ""
        cusip = (_text(_find("cusip")) or "").upper().ljust(9, "0")[:9]

        raw_value = _int_or_zero(_find("value"))
        value = raw_value * 1000 if is_pre_2022 else raw_value

        shrs_el = _find("shrsOrPrnAmt")
        shares = 0
        share_type = "SH"
        if shrs_el is not None:
            sh_el = shrs_el.find("ns:sshPrnamt", _NS_13F)
            if sh_el is None:
                sh_el = shrs_el.find("ns:sshPrnamt", _NS_13F_ALT)
            if sh_el is None:
                for child in shrs_el.iter():
                    if etree.QName(child).localname == "sshPrnamt":
                        sh_el = child
                        break
            shares = _int_or_zero(sh_el)

            type_el = shrs_el.find("ns:sshPrnamtType", _NS_13F)
            if type_el is None:
                type_el = shrs_el.find("ns:sshPrnamtType", _NS_13F_ALT)
            if type_el is None:
                for child in shrs_el.iter():
                    if etree.QName(child).localname == "sshPrnamtType":
                        type_el = child
                        break
            share_type = _text(type_el) or "SH"

        inv_disc = _text(_find("investmentDiscretion"))

        voting_el = _find("votingAuthority")
        voting_sole = 0
        voting_shared = 0
        voting_none = 0
        if voting_el is not None:
            for child in voting_el.iter():
                local = etree.QName(child).localname
                if local == "Sole":
                    voting_sole = _int_or_zero(child)
                elif local == "Shared":
                    voting_shared = _int_or_zero(child)
                elif local == "None":
                    voting_none = _int_or_zero(child)

        holdings.append(
            Form13FHolding(
                name_of_issuer=name_of_issuer,
                cusip=cusip,
                value=value,
                shares=shares,
                share_type=share_type,
                investment_discretion=inv_disc,
                voting_sole=voting_sole,
                voting_shared=voting_shared,
                voting_none=voting_none,
            )
        )

    return Form13FFiling(
        accession_number=accession_number,
        filer_cik=filer_cik,
        filer_name=filer_name,
        period_of_report=period_of_report,
        holdings=holdings,
    )
