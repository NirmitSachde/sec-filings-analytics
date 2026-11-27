"""Tests for the risk-factor encoder and the YoY diff summarizer.

SentenceTransformer, the Ollama client and the DB session are all mocked.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sec_filings.embeddings import diff_summarizer, encoder
from sec_filings.models import RiskFactorChunk, RiskFactorDiff


class FakeQuery:
    """Chainable stand-in for a SQLAlchemy Query with canned results."""

    def __init__(self, all_result=None, first_result=None):
        self._all = all_result if all_result is not None else []
        self._first = first_result

    def filter(self, *args, **kwargs):
        return self

    def distinct(self):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self._all

    def first(self):
        return self._first


def _session(queries):
    session = MagicMock()
    session.query.side_effect = list(queries)
    return session


def _words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


# ---------------------------------------------------------------------------
# encoder._chunk_text
# ---------------------------------------------------------------------------


def test_chunk_text_empty_and_whitespace():
    assert encoder._chunk_text("") == []
    assert encoder._chunk_text("   \n\t ") == []


def test_chunk_text_short_text_single_chunk_normalizes_whitespace():
    assert encoder._chunk_text("alpha  beta\n gamma") == ["alpha beta gamma"]


def test_chunk_text_exact_chunk_size_is_one_chunk():
    text = _words(500)
    chunks = encoder._chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_small_window_overlap():
    chunks = encoder._chunk_text(_words(10), chunk_size=4, overlap=1)
    assert chunks == [
        "w0 w1 w2 w3",
        "w3 w4 w5 w6",
        "w6 w7 w8 w9",
    ]


def test_chunk_text_zero_overlap_partitions_words():
    chunks = encoder._chunk_text(_words(7), chunk_size=3, overlap=0)
    assert chunks == ["w0 w1 w2", "w3 w4 w5", "w6"]


def test_chunk_text_default_params_overlap_and_coverage():
    words = _words(1000).split()
    chunks = encoder._chunk_text(" ".join(words))

    # Starts at 0, 450, 900 with the default 500/50 window.
    assert len(chunks) == 3
    split = [c.split() for c in chunks]
    assert [len(c) for c in split] == [500, 500, 100]
    assert split[0][0] == "w0"
    assert split[1][0] == "w450"
    assert split[2][0] == "w900"
    assert split[2][-1] == "w999"
    for prev, nxt in zip(split, split[1:], strict=False):
        assert prev[-encoder._CHUNK_OVERLAP :] == nxt[: encoder._CHUNK_OVERLAP]
    # Every word appears in at least one chunk.
    assert set(words) == {w for c in split for w in c}


def test_chunk_text_no_trailing_duplicate_chunk():
    # 950 words: second window ends exactly at the end, so no third chunk.
    chunks = encoder._chunk_text(_words(950))
    assert len(chunks) == 2
    assert chunks[-1].split()[-1] == "w949"


# ---------------------------------------------------------------------------
# encoder.encode_risk_factors
# ---------------------------------------------------------------------------


class FakeVector:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return list(self._values)


@pytest.fixture
def fake_model(monkeypatch):
    model = MagicMock()
    model.encode.side_effect = lambda text, normalize_embeddings: FakeVector(
        [float(len(text.split())), 1.0]
    )
    ctor = MagicMock(return_value=model)
    monkeypatch.setattr(encoder, "SentenceTransformer", ctor)
    return ctor, model


def test_encode_risk_factors_chunks_and_skips_existing(monkeypatch, fake_model):
    ctor, model = fake_model
    done = SimpleNamespace(accession_number="0000000001-24-000001", cik=1, text="old")
    fresh = SimpleNamespace(accession_number="0000320193-24-000123", cik=320193, text=_words(1000))
    session = _session(
        [
            FakeQuery(all_result=[done, fresh]),
            FakeQuery(first_result=object()),  # done already has chunks
            FakeQuery(first_result=None),  # fresh has none
        ]
    )
    monkeypatch.setattr(encoder, "get_session", lambda: session)

    total = encoder.encode_risk_factors()

    assert total == 3
    ctor.assert_called_once_with("BAAI/bge-small-en-v1.5")
    assert model.encode.call_count == 3
    for call in model.encode.call_args_list:
        assert call.kwargs == {"normalize_embeddings": True}

    added = [c.args[0] for c in session.add.call_args_list]
    assert len(added) == 3
    assert all(isinstance(c, RiskFactorChunk) for c in added)
    assert [c.chunk_index for c in added] == [0, 1, 2]
    assert {c.accession_number for c in added} == {"0000320193-24-000123"}
    assert {c.issuer_cik for c in added} == {320193}
    assert added[0].chunk_text.split()[0] == "w0"
    assert added[1].chunk_text.split()[0] == "w450"
    assert [c.embedding for c in added] == [[500.0, 1.0], [500.0, 1.0], [100.0, 1.0]]
    # Year is not derived from the filing yet (see report).
    assert {c.year for c in added} == {0}

    session.rollback.assert_not_called()
    session.close.assert_called_once()
    assert session.commit.call_count >= 1


def test_encode_risk_factors_batch_commit(monkeypatch, fake_model):
    sections = [
        SimpleNamespace(accession_number=f"acc-{i}", cik=i, text=_words(10)) for i in range(4)
    ]
    session = _session(
        [FakeQuery(all_result=sections)] + [FakeQuery(first_result=None) for _ in sections]
    )
    monkeypatch.setattr(encoder, "get_session", lambda: session)

    total = encoder.encode_risk_factors(batch_size=2)

    assert total == 4
    # Commits after sections 2 and 4 (total hits a multiple of 2), then the final commit.
    assert session.commit.call_count == 3


def test_encode_risk_factors_no_sections(monkeypatch, fake_model):
    _, model = fake_model
    session = _session([FakeQuery(all_result=[])])
    monkeypatch.setattr(encoder, "get_session", lambda: session)

    assert encoder.encode_risk_factors() == 0
    model.encode.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_called_once()
    session.close.assert_called_once()


def test_encode_risk_factors_rolls_back_on_error(monkeypatch, fake_model):
    _, model = fake_model
    model.encode.side_effect = RuntimeError("encode failed")
    section = SimpleNamespace(accession_number="a", cik=1, text="some risk text")
    session = _session([FakeQuery(all_result=[section]), FakeQuery(first_result=None)])
    monkeypatch.setattr(encoder, "get_session", lambda: session)

    with pytest.raises(RuntimeError, match="encode failed"):
        encoder.encode_risk_factors()
    session.rollback.assert_called_once()
    session.commit.assert_not_called()
    session.close.assert_called_once()


# ---------------------------------------------------------------------------
# diff_summarizer._summarize_pair
# ---------------------------------------------------------------------------


def _ollama_reply(content):
    return {"message": {"content": content}}


def test_summarize_pair_parses_structured_reply(monkeypatch):
    chat = MagicMock(
        return_value=_ollama_reply(
            "NEW:  Added cybersecurity risk.  \n"
            "DROPPED: Removed pandemic language.\n"
            "SENTIMENT: more cautionary\n"
        )
    )
    monkeypatch.setattr(diff_summarizer.ollama_client, "chat", chat)

    result = diff_summarizer._summarize_pair("old text", "new text", model="tiny-model")

    assert result == {
        "new": "Added cybersecurity risk.",
        "dropped": "Removed pandemic language.",
        "sentiment": "more cautionary",
    }
    kwargs = chat.call_args.kwargs
    assert kwargs["model"] == "tiny-model"
    messages = kwargs["messages"]
    assert messages[0]["role"] == "user"
    assert "PREVIOUS YEAR:\nold text" in messages[0]["content"]
    assert "CURRENT YEAR:\nnew text" in messages[0]["content"]


def test_summarize_pair_default_model_and_truncation(monkeypatch):
    chat = MagicMock(return_value=_ollama_reply("NEW: a\nDROPPED: b\nSENTIMENT: similar"))
    monkeypatch.setattr(diff_summarizer.ollama_client, "chat", chat)

    prev = "P" * 2500
    curr = "C" * 3000
    result = diff_summarizer._summarize_pair(prev, curr)

    assert result == {"new": "a", "dropped": "b", "sentiment": "similar"}
    assert chat.call_args.kwargs["model"] == "llama3.1:8b-instruct-q4_K_M"
    prompt = chat.call_args.kwargs["messages"][0]["content"]
    assert "P" * 2000 in prompt
    assert "P" * 2001 not in prompt
    assert "C" * 2000 in prompt
    assert "C" * 2001 not in prompt


def test_summarize_pair_tolerates_preamble(monkeypatch):
    reply = "Sure, here you go:\nNEW: x\nDROPPED: y\nSENTIMENT: more confident"
    monkeypatch.setattr(
        diff_summarizer.ollama_client, "chat", MagicMock(return_value=_ollama_reply(reply))
    )
    assert diff_summarizer._summarize_pair("a", "b") == {
        "new": "x",
        "dropped": "y",
        "sentiment": "more confident",
    }


def test_summarize_pair_unparseable_reply_returns_none(monkeypatch):
    monkeypatch.setattr(
        diff_summarizer.ollama_client,
        "chat",
        MagicMock(return_value=_ollama_reply("The risks look about the same.")),
    )
    assert diff_summarizer._summarize_pair("a", "b") is None


def test_summarize_pair_client_error_returns_none(monkeypatch):
    monkeypatch.setattr(
        diff_summarizer.ollama_client,
        "chat",
        MagicMock(side_effect=ConnectionError("ollama not running")),
    )
    assert diff_summarizer._summarize_pair("a", "b") is None


def test_summarize_pair_malformed_response_shape_returns_none(monkeypatch):
    monkeypatch.setattr(diff_summarizer.ollama_client, "chat", MagicMock(return_value={}))
    assert diff_summarizer._summarize_pair("a", "b") is None


# ---------------------------------------------------------------------------
# diff_summarizer.generate_diffs
# ---------------------------------------------------------------------------


def _chunks(*texts):
    return [SimpleNamespace(chunk_text=t) for t in texts]


def test_generate_diffs_walks_consecutive_years(monkeypatch):
    summary = {"new": "n", "dropped": "d", "sentiment": "similar"}
    summarize = MagicMock(return_value=summary)
    monkeypatch.setattr(diff_summarizer, "_summarize_pair", summarize)

    session = _session(
        [
            FakeQuery(all_result=[(100,), (200,), (300,)]),
            # issuer 100: years 2022, 2023, 2024
            FakeQuery(all_result=[(2022,), (2023,), (2024,)]),
            FakeQuery(first_result=object()),  # 2023 diff already exists, skipped
            FakeQuery(first_result=None),  # 2024 diff missing
            FakeQuery(all_result=_chunks("prev one", "prev two")),
            FakeQuery(all_result=_chunks("curr one")),
            # issuer 200: one year only, nothing to compare
            FakeQuery(all_result=[(2024,)]),
            # issuer 300: current year has no chunks
            FakeQuery(all_result=[(2023,), (2024,)]),
            FakeQuery(first_result=None),
            FakeQuery(all_result=_chunks("prev only")),
            FakeQuery(all_result=[]),
        ]
    )
    monkeypatch.setattr(diff_summarizer, "get_session", lambda: session)

    total = diff_summarizer.generate_diffs()

    assert total == 1
    summarize.assert_called_once_with("prev one prev two", "curr one")
    added = [c.args[0] for c in session.add.call_args_list]
    assert len(added) == 1
    rec = added[0]
    assert isinstance(rec, RiskFactorDiff)
    assert rec.issuer_cik == 100
    assert rec.year == 2024
    assert json.loads(rec.diff_json) == [summary]
    # One commit per issuer.
    assert session.commit.call_count == 3
    session.rollback.assert_not_called()
    session.close.assert_called_once()


def test_generate_diffs_summary_failure_adds_nothing(monkeypatch):
    monkeypatch.setattr(diff_summarizer, "_summarize_pair", MagicMock(return_value=None))
    session = _session(
        [
            FakeQuery(all_result=[(1,)]),
            FakeQuery(all_result=[(2023,), (2024,)]),
            FakeQuery(first_result=None),
            FakeQuery(all_result=_chunks("a")),
            FakeQuery(all_result=_chunks("b")),
        ]
    )
    monkeypatch.setattr(diff_summarizer, "get_session", lambda: session)

    assert diff_summarizer.generate_diffs() == 0
    session.add.assert_not_called()
    session.commit.assert_called_once()


def test_generate_diffs_no_issuers(monkeypatch):
    summarize = MagicMock()
    monkeypatch.setattr(diff_summarizer, "_summarize_pair", summarize)
    session = _session([FakeQuery(all_result=[])])
    monkeypatch.setattr(diff_summarizer, "get_session", lambda: session)

    assert diff_summarizer.generate_diffs() == 0
    summarize.assert_not_called()
    session.commit.assert_not_called()
    session.close.assert_called_once()


def test_generate_diffs_rolls_back_and_reraises(monkeypatch):
    session = MagicMock()
    session.query.side_effect = RuntimeError("query failed")
    monkeypatch.setattr(diff_summarizer, "get_session", lambda: session)

    with pytest.raises(RuntimeError, match="query failed"):
        diff_summarizer.generate_diffs()
    session.rollback.assert_called_once()
    session.close.assert_called_once()
