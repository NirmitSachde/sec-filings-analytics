"""SQLAlchemy ORM models for all database tables."""

import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from sec_filings.db import Base


class FilingIndex(Base):
    __tablename__ = "filing_index"
    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_filing_index_accession"),
        {"schema": "raw"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    form_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    cik: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    date_filed: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    fetched_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    parsed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InsiderTransaction(Base):
    __tablename__ = "insider_transactions"
    __table_args__ = (
        UniqueConstraint(
            "accession_number", "transaction_index", name="uq_insider_tx_accession_idx"
        ),
        {"schema": "raw"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    filing_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    transaction_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Reporting owner
    owner_cik: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    owner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_director: Mapped[bool] = mapped_column(Boolean, default=False)
    is_officer: Mapped[bool] = mapped_column(Boolean, default=False)
    is_ten_percent_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    is_other: Mapped[bool] = mapped_column(Boolean, default=False)
    officer_title: Mapped[str | None] = mapped_column(String(200))

    # Issuer
    issuer_cik: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    issuer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer_ticker: Mapped[str | None] = mapped_column(String(20), index=True)

    # Transaction details
    security_title: Mapped[str] = mapped_column(String(200), nullable=False)
    transaction_date: Mapped[datetime.date | None] = mapped_column(Date)
    transaction_code: Mapped[str | None] = mapped_column(String(5))
    shares: Mapped[float | None] = mapped_column(Float)
    price_per_share: Mapped[float | None] = mapped_column(Float)
    shares_after: Mapped[float | None] = mapped_column(Float)
    direct_or_indirect: Mapped[str | None] = mapped_column(String(1))
    is_derivative: Mapped[bool] = mapped_column(Boolean, default=False)
    is_10b5_1: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HoldingsPosition(Base):
    __tablename__ = "holdings_positions"
    __table_args__ = (
        UniqueConstraint(
            "accession_number", "cusip", "name_of_issuer", name="uq_holdings_pos"
        ),
        {"schema": "raw"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    filer_cik: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    filer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    period_of_report: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)

    name_of_issuer: Mapped[str] = mapped_column(String(200), nullable=False)
    cusip: Mapped[str] = mapped_column(String(9), nullable=False, index=True)
    ticker: Mapped[str | None] = mapped_column(String(20), index=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    share_type: Mapped[str] = mapped_column(String(10), nullable=False)
    investment_discretion: Mapped[str | None] = mapped_column(String(10))
    voting_sole: Mapped[int | None] = mapped_column(BigInteger)
    voting_shared: Mapped[int | None] = mapped_column(BigInteger)
    voting_none: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class XbrlFact(Base):
    __tablename__ = "xbrl_facts"
    __table_args__ = (
        UniqueConstraint(
            "accession_number", "concept", "period_start", "period_end", "context_id",
            name="uq_xbrl_fact",
        ),
        {"schema": "raw"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    cik: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    concept: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    decimals: Mapped[str | None] = mapped_column(String(20))
    period_start: Mapped[datetime.date | None] = mapped_column(Date)
    period_end: Mapped[datetime.date | None] = mapped_column(Date)
    context_id: Mapped[str] = mapped_column(String(200), nullable=False)
    is_instant: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FilingSection(Base):
    __tablename__ = "filing_sections"
    __table_args__ = (
        UniqueConstraint("accession_number", "section", name="uq_filing_section"),
        {"schema": "raw"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    cik: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    section: Mapped[str] = mapped_column(String(50), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ParseFailure(Base):
    __tablename__ = "parse_failures"
    __table_args__ = {"schema": "raw"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    form_type: Mapped[str] = mapped_column(String(20), nullable=False)
    exception_class: Mapped[str] = mapped_column(String(200), nullable=False)
    traceback: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(20), nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TickerCik(Base):
    __tablename__ = "ticker_cik"
    __table_args__ = (
        UniqueConstraint("cik", "ticker", name="uq_ticker_cik"),
        {"schema": "ref"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cik: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(20))

    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TickerOverride(Base):
    __tablename__ = "ticker_overrides"
    __table_args__ = {"schema": "ref"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cusip: Mapped[str | None] = mapped_column(String(9), index=True)
    cik: Mapped[int | None] = mapped_column(Integer, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class RiskFactorChunk(Base):
    __tablename__ = "risk_factor_chunks"
    __table_args__ = (
        Index("ix_risk_factor_embedding", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        {"schema": "vec"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    issuer_cik: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(384))

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RiskFactorDiff(Base):
    __tablename__ = "risk_factor_diffs"
    __table_args__ = (
        UniqueConstraint("issuer_cik", "year", name="uq_risk_diff_cik_year"),
        {"schema": "mart"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issuer_cik: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    diff_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
