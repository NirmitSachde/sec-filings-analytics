"""Pydantic models for parsed filing data."""

import datetime

from pydantic import BaseModel, Field


class Form4Transaction(BaseModel):
    accession_number: str
    filing_date: datetime.date
    transaction_index: int

    owner_cik: int
    owner_name: str
    is_director: bool = False
    is_officer: bool = False
    is_ten_percent_owner: bool = False
    is_other: bool = False
    officer_title: str | None = None

    issuer_cik: int
    issuer_name: str
    issuer_ticker: str | None = None

    security_title: str
    transaction_date: datetime.date | None = None
    transaction_code: str | None = None
    shares: float | None = None
    price_per_share: float | None = None
    shares_after: float | None = None
    direct_or_indirect: str | None = None
    is_derivative: bool = False
    is_10b5_1: bool = False


class Form4Filing(BaseModel):
    accession_number: str
    transactions: list[Form4Transaction]


class Form13FHolding(BaseModel):
    name_of_issuer: str
    cusip: str = Field(min_length=9, max_length=9)
    value: int
    shares: int
    share_type: str
    investment_discretion: str | None = None
    voting_sole: int | None = None
    voting_shared: int | None = None
    voting_none: int | None = None
    ticker: str | None = None


class Form13FFiling(BaseModel):
    accession_number: str
    filer_cik: int
    filer_name: str
    period_of_report: datetime.date
    holdings: list[Form13FHolding]


class XbrlFactRecord(BaseModel):
    accession_number: str
    cik: int
    concept: str
    value: str
    unit: str | None = None
    decimals: str | None = None
    period_start: datetime.date | None = None
    period_end: datetime.date | None = None
    context_id: str
    is_instant: bool = False


class FilingSectionRecord(BaseModel):
    accession_number: str
    cik: int
    section: str
    text: str
    char_count: int


class Form10KFiling(BaseModel):
    accession_number: str
    cik: int
    xbrl_facts: list[XbrlFactRecord]
    sections: list[FilingSectionRecord]
