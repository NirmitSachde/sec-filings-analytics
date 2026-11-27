"""Extra Form 10-K parser tests: section boundaries, XBRL filtering, top-level parse."""

import datetime
from types import SimpleNamespace

from sec_filings.parsers import form10k
from sec_filings.parsers.form10k import _extract_sections, parse_form10k, parse_xbrl_facts

_LONG_BUSINESS = (
    "We design, manufacture and market industrial sensors used in factories, "
    "utilities and transportation networks across North America and Europe."
)
_LONG_RISK = (
    "Our operations depend on a small number of suppliers. A disruption at any of "
    "them could delay shipments and materially reduce revenue and margins."
)
_LONG_MDA = (
    "Net sales increased eleven percent compared with the prior year, driven by "
    "higher volumes in our grid monitoring segment and favorable pricing."
)


def _html(body: str) -> str:
    return f"<html><body>{body}</body></html>"


def test_extract_sections_no_body_returns_empty(monkeypatch):
    monkeypatch.setattr(form10k, "HTMLParser", lambda html: SimpleNamespace(body=None))
    assert _extract_sections("<p>ignored</p>", "acc", 1) == []


def test_extract_sections_all_three_in_order_with_boundaries():
    html = _html(
        f"<h2>Item 1. Business</h2><p>{_LONG_BUSINESS}</p>"
        f"<h2>Item 1A. Risk Factors</h2><p>{_LONG_RISK}</p>"
        f"<h2>Item 7. Management's Discussion and Analysis</h2><p>{_LONG_MDA}</p>"
    )
    sections = _extract_sections(html, "0000000001-24-000001", 42)

    assert [s.section for s in sections] == [
        "item_1_business",
        "item_1a_risk_factors",
        "item_7_mda",
    ]
    by_name = {s.section: s for s in sections}
    assert _LONG_BUSINESS in by_name["item_1_business"].text
    assert _LONG_RISK not in by_name["item_1_business"].text
    assert _LONG_RISK in by_name["item_1a_risk_factors"].text
    assert _LONG_MDA not in by_name["item_1a_risk_factors"].text
    assert _LONG_MDA in by_name["item_7_mda"].text
    for s in sections:
        assert s.accession_number == "0000000001-24-000001"
        assert s.cik == 42
        assert s.char_count == len(s.text)
        # Header text itself is not part of the section body.
        assert "Item 1A. Risk Factors" not in s.text


def test_extract_sections_short_section_is_dropped():
    html = _html(
        "<h2>Item 1. Business</h2><p>Too short.</p>"
        f"<h2>Item 1A. Risk Factors</h2><p>{_LONG_RISK}</p>"
    )
    sections = _extract_sections(html, "acc", 1)
    assert [s.section for s in sections] == ["item_1a_risk_factors"]


def test_extract_sections_keeps_first_occurrence_of_duplicate_header():
    # A table of contents mentions Item 1A first; the first match wins.
    html = _html(
        "<p>Item 1A. Risk Factors</p>"
        f"<p>{_LONG_RISK}</p>"
        "<h2>Item 1A. Risk Factors</h2>"
        "<p>Later text that is still inside the same first section block.</p>"
    )
    sections = _extract_sections(html, "acc", 1)
    assert len(sections) == 1
    risk = sections[0]
    assert risk.section == "item_1a_risk_factors"
    assert risk.text.startswith(_LONG_RISK)
    assert "Later text" in risk.text


def test_extract_sections_bold_style_header_and_punctuation_variants():
    html = _html(
        "<div style='font-weight:bold'>ITEM 1A \u2014 RISK FACTOR</div>"
        f"<div>{_LONG_RISK}</div>"
        "<span class='Bold'>Item 7: Managements Discussion</span>"
        f"<div>{_LONG_MDA}</div>"
    )
    names = [s.section for s in _extract_sections(html, "acc", 1)]
    assert names == ["item_1a_risk_factors", "item_7_mda"]


def test_extract_sections_long_paragraph_mentioning_item_is_not_a_header():
    # Paragraphs over 200 chars are only headers if tagged; plain <p> is not.
    long_mention = "Item 1A. Risk Factors " + ("filler words here " * 20)
    html = _html(f"<p>{long_mention}</p><p>{_LONG_RISK}</p>")
    assert _extract_sections(html, "acc", 1) == []


_RISK_PARAGRAPHS = [
    "Demand for our sensors depends on capital spending by utilities and factories.",
    "We rely on a small number of contract manufacturers in two countries.",
    "Cyber attacks on our cloud monitoring service could expose customer data.",
    "Changes in trade policy could raise the cost of imported components.",
    "We may not be able to hire and keep enough experienced engineers.",
    "Our debt agreements limit how we can use cash and take on new borrowing.",
]


def test_extract_sections_last_section_survives_many_empty_elements():
    # Regression: empty <br> nodes count toward traversal positions but not toward
    # the text node list, so ending the last section at len(text nodes) dropped it.
    html = _html(
        "<h2>Item 1A. Risk Factors</h2>"
        + "<br>" * 30
        + "".join(f"<p>{para}</p>" for para in _RISK_PARAGRAPHS)
    )

    (section,) = _extract_sections(html, "acc", 7)

    assert section.section == "item_1a_risk_factors"
    assert section.text == "\n".join(_RISK_PARAGRAPHS)
    assert section.char_count == len(section.text)


