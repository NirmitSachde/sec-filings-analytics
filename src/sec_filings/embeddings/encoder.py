"""Sentence-transformer encoder for risk-factor text chunks."""

from sentence_transformers import SentenceTransformer

from sec_filings.db import get_session
from sec_filings.models import FilingSection, RiskFactorChunk

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50


def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping token-approximate chunks."""
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
    """Encode all un-embedded risk factor sections into vector chunks."""
    model = SentenceTransformer(_MODEL_NAME)
    session = get_session()
    total = 0

    try:
        sections = (
            session.query(FilingSection)
            .filter(FilingSection.section == "item_1a_risk_factors")
            .all()
        )

        for section in sections:
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
                    year=0,
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
