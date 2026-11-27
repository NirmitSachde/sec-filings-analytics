"""Tests for the database helpers and ORM model definitions (no live database)."""

import datetime
from unittest.mock import MagicMock

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Session

from sec_filings import db, models
from sec_filings.config import get_settings

# --- db.py --------------------------------------------------------------------


@pytest.fixture
def fresh_db(monkeypatch):
    """Reset the module-level singletons so each test starts cold."""
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    return db


def test_get_engine_creates_once_with_settings_url(fresh_db, monkeypatch):
    fake_engine = MagicMock(name="engine")
    create = MagicMock(return_value=fake_engine)
    monkeypatch.setattr(fresh_db, "create_engine", create)

    first = fresh_db.get_engine()
    second = fresh_db.get_engine()

    assert first is second is fake_engine
    create.assert_called_once_with(get_settings().database_url, pool_pre_ping=True, pool_size=10)
    url = create.call_args.args[0]
    assert url.startswith("postgresql+psycopg://")


def test_get_engine_real_engine_is_lazy(fresh_db):
    # create_engine does not connect, so this is safe without a database.
    engine = fresh_db.get_engine()
    assert engine.dialect.name == "postgresql"
    assert engine.url.database == get_settings().postgres_db
    assert fresh_db.get_engine() is engine
    engine.dispose()


def test_get_session_factory_binds_engine_and_caches(fresh_db, monkeypatch):
    fake_engine = MagicMock(name="engine")
    monkeypatch.setattr(fresh_db, "get_engine", lambda: fake_engine)
    maker = MagicMock(name="sessionmaker")
    monkeypatch.setattr(fresh_db, "sessionmaker", maker)

    first = fresh_db.get_session_factory()
    second = fresh_db.get_session_factory()

    assert first is second is maker.return_value
    maker.assert_called_once_with(bind=fake_engine)


def test_get_session_returns_new_session_from_factory(fresh_db, monkeypatch):
    factory = MagicMock(name="factory", side_effect=[object(), object()])
    monkeypatch.setattr(fresh_db, "get_session_factory", lambda: factory)

    s1 = fresh_db.get_session()
    s2 = fresh_db.get_session()

    assert s1 is not s2
    assert factory.call_count == 2


def test_get_session_real_session_without_connecting(fresh_db):
    session = fresh_db.get_session()
    try:
        assert isinstance(session, Session)
        assert session.get_bind() is fresh_db.get_engine()
    finally:
        session.close()
        fresh_db.get_engine().dispose()


# --- models.py ------------------------------------------------------------------

EXPECTED_TABLES = {
    models.FilingIndex: "raw.filing_index",
    models.InsiderTransaction: "raw.insider_transactions",
    models.HoldingsPosition: "raw.holdings_positions",
    models.XbrlFact: "raw.xbrl_facts",
    models.FilingSection: "raw.filing_sections",
    models.ParseFailure: "raw.parse_failures",
    models.TickerCik: "ref.ticker_cik",
    models.TickerOverride: "ref.ticker_overrides",
    models.RiskFactorChunk: "vec.risk_factor_chunks",
    models.RiskFactorDiff: "mart.risk_factor_diffs",
    models.DailyPrice: "raw.daily_prices",
    models.SecurityMaster: "raw.security_master",
}


@pytest.mark.parametrize(("model", "fullname"), list(EXPECTED_TABLES.items()))
def test_model_table_names_and_schemas(model, fullname):
    assert model.__table__.fullname == fullname
    assert db.Base.metadata.tables[fullname] is model.__table__


def test_metadata_has_every_model():
    assert set(EXPECTED_TABLES.values()) <= set(db.Base.metadata.tables)


def _unique_constraints(model):
    return {
        c.name: tuple(col.name for col in c.columns)
        for c in model.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }


@pytest.mark.parametrize(
    ("model", "name", "columns"),
    [
        (models.FilingIndex, "uq_filing_index_accession", ("accession_number",)),
        (
            models.InsiderTransaction,
            "uq_insider_tx_accession_idx",
            ("accession_number", "transaction_index"),
        ),
        (
            models.HoldingsPosition,
            "uq_holdings_pos",
            ("accession_number", "cusip", "name_of_issuer"),
        ),
        (
            models.XbrlFact,
            "uq_xbrl_fact",
            ("accession_number", "concept", "period_start", "period_end", "context_id"),
        ),
        (models.FilingSection, "uq_filing_section", ("accession_number", "section")),
        (models.TickerCik, "uq_ticker_cik", ("cik", "ticker")),
        (models.RiskFactorDiff, "uq_risk_diff_cik_year", ("issuer_cik", "year")),
    ],
)
def test_unique_constraints(model, name, columns):
    assert _unique_constraints(model)[name] == columns


@pytest.mark.parametrize(
    ("model", "pk"),
    [
        (models.FilingIndex, ("id",)),
        (models.InsiderTransaction, ("id",)),
        (models.TickerCik, ("id",)),
        (models.DailyPrice, ("ticker", "date")),
        (models.SecurityMaster, ("ticker",)),
    ],
)
def test_primary_keys(model, pk):
    assert tuple(c.name for c in model.__table__.primary_key.columns) == pk


def test_insider_transaction_nullability_and_defaults():
    cols = models.InsiderTransaction.__table__.c
    for required in ("accession_number", "filing_date", "owner_cik", "issuer_cik"):
        assert cols[required].nullable is False
    for optional in ("issuer_ticker", "transaction_code", "shares", "price_per_share"):
        assert cols[optional].nullable is True
    for flag in ("is_director", "is_officer", "is_derivative", "is_10b5_1"):
        assert cols[flag].default.arg is False
    assert cols["created_at"].server_default is not None


def test_holdings_position_columns():
    cols = models.HoldingsPosition.__table__.c
    assert cols["cusip"].type.length == 9
    assert cols["value"].nullable is False
    assert cols["ticker"].nullable is True
    assert cols["period_of_report"].index is True


def test_risk_factor_chunk_vector_and_hnsw_index():
    table = models.RiskFactorChunk.__table__
    emb_type = table.c["embedding"].type
    assert isinstance(emb_type, Vector)
    assert emb_type.dim == 384
    idx = next(i for i in table.indexes if i.name == "ix_risk_factor_embedding")
    pg_opts = idx.dialect_options["postgresql"]
    assert pg_opts["using"] == "hnsw"
    assert pg_opts["with"] == {"m": 16, "ef_construction": 64}
    assert pg_opts["ops"] == {"embedding": "vector_cosine_ops"}


def test_ticker_cik_updated_at_has_onupdate():
    col = models.TickerCik.__table__.c["updated_at"]
    assert col.onupdate is not None
    assert col.server_default is not None


def test_security_master_default_active():
    assert models.SecurityMaster.__table__.c["is_active"].default.arg is True


def test_models_construct_without_database():
    tx = models.InsiderTransaction(
        accession_number="0000320193-24-000001",
        filing_date=datetime.date(2024, 3, 1),
        transaction_index=0,
        owner_cik=1,
        owner_name="Doe John",
        issuer_cik=320193,
        issuer_name="Apple Inc.",
        security_title="Common Stock",
    )
    assert tx.issuer_cik == 320193
    assert tx.shares is None

    price = models.DailyPrice(ticker="AAPL", date=datetime.date(2024, 1, 2), close=185.6)
    assert price.close == 185.6
    assert price.adj_close is None

    chunk = models.RiskFactorChunk(
        accession_number="a", issuer_cik=1, year=2024, chunk_index=0, chunk_text="t"
    )
    assert chunk.embedding is None
