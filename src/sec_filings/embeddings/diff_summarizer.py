"""Year-over-year risk-factor diff summarizer using local Ollama."""

import json
import re

import ollama as ollama_client

from sec_filings.config import get_settings
from sec_filings.db import get_session
from sec_filings.models import RiskFactorChunk, RiskFactorDiff

_DIFF_PROMPT = """Compare these two risk factor excerpts from consecutive years of the same company's 10-K filing.

PREVIOUS YEAR:
{prev_text}

CURRENT YEAR:
{curr_text}

Respond ONLY in this exact format:
NEW: <what's new this year, one sentence>
DROPPED: <what was dropped from last year, one sentence>
SENTIMENT: <more cautionary | similar | more confident>
"""

_DIFF_RE = re.compile(
    r"NEW:\s*(.+?)\n"
    r"DROPPED:\s*(.+?)\n"
    r"SENTIMENT:\s*(.+)",
    re.DOTALL,
)


def _summarize_pair(prev_text: str, curr_text: str, model: str = "llama3.1:8b-instruct-q4_K_M") -> dict | None:
    """Call local Ollama to summarize a chunk pair diff."""
    settings = get_settings()

    prompt = _DIFF_PROMPT.format(prev_text=prev_text[:2000], curr_text=curr_text[:2000])

    try:
        response = ollama_client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response["message"]["content"]

        match = _DIFF_RE.search(text)
        if match:
            return {
                "new": match.group(1).strip(),
                "dropped": match.group(2).strip(),
                "sentiment": match.group(3).strip(),
            }
    except Exception:
        pass

    return None


def generate_diffs(min_similarity: float = 0.5, max_similarity: float = 0.85) -> int:
    """Generate year-over-year risk factor diff summaries for all issuers."""
    session = get_session()
    total = 0

    try:
        issuers = (
            session.query(RiskFactorChunk.issuer_cik)
            .distinct()
            .all()
        )

        for (issuer_cik,) in issuers:
            years = (
                session.query(RiskFactorChunk.year)
                .filter(RiskFactorChunk.issuer_cik == issuer_cik)
                .distinct()
                .order_by(RiskFactorChunk.year)
                .all()
            )
            year_list = [y[0] for y in years]

            for i in range(1, len(year_list)):
                prev_year = year_list[i - 1]
                curr_year = year_list[i]

                existing = (
                    session.query(RiskFactorDiff)
                    .filter(
                        RiskFactorDiff.issuer_cik == issuer_cik,
                        RiskFactorDiff.year == curr_year,
                    )
                    .first()
                )
                if existing:
                    continue

                prev_chunks = (
                    session.query(RiskFactorChunk)
                    .filter(
                        RiskFactorChunk.issuer_cik == issuer_cik,
                        RiskFactorChunk.year == prev_year,
                    )
                    .order_by(RiskFactorChunk.chunk_index)
                    .all()
                )
                curr_chunks = (
                    session.query(RiskFactorChunk)
                    .filter(
                        RiskFactorChunk.issuer_cik == issuer_cik,
                        RiskFactorChunk.year == curr_year,
                    )
                    .order_by(RiskFactorChunk.chunk_index)
                    .all()
                )

                diffs: list[dict] = []
                prev_text = " ".join(c.chunk_text for c in prev_chunks)
                curr_text = " ".join(c.chunk_text for c in curr_chunks)

                if prev_text and curr_text:
                    result = _summarize_pair(prev_text, curr_text)
                    if result:
                        diffs.append(result)

                if diffs:
                    diff_record = RiskFactorDiff(
                        issuer_cik=issuer_cik,
                        year=curr_year,
                        diff_json=json.dumps(diffs),
                    )
                    session.add(diff_record)
                    total += 1

            session.commit()

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return total


if __name__ == "__main__":
    count = generate_diffs()
    print(f"Generated {count} risk factor diffs")
