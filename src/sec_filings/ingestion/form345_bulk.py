"""Bulk backfill of Form 4 transactions from the SEC's quarterly insider data sets.

Source: https://www.sec.gov/dera/data/form-345 (one zip per quarter, tab-separated
SUBMISSION / REPORTINGOWNER / NONDERIV_TRANS / DERIV_TRANS tables). Downloading
~50 zips is far cheaper than crawling millions of individual Form 4 XML files at
the 10 req/s EDGAR ceiling, and the SEC builds these tables from the same filings.

Loading rules (kept deliberately conservative for the backtest):
- Original Form 4 filings only. 4/A amendments, Form 3 and Form 5 are skipped so a
  transaction is never counted twice.
- One reporting owner per filing. Joint filings (a fund and its affiliates filing
  together) list several owners for the same trade; attributing the trade to each
  of them would fake a "cluster" of insiders, so only the first listed owner is kept.
- The table is reloaded from scratch each run (TRUNCATE + COPY), so the job is
  idempotent.

Usage:
    uv run python -m sec_filings.ingestion.form345_bulk data/raw/form345
"""

from __future__ import annotations

import io
import logging
import sys
import zipfile
from pathlib import Path

import polars as pl
import psycopg

from sec_filings.config import get_settings

logger = logging.getLogger(__name__)

_TICKER_RE = r"^[A-Z]{1,5}([.\-][A-Z]{1,2})?$"
_DATE_FMT = "%d-%b-%Y"
_DERIV_INDEX_OFFSET = 10_000

_COPY_COLUMNS = [
    "accession_number",
    "filing_date",
    "transaction_index",
    "owner_cik",
    "owner_name",
    "is_director",
    "is_officer",
    "is_ten_percent_owner",
    "is_other",
    "officer_title",
    "issuer_cik",
    "issuer_name",
    "issuer_ticker",
    "security_title",
    "transaction_date",
    "transaction_code",
    "shares",
    "price_per_share",
    "shares_after",
    "direct_or_indirect",
    "is_derivative",
    "is_10b5_1",
]


def _read_tsv(zf: zipfile.ZipFile, name: str) -> pl.DataFrame:
    with zf.open(name) as fh:
        return pl.read_csv(
            fh.read(),
            separator="\t",
            quote_char=None,
            infer_schema=False,
            truncate_ragged_lines=True,
            encoding="utf8-lossy",
        )


def _clean_ticker(col: pl.Expr) -> pl.Expr:
    """Normalize the free-text ISSUERTRADINGSYMBOL ("NYSE: KRC", "WLY, WLYB", "vicr")."""
    up = col.str.to_uppercase().str.strip_chars()
    placeholder = up.is_in(["N/A", "NA", "NONE", "NULL", "N.A.", "-", "--", "NOT APPLICABLE"])
    t = (
        pl.when(placeholder)
        .then(None)
        .otherwise(up)
        .str.replace_all(r"^.*[:/]\s*", "")  # drop exchange prefixes
        .str.split(",")
        .list.first()
        .str.strip_chars()
        .str.split(" ")
        .list.first()
    )
    return pl.when(t.str.contains(_TICKER_RE)).then(t).otherwise(None)


def _to_float(col: str) -> pl.Expr:
    return pl.col(col).str.strip_chars().cast(pl.Float64, strict=False)


def _transactions(
    zf: zipfile.ZipFile, table: str, sk_col: str, offset: int, header: pl.DataFrame
) -> pl.DataFrame:
    tx = _read_tsv(zf, table)
    tx = tx.join(header, on="ACCESSION_NUMBER", how="inner")
    tx = tx.with_columns(pl.col(sk_col).cast(pl.Int64, strict=False).alias("_sk")).sort(
        ["ACCESSION_NUMBER", "_sk"]
    )
    return tx.select(
        pl.col("ACCESSION_NUMBER").alias("accession_number"),
        pl.col("filing_date"),
        (pl.int_range(pl.len()).over("ACCESSION_NUMBER") + offset).alias("transaction_index"),
        pl.col("owner_cik"),
        pl.col("owner_name"),
        pl.col("is_director"),
        pl.col("is_officer"),
        pl.col("is_ten_percent_owner"),
        pl.col("is_other"),
        pl.col("officer_title"),
        pl.col("issuer_cik"),
        pl.col("issuer_name"),
        pl.col("issuer_ticker"),
        pl.col("SECURITY_TITLE").fill_null("").str.slice(0, 200).alias("security_title"),
        pl.col("TRANS_DATE")
        .str.strptime(pl.Date, _DATE_FMT, strict=False)
        .alias("transaction_date"),
        pl.col("TRANS_CODE").str.strip_chars().str.slice(0, 5).alias("transaction_code"),
        _to_float("TRANS_SHARES").alias("shares"),
        _to_float("TRANS_PRICEPERSHARE").alias("price_per_share"),
        _to_float("SHRS_OWND_FOLWNG_TRANS").alias("shares_after"),
        pl.col("DIRECT_INDIRECT_OWNERSHIP")
        .str.strip_chars()
        .str.slice(0, 1)
        .alias("direct_or_indirect"),
        pl.lit(offset > 0).alias("is_derivative"),
        pl.col("is_10b5_1"),
    )


