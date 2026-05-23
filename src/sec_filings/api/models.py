"""Pydantic response models for the API."""

import datetime

from pydantic import BaseModel


class InsiderTransactionResponse(BaseModel):
    accession_number: str
    filing_date: datetime.date
    owner_name: str
    owner_cik: int
    is_director: bool
    is_officer: bool
    officer_title: str | None
    issuer_name: str
    issuer_ticker: str | None
    security_title: str
    transaction_date: datetime.date | None
    transaction_code: str | None
    shares: float | None
    price_per_share: float | None
    shares_after: float | None
    is_derivative: bool
    is_10b5_1: bool


class HoldingResponse(BaseModel):
    filer_name: str
    filer_cik: int
    period_of_report: datetime.date
    name_of_issuer: str
    cusip: str
    ticker: str | None
    value: int
    shares: int
    investment_discretion: str | None


class HoldingChangeResponse(BaseModel):
    filer_name: str
    filer_cik: int
    period_of_report: datetime.date
    name_of_issuer: str
    cusip: str
    ticker: str | None
    current_value: int
    previous_value: int | None
    change_type: str
    value_delta: int


class ClusterBuyingSignal(BaseModel):
    issuer_ticker: str | None
    issuer_name: str
    issuer_cik: int
    distinct_insiders: int
    total_buy_value: float
    latest_filing_date: datetime.date


class ConcentrationResult(BaseModel):
    issuer_name: str
    ticker: str | None
    cik: int
    top10_holder_pct: float
    hhi: float


class RiskSimilarResult(BaseModel):
    ticker: str | None
    issuer_cik: int
    similarity: float
    chunk_preview: str


class RiskDiffResponse(BaseModel):
    issuer_cik: int
    year: int
    diffs: list[dict]
