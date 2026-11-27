"""Sentence-transformer encoder for risk-factor text chunks."""

from sentence_transformers import SentenceTransformer

from sec_filings.db import get_session
from sec_filings.models import FilingIndex, FilingSection, RiskFactorChunk

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50


def _chunk_text(
    text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP
) -> list[str]:
    """Split text into overlapping token-approximate chunks."""
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("need chunk_size > 0 and 0 <= overlap < chunk_size")
    words = text.split()
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += chunk_size - overlap
    return chunks


def encode_risk_factors(batch_size: int = 50) -> int:
    """Encode all un-embedded 10-K risk factor sections into vector chunks.

    Each chunk is tagged with the year the 10-K was filed, which is what the
    year-over-year diff step compares. Only original 10-Ks are used: a 10-Q or
    a 10-K/A in the same year would otherwise be mixed into that year.
    """
    model = SentenceTransformer(_MODEL_NAME)
    session = get_session()
    total = 0

    try:
        sections = (
            session.query(FilingSection, FilingIndex.date_filed)
            .join(FilingIndex, FilingIndex.accession_number == FilingSection.accession_number)
            .filter(FilingSection.section == "item_1a_risk_factors")
            .filter(FilingIndex.form_type == "10-K")
            .all()
        )

        for section, date_filed in sections:
            existing = (
                session.query(RiskFactorChunk)
                .filter(RiskFactorChunk.accession_number == section.accession_number)
                .first()
            )
            if existing:
                continue

            cik_val: int = section.cik
            chunks = _chunk_text(section.text)

            for i, chunk_text in enumerate(chunks):
                embedding = model.encode(chunk_text, normalize_embeddings=True)

                chunk = RiskFactorChunk(
                    accession_number=section.accession_number,
                    issuer_cik=cik_val,
                    year=date_filed.year,
                    chunk_index=i,
                    chunk_text=chunk_text,
                    embedding=embedding.tolist(),
                )
                session.add(chunk)
                total += 1

            if total % batch_size == 0:
                session.commit()

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return total


if __name__ == "__main__":
    count = encode_risk_factors()
    print(f"Encoded {count} risk factor chunks")