def test_extract_sections_empty_elements_before_last_of_several_sections():
    html = _html(
        f"<h2>Item 1. Business</h2><p>{_LONG_BUSINESS}</p>"
        "<h2>Item 1A. Risk Factors</h2>"
        + "<div></div><br>" * 40
        + "".join(f"<p>{para}</p>" for para in _RISK_PARAGRAPHS)
    )
    sections = _extract_sections(html, "acc", 7)
    assert [s.section for s in sections] == ["item_1_business", "item_1a_risk_factors"]
    assert _RISK_PARAGRAPHS[-1] in sections[1].text
    assert _LONG_BUSINESS not in sections[1].text


def test_extract_sections_no_matching_headers():
    html = _html(f"<h2>Introduction</h2><p>{_LONG_RISK}</p>")
    assert _extract_sections(html, "acc", 1) == []


def _facts(entries, taxonomy="us-gaap", concept="Assets", unit="USD"):
    return {"facts": {taxonomy: {concept: {"units": {unit: entries}}}}}


def test_parse_xbrl_facts_skips_null_values_and_other_accessions():
    facts = _facts(
        [
            {"val": None, "accn": "0000320193-24-000042", "end": "2024-03-31"},
            {"val": 5, "accn": "0000320193-23-000001", "end": "2023-03-31"},
            {"val": 7, "accn": "0000320193-24-000042", "end": "2024-03-31"},
        ]
    )
    records = parse_xbrl_facts(facts, "0000320193-24-000042", 320193)
    assert [r.value for r in records] == ["7"]


def test_parse_xbrl_facts_accession_match_ignores_dashes():
    facts = _facts([{"val": 1, "accn": "0000320193-24-000042", "end": "2024-03-31"}])
    assert len(parse_xbrl_facts(facts, "000032019324000042", 1)) == 1


def test_parse_xbrl_facts_instant_fact():
    facts = _facts(
        [
            {
                "val": 352583000000,
                "accn": "acc-1",
                "end": "2023-09-30",
                "decimals": -6,
                "frame": "CY2023Q3I",
            }
        ]
    )
    (rec,) = parse_xbrl_facts(facts, "acc-1", 320193)
    assert rec.is_instant is True
    assert rec.period_start is None
    assert rec.period_end == datetime.date(2023, 9, 30)
    assert rec.decimals == "-6"
    assert rec.context_id == "CY2023Q3I"
    assert rec.concept == "us-gaap:Assets"
    assert rec.value == "352583000000"


def test_parse_xbrl_facts_duration_fact_and_context_fallback():
    facts = _facts(
        [{"val": 10.5, "accn": "acc-1", "start": "2023-01-01", "end": "2023-12-31", "fy": 2023}],
        concept="EarningsPerShareBasic",
        unit="USD/shares",
    )
    (rec,) = parse_xbrl_facts(facts, "acc-1", 1)
    assert rec.is_instant is False
    assert rec.period_start == datetime.date(2023, 1, 1)
    assert rec.period_end == datetime.date(2023, 12, 31)
    assert rec.unit == "USD/shares"
    assert rec.decimals == ""
    assert rec.context_id == "2023-"


def test_parse_xbrl_facts_bad_dates_are_suppressed():
    facts = _facts([{"val": 1, "accn": "acc-1", "start": "2023-13-01", "end": "garbage"}])
    (rec,) = parse_xbrl_facts(facts, "acc-1", 1)
    assert rec.period_start is None
    assert rec.period_end is None
    # No valid end date means it is not flagged instant.
    assert rec.is_instant is False
    assert rec.context_id == "-"


def test_parse_xbrl_facts_bad_start_with_valid_end_is_instant():
    facts = _facts([{"val": 1, "accn": "acc-1", "start": "nope", "end": "2024-01-31"}])
    (rec,) = parse_xbrl_facts(facts, "acc-1", 1)
    assert rec.is_instant is True


def test_parse_xbrl_facts_missing_accn_and_units():
    facts = {
        "facts": {
            "dei": {
                "NoUnits": {},
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [{"val": 15_000_000_000, "end": "2024-01-19"}]}
                },
            }
        }
    }
    assert parse_xbrl_facts(facts, "acc-1", 1) == []


def test_parse_xbrl_facts_multiple_taxonomies_and_units():
    year = {"accn": "a-1", "start": "2023-01-01", "end": "2023-12-31"}
    shares = [{"val": 3, "accn": "a-1", "end": "2024-01-01"}]
    facts = {
        "facts": {
            "dei": {"Shares": {"units": {"shares": shares}}},
            "us-gaap": {
                "Revenue": {
                    "units": {
                        "USD": [{"val": 1, **year}],
                        "EUR": [{"val": 2, **year}],
                    }
                }
            },
        }
    }
    records = parse_xbrl_facts(facts, "a-1", 9)
    assert sorted((r.concept, r.unit, r.value) for r in records) == [
        ("dei:Shares", "shares", "3"),
        ("us-gaap:Revenue", "EUR", "2"),
        ("us-gaap:Revenue", "USD", "1"),
    ]


def test_parse_form10k_combines_xbrl_and_sections():
    html = _html(f"<h2>Item 1A. Risk Factors</h2><p>{_LONG_RISK}</p>")
    facts = _facts([{"val": 99, "accn": "acc-x", "end": "2024-12-31"}])

    filing = parse_form10k(html, facts, "acc-x", 777)

    assert filing.accession_number == "acc-x"
    assert filing.cik == 777
    assert [f.value for f in filing.xbrl_facts] == ["99"]
    assert [s.section for s in filing.sections] == ["item_1a_risk_factors"]
    assert filing.sections[0].cik == 777


def test_parse_form10k_with_nothing():
    filing = parse_form10k(None, None, "acc-y", 1)
    assert filing.xbrl_facts == []
    assert filing.sections == []

    filing = parse_form10k("", {}, "acc-y", 1)
    assert filing.xbrl_facts == []
    assert filing.sections == []