def parse_quarter(path: Path) -> pl.DataFrame:
    """Turn one quarterly zip into rows shaped like raw.insider_transactions."""
    with zipfile.ZipFile(path) as zf:
        sub = _read_tsv(zf, "SUBMISSION.tsv")
        sub = sub.filter(pl.col("DOCUMENT_TYPE").str.strip_chars() == "4")
        aff = (
            pl.col("AFF10B5ONE").str.to_lowercase().is_in(["1", "true"])
            if "AFF10B5ONE" in sub.columns
            else pl.lit(False)
        )
        sub = sub.select(
            "ACCESSION_NUMBER",
            pl.col("FILING_DATE")
            .str.strptime(pl.Date, _DATE_FMT, strict=False)
            .alias("filing_date"),
            pl.col("ISSUERCIK").cast(pl.Int64, strict=False).alias("issuer_cik"),
            pl.col("ISSUERNAME").fill_null("").str.slice(0, 200).alias("issuer_name"),
            _clean_ticker(pl.col("ISSUERTRADINGSYMBOL")).alias("issuer_ticker"),
            aff.fill_null(False).alias("is_10b5_1"),
        ).drop_nulls(["filing_date", "issuer_cik"])

        own = _read_tsv(zf, "REPORTINGOWNER.tsv")
        rel = pl.col("RPTOWNER_RELATIONSHIP").fill_null("")
        own = (
            own.unique(subset="ACCESSION_NUMBER", keep="first", maintain_order=True)
            .select(
                "ACCESSION_NUMBER",
                pl.col("RPTOWNERCIK").cast(pl.Int64, strict=False).alias("owner_cik"),
                pl.col("RPTOWNERNAME").fill_null("").str.slice(0, 200).alias("owner_name"),
                rel.str.contains("Director").alias("is_director"),
                rel.str.contains("Officer").alias("is_officer"),
                rel.str.contains("TenPercentOwner").alias("is_ten_percent_owner"),
                rel.str.contains("Other").alias("is_other"),
                pl.col("RPTOWNER_TITLE").str.slice(0, 200).alias("officer_title"),
            )
            .drop_nulls("owner_cik")
        )

        header = sub.join(own, on="ACCESSION_NUMBER", how="inner")
        parts = [_transactions(zf, "NONDERIV_TRANS.tsv", "NONDERIV_TRANS_SK", 0, header)]
        if "DERIV_TRANS.tsv" in zf.namelist():
            parts.append(
                _transactions(zf, "DERIV_TRANS.tsv", "DERIV_TRANS_SK", _DERIV_INDEX_OFFSET, header)
            )
    return pl.concat(parts, how="vertical")


def load(folder: Path) -> int:
    zips = sorted(folder.glob("*_form345.zip"))
    if not zips:
        raise SystemExit(f"No *_form345.zip files in {folder}")

    dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    total = 0
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE raw.insider_transactions RESTART IDENTITY")
            for z in zips:
                df = parse_quarter(z)
                buf = io.BytesIO()
                df.select(_COPY_COLUMNS).write_csv(buf, include_header=False)
                buf.seek(0)
                cols = ", ".join(_COPY_COLUMNS)
                with cur.copy(
                    f"COPY raw.insider_transactions ({cols}) FROM STDIN WITH (FORMAT csv)"
                ) as cp:
                    while chunk := buf.read(1 << 20):
                        cp.write(chunk)
                total += df.height
                logger.info("%s: %d rows (running total %d)", z.name, df.height, total)
        conn.commit()
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/form345")
    print(f"Loaded {load(target):,} Form 4 transaction rows")
