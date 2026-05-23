"""Parser for SEC Form 10-K / 10-Q filings.

Two extraction paths:
1. XBRL facts via the companyfacts API (structured financials)
2. HTML section extraction via selectolax (risk factors, MD&A, etc.)
"""

import re

from selectolax.parser import HTMLParser

from sec_filings.parsers.contracts import (
    FilingSectionRecord,
    Form10KFiling,
    XbrlFactRecord,
)

_SECTION_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "item_1_business": [
        re.compile(r"item\s+1\.?\s*[\.\-—:]*\s*business", re.IGNORECASE),
    ],
    "item_1a_risk_factors": [
        re.compile(r"item\s+1a\.?\s*[\.\-—:]*\s*risk\s+factors?", re.IGNORECASE),
    ],
    "item_7_mda": [
        re.compile(
            r"item\s+7\.?\s*[\.\-—:]*\s*management.{0,5}s?\s+discussion",
            re.IGNORECASE,
        ),
    ],
}

_SECTION_ORDER = ["item_1_business", "item_1a_risk_factors", "item_7_mda"]


def _extract_sections(
    html_content: str, accession_number: str, cik: int
) -> list[FilingSectionRecord]:
    """Extract key sections from 10-K HTML using header-text matching."""
    tree = HTMLParser(html_content)
    body = tree.body
    if body is None:
        return []

    headers: list[tuple[str, int]] = []
    all_text_nodes: list[tuple[int, str]] = []

    for i, node in enumerate(body.traverse()):
        text = node.text(strip=True) if hasattr(node, "text") else ""
        if not text:
            continue
        all_text_nodes.append((i, text))

        tag = node.tag if hasattr(node, "tag") else ""
        is_header = tag in ("h1", "h2", "h3", "h4", "b", "strong") or (
            hasattr(node, "attributes")
            and any(
                "bold" in str(node.attributes.get(a, "")).lower()
                for a in ("style", "class")
                if node.attributes.get(a)
            )
        )

        if not is_header and len(text) < 200:
            is_header = True

        if is_header:
            for section_name, patterns in _SECTION_PATTERNS.items():
                for pattern in patterns:
                    if pattern.search(text[:200]):
                        headers.append((section_name, i))
                        break

    # Deduplicate: keep first occurrence of each section
    seen: set[str] = set()
    unique_headers: list[tuple[str, int]] = []
    for name, idx in headers:
        if name not in seen:
            seen.add(name)
            unique_headers.append((name, idx))

    sections: list[FilingSectionRecord] = []
    for h_idx, (section_name, start_pos) in enumerate(unique_headers):
        end_pos = unique_headers[h_idx + 1][1] if h_idx + 1 < len(unique_headers) else len(all_text_nodes)

        section_text_parts: list[str] = []
        for node_idx, text in all_text_nodes:
            if start_pos < node_idx < end_pos:
                section_text_parts.append(text)

        section_text = "\n".join(section_text_parts)
        if len(section_text) < 100:
            continue

        sections.append(
            FilingSectionRecord(
                accession_number=accession_number,
                cik=cik,
                section=section_name,
                text=section_text,
                char_count=len(section_text),
            )
        )

    return sections


def parse_xbrl_facts(
    facts_json: dict,
    accession_number: str,
    cik: int,
) -> list[XbrlFactRecord]:
    """Parse XBRL facts from the companyfacts JSON API response."""
    records: list[XbrlFactRecord] = []

    facts = facts_json.get("facts", {})
    for taxonomy, concepts in facts.items():
        for concept_name, concept_data in concepts.items():
            units = concept_data.get("units", {})
            for unit_name, entries in units.items():
                for entry in entries:
                    val = entry.get("val")
                    if val is None:
                        continue

                    accn = entry.get("accn", "").replace("-", "")
                    if accn != accession_number.replace("-", ""):
                        continue

                    period_start = None
                    period_end = None
                    is_instant = False

                    if "start" in entry:
                        try:
                            period_start = __import__("datetime").date.fromisoformat(entry["start"])
                        except ValueError:
                            pass
                    if "end" in entry:
                        try:
                            period_end = __import__("datetime").date.fromisoformat(entry["end"])
                        except ValueError:
                            pass
                    if period_start is None and period_end is not None:
                        is_instant = True

                    records.append(
                        XbrlFactRecord(
                            accession_number=accession_number,
                            cik=cik,
                            concept=f"{taxonomy}:{concept_name}",
                            value=str(val),
                            unit=unit_name,
                            decimals=str(entry.get("decimals", "")),
                            period_start=period_start,
                            period_end=period_end,
                            context_id=entry.get("frame", f"{entry.get('fy', '')}-{entry.get('fp', '')}"),
                            is_instant=is_instant,
                        )
                    )

    return records


def parse_form10k(
    html_content: str | None,
    xbrl_facts_json: dict | None,
    accession_number: str,
    cik: int,
) -> Form10KFiling:
    xbrl_facts: list[XbrlFactRecord] = []
    if xbrl_facts_json:
        xbrl_facts = parse_xbrl_facts(xbrl_facts_json, accession_number, cik)

    sections: list[FilingSectionRecord] = []
    if html_content:
        sections = _extract_sections(html_content, accession_number, cik)

    return Form10KFiling(
        accession_number=accession_number,
        cik=cik,
        xbrl_facts=xbrl_facts,
        sections=sections,
    )
