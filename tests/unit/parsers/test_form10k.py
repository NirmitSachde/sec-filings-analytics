"""Tests for Form 10-K parser."""

from sec_filings.parsers.form10k import _extract_sections, parse_xbrl_facts


def test_extract_sections_empty_html():
    sections = _extract_sections("", "test-accession", 123)
    assert sections == []


def test_extract_sections_no_body():
    sections = _extract_sections("<html></html>", "test-accession", 123)
    assert sections == []


def test_extract_sections_with_risk_factors():
    html = """
    <html><body>
    <h2>Item 1. Business</h2>
    <p>We are a technology company that develops consumer electronics.</p>
    <p>Our main products include smartphones, tablets, and computers. We operate globally
    with manufacturing in several countries. Revenue is generated through hardware sales,
    services, and digital content.</p>

    <h2>Item 1A. Risk Factors</h2>
    <p>Global economic conditions could materially adversely affect our business.</p>
    <p>We face substantial competition in all our product categories. The technology industry
    is characterized by rapid change and new products are introduced frequently by competitors.
    Our ability to compete depends on our ability to innovate. Supply chain disruptions could
    impact our manufacturing capabilities significantly.</p>

    <h2>Item 7. Management's Discussion and Analysis</h2>
    <p>Revenue increased 8% year over year driven by strong iPhone sales.</p>
    <p>Services revenue grew 12% as our installed base expanded. We continue to invest in
    research and development to maintain our competitive position.</p>
    </body></html>
    """
    sections = _extract_sections(html, "test-accession", 320193)

    section_names = [s.section for s in sections]
    assert "item_1a_risk_factors" in section_names

    risk = [s for s in sections if s.section == "item_1a_risk_factors"][0]
    assert risk.char_count > 100
    assert risk.cik == 320193


def test_parse_xbrl_facts_empty():
    result = parse_xbrl_facts({}, "test-accession", 123)
    assert result == []


def test_parse_xbrl_facts_with_data():
    facts_json = {
        "facts": {
            "us-gaap": {
                "Revenue": {
                    "units": {
                        "USD": [
                            {
                                "val": 1000000,
                                "accn": "0000320193-24-000042",
                                "start": "2024-01-01",
                                "end": "2024-03-31",
                                "fy": 2024,
                                "fp": "Q1",
                            }
                        ]
                    }
                }
            }
        }
    }

    result = parse_xbrl_facts(facts_json, "0000320193-24-000042", 320193)
    assert len(result) == 1
    assert result[0].concept == "us-gaap:Revenue"
    assert result[0].value == "1000000"
    assert result[0].unit == "USD"
