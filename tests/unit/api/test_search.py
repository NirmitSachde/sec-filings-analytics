"""Tests for the semantic search and risk-factor diff endpoints."""

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from sec_filings.api.main import app
from sec_filings.api.routes import search
from tests.unit.api.fakes import FakeQuery, FakeSession

client = TestClient(app)


@pytest.fixture
def install(monkeypatch):
    def _install(session):
        monkeypatch.setattr(search, "get_session", lambda: session)
        return session

    return _install


# --- _get_model -----------------------------------------------------------------


def test_get_model_loads_once_and_caches(monkeypatch):
    fake_cls = MagicMock(name="SentenceTransformer")
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = fake_cls
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr(search, "_model", None)

    first = search._get_model()
    second = search._get_model()

    assert first is second is fake_cls.return_value
    fake_cls.assert_called_once_with("BAAI/bge-small-en-v1.5")


def test_get_model_returns_existing_without_import(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(search, "_model", sentinel)
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # import would fail
    assert search._get_model() is sentinel


# --- /search/risk-similar/{ticker} -----------------------------------------------


def test_risk_similar_unknown_ticker(install):
    q = FakeQuery(first=None)
    session = install(FakeSession([q]))

    resp = client.get("/search/risk-similar/zzzz")

    assert resp.status_code == 200
    assert resp.json() == []
    assert q.rendered_filters() == ["ref.ticker_cik.ticker = 'ZZZZ'"]
    assert session.executed == []
    assert session.closed


@pytest.mark.parametrize("chunk", [None, SimpleNamespace(embedding=None)])
def test_risk_similar_without_embedding(install, chunk):
    mapping = SimpleNamespace(cik=320193)
    chunk_q = FakeQuery(first=chunk)
    session = install(FakeSession([FakeQuery(first=mapping), chunk_q]))

    resp = client.get("/search/risk-similar/AAPL")

    assert resp.status_code == 200
    assert resp.json() == []
    assert chunk_q.rendered_filters() == ["vec.risk_factor_chunks.issuer_cik = 320193"]
    assert chunk_q.rendered_order_bys() == [
        "vec.risk_factor_chunks.year DESC",
        "vec.risk_factor_chunks.chunk_index",
    ]
    assert session.executed == []
    assert session.closed


def test_risk_similar_returns_deduped_neighbours(install):
    mapping = SimpleNamespace(cik=320193)
    chunk = SimpleNamespace(embedding=[0.25, -0.5, 1.0])
    long_text = "risk " * 100
    rows = [
        SimpleNamespace(issuer_cik=789019, chunk_text=long_text, similarity=0.912345),
        SimpleNamespace(issuer_cik=789019, chunk_text="dup", similarity=0.9),
        SimpleNamespace(issuer_cik=55, chunk_text="short text", similarity="0.5"),
    ]
    msft_q = FakeQuery(first=SimpleNamespace(ticker="MSFT"))
    unknown_q = FakeQuery(first=None)
    session = install(
        FakeSession(
            [FakeQuery(first=mapping), FakeQuery(first=chunk), msft_q, unknown_q],
            execute_rows=rows,
        )
    )

    resp = client.get("/search/risk-similar/aapl", params={"top_k": 7})

    assert resp.status_code == 200
    assert resp.json() == [
        {
            "ticker": "MSFT",
            "issuer_cik": 789019,
            "similarity": 0.9123,
            "chunk_preview": long_text[:200],
        },
        {"ticker": None, "issuer_cik": 55, "similarity": 0.5, "chunk_preview": "short text"},
    ]
    # One ticker lookup per distinct CIK, not per row.
    assert len(session.queries) == 4
    assert msft_q.rendered_filters() == ["ref.ticker_cik.cik = 789019"]
    assert unknown_q.rendered_filters() == ["ref.ticker_cik.cik = 55"]

    (statement, params), *_ = session.executed
    assert params == {"embedding": "[0.25,-0.5,1.0]", "exclude_cik": 320193, "top_k": 7}
    sql = str(statement)
    assert "FROM vec.risk_factor_chunks" in sql
    assert "issuer_cik != :exclude_cik" in sql
    assert "LIMIT :top_k" in sql
    assert session.closed


def test_risk_similar_sql_binds_embedding(install):
    session = install(
        FakeSession(
            [
                FakeQuery(first=SimpleNamespace(cik=1)),
                FakeQuery(first=SimpleNamespace(embedding=[0.1])),
            ],
            execute_rows=[],
        )
    )
    client.get("/search/risk-similar/AAPL")
    statement, _ = session.executed[0]
    assert "embedding" in statement._bindparams


def test_risk_similar_top_k_validation(install):
    session = install(FakeSession([]))
    resp = client.get("/search/risk-similar/AAPL", params={"top_k": 51})
    assert resp.status_code == 422
    assert session.queries == []


# --- /search/diffs/{ticker}/{year} ------------------------------------------------


def test_diffs_unknown_ticker(install):
    q = FakeQuery(first=None)
    session = install(FakeSession([q]))

    resp = client.get("/search/diffs/nope/2024")

    assert resp.status_code == 200
    assert resp.json() == {"issuer_cik": 0, "year": 2024, "diffs": []}
    assert q.rendered_filters() == ["ref.ticker_cik.ticker = 'NOPE'"]
    assert session.closed


def test_diffs_missing_year(install):
    diff_q = FakeQuery(first=None)
    session = install(FakeSession([FakeQuery(first=SimpleNamespace(cik=320193)), diff_q]))

    resp = client.get("/search/diffs/AAPL/2023")

    assert resp.status_code == 200
    assert resp.json() == {"issuer_cik": 320193, "year": 2023, "diffs": []}
    assert diff_q.rendered_filters() == [
        "mart.risk_factor_diffs.issuer_cik = 320193",
        "mart.risk_factor_diffs.year = 2023",
    ]
    assert session.closed


def test_diffs_returns_parsed_json(install):
    diffs = [
        {"type": "added", "summary": "New AI regulation risk"},
        {"type": "removed", "summary": "Pandemic supply chain risk"},
    ]
    record = SimpleNamespace(diff_json=json.dumps(diffs))
    session = install(
        FakeSession([FakeQuery(first=SimpleNamespace(cik=320193)), FakeQuery(first=record)])
    )

    resp = client.get("/search/diffs/aapl/2024")

    assert resp.status_code == 200
    assert resp.json() == {"issuer_cik": 320193, "year": 2024, "diffs": diffs}
    assert session.closed


def test_diffs_year_must_be_int(install):
    session = install(FakeSession([]))
    resp = client.get("/search/diffs/AAPL/latest")
    assert resp.status_code == 422
    assert session.queries == []


def test_diffs_session_closed_on_bad_json(install):
    record = SimpleNamespace(diff_json="{not json")
    session = install(
        FakeSession([FakeQuery(first=SimpleNamespace(cik=1)), FakeQuery(first=record)])
    )
    with pytest.raises(json.JSONDecodeError):
        client.get("/search/diffs/AAPL/2024")
    assert session.closed
