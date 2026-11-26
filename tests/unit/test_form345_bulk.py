"""Unit tests for the Form 4 bulk loader's normalization rules."""

import zipfile
from pathlib import Path

import polars as pl

from sec_filings.ingestion.form345_bulk import _clean_ticker, parse_quarter


def test_clean_ticker_handles_free_text_symbols():
    raw = ["NYSE: KRC", "WLY, WLYB", "vicr", "NYSE/TRN", "N/A", "1314152", "BRK.B", None, "NONE"]
    out = pl.DataFrame({"t": raw}).select(_clean_ticker(pl.col("t"))).to_series().to_list()
    assert out[0] == "KRC"
    assert out[1] == "WLY"
    assert out[2] == "VICR"
    assert out[3] == "TRN"
    assert out[4] is None  # "N/A" must not become ticker "A" (Agilent)
    assert out[5] is None  # a CIK typed into the ticker field
    assert out[8] is None  # "NONE" placeholder
    assert out[6] == "BRK.B"
    assert out[7] is None


def _tsv(header: list[str], rows: list[list[str]]) -> str:
    return "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"


def _quarter_zip(tmp_path: Path) -> Path:
    sub = _tsv(
        [
            "ACCESSION_NUMBER",
            "FILING_DATE",
            "DOCUMENT_TYPE",
            "ISSUERCIK",
            "ISSUERNAME",
            "ISSUERTRADINGSYMBOL",
        ],
        [
            ["A-1", "03-JAN-2024", "4", "0000000001", "ACME CORP", "ACME"],
            ["A-2", "04-JAN-2024", "4/A", "0000000001", "ACME CORP", "ACME"],  # amendment: skipped
        ],
    )
    own = _tsv(
        [
            "ACCESSION_NUMBER",
            "RPTOWNERCIK",
            "RPTOWNERNAME",
            "RPTOWNER_RELATIONSHIP",
            "RPTOWNER_TITLE",
        ],
        [
            ["A-1", "0000000101", "Fund LP", "TenPercentOwner", ""],
            ["A-1", "0000000102", "Fund GP", "TenPercentOwner", ""],  # joint filer: dropped
            ["A-2", "0000000101", "Fund LP", "TenPercentOwner", ""],
        ],
    )
    cols = [
        "ACCESSION_NUMBER",
        "NONDERIV_TRANS_SK",
        "SECURITY_TITLE",
        "TRANS_DATE",
        "TRANS_CODE",
        "TRANS_SHARES",
        "TRANS_PRICEPERSHARE",
        "SHRS_OWND_FOLWNG_TRANS",
        "DIRECT_INDIRECT_OWNERSHIP",
    ]
    nd = _tsv(
        cols,
        [
            ["A-1", "2", "Common", "02-JAN-2024", "P", "100", "10.5", "1100", "D"],
            ["A-1", "1", "Common", "02-JAN-2024", "P", "50", "10.0", "1000", "D"],
            ["A-2", "3", "Common", "02-JAN-2024", "P", "100", "10.5", "1100", "D"],
        ],
    )
    path = tmp_path / "2024q1_form345.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("SUBMISSION.tsv", sub)
        zf.writestr("REPORTINGOWNER.tsv", own)
        zf.writestr("NONDERIV_TRANS.tsv", nd)
    return path


def test_parse_quarter_keeps_originals_and_one_owner(tmp_path):
    df = parse_quarter(_quarter_zip(tmp_path))
    assert df["accession_number"].unique().to_list() == ["A-1"]  # 4/A skipped
    assert df["owner_cik"].unique().to_list() == [101]  # first listed owner only
    assert df.height == 2
    # transaction_index follows the SEC row key, so the SK=1 row comes first
    first = df.filter(pl.col("transaction_index") == 0)
    assert first["shares"].item() == 50
    assert df["is_ten_percent_owner"].all()
    assert str(df["filing_date"][0]) == "2024-01-03"
