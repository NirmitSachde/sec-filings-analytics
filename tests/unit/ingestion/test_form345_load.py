"""Unit tests for the Form 4 bulk loader's DB load path and CLI entry (psycopg mocked)."""

import io
import runpy
import sys
import warnings
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import psycopg
import pytest

from sec_filings.ingestion import form345_bulk
from sec_filings.ingestion.form345_bulk import _COPY_COLUMNS, load, parse_quarter


def _tsv(header: list[str], rows: list[list[str]]) -> str:
    return "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"


_TX_COLS = [
    "SECURITY_TITLE",
    "TRANS_DATE",
    "TRANS_CODE",
    "TRANS_SHARES",
    "TRANS_PRICEPERSHARE",
    "SHRS_OWND_FOLWNG_TRANS",
    "DIRECT_INDIRECT_OWNERSHIP",
]


def _write_zip(path: Path, acc: str, *, deriv: bool, aff: str | None) -> Path:
    sub_cols = [
        "ACCESSION_NUMBER",
        "FILING_DATE",
        "DOCUMENT_TYPE",
        "ISSUERCIK",
        "ISSUERNAME",
        "ISSUERTRADINGSYMBOL",
    ]
    sub_row = [acc, "15-FEB-2024", "4", "0000320193", "Apple Inc", "NASDAQ: aapl"]
    if aff is not None:
        sub_cols.append("AFF10B5ONE")
        sub_row.append(aff)
    own = _tsv(
        [
            "ACCESSION_NUMBER",
            "RPTOWNERCIK",
            "RPTOWNERNAME",
            "RPTOWNER_RELATIONSHIP",
            "RPTOWNER_TITLE",
        ],
        [[acc, "0001214156", "COOK TIMOTHY D", "Director,Officer", "CEO"]],
    )
    nd = _tsv(
        ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", *_TX_COLS],
        [[acc, "1", "Common Stock", "13-FEB-2024", "S", "1000", "185.5", "3000000", "D"]],
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("SUBMISSION.tsv", _tsv(sub_cols, [sub_row]))
        zf.writestr("REPORTINGOWNER.tsv", own)
        zf.writestr("NONDERIV_TRANS.tsv", nd)
        if deriv:
            zf.writestr(
                "DERIV_TRANS.tsv",
                _tsv(
                    ["ACCESSION_NUMBER", "DERIV_TRANS_SK", *_TX_COLS],
                    [
                        [acc, "9", "RSU", "13-FEB-2024", "M", "500", "", "100", "D"],
                        [acc, "8", "RSU", "12-FEB-2024", "M", "200", "", "600", "D"],
                    ],
                ),
            )
    return path


class _Db:
    def __init__(self) -> None:
        self.conn = MagicMock()
        self.conn.__enter__.return_value = self.conn
        self.cur = MagicMock()
        self.cur.__enter__.return_value = self.cur
        self.conn.cursor.return_value = self.cur
        self.copy_sql: list[str] = []
        self.payloads: list[bytes] = []

        def copy(sql):
            self.copy_sql.append(sql)
            chunks: list[bytes] = []
            self.payloads.append(chunks)  # type: ignore[arg-type]
            cp = MagicMock()
            cp.write.side_effect = chunks.append
            cm = MagicMock()
            cm.__enter__.return_value = cp
            return cm

        self.cur.copy.side_effect = copy

    def frames(self) -> list[pl.DataFrame]:
        return [
            pl.read_csv(
                io.BytesIO(b"".join(chunks)),
                has_header=False,
                new_columns=_COPY_COLUMNS,
                infer_schema=False,
            )
            for chunks in self.payloads
        ]


def test_parse_quarter_with_derivatives_and_10b5_1_flag(tmp_path):
    df = parse_quarter(_write_zip(tmp_path / "q_form345.zip", "A-1", deriv=True, aff="1"))
    assert df.height == 3
    nonderiv = df.filter(~pl.col("is_derivative"))
    deriv = df.filter(pl.col("is_derivative")).sort("transaction_index")
    assert nonderiv["transaction_index"].to_list() == [0]
    # Derivative rows are offset and ordered by their SEC row key (SK 8 before SK 9).
    assert deriv["transaction_index"].to_list() == [10_000, 10_001]
    assert deriv["shares"].to_list() == [200.0, 500.0]
    assert deriv["price_per_share"].to_list() == [None, None]
    assert df["issuer_ticker"].unique().to_list() == ["AAPL"]
    assert df["is_10b5_1"].all()
    row = nonderiv.row(0, named=True)
    assert row["is_director"] and row["is_officer"]
    assert not row["is_ten_percent_owner"]
    assert row["transaction_code"] == "S"
    assert row["direct_or_indirect"] == "D"
    assert str(row["transaction_date"]) == "2024-02-13"


def test_parse_quarter_without_aff_column_defaults_false(tmp_path):
    df = parse_quarter(_write_zip(tmp_path / "q_form345.zip", "A-1", deriv=False, aff=None))
    assert df.height == 1
    assert not df["is_10b5_1"].any()
    assert not df["is_derivative"].any()


def test_load_without_zips_exits(tmp_path):
    with pytest.raises(SystemExit, match="No \\*_form345.zip files"):
        load(tmp_path)


def test_load_truncates_then_copies_each_quarter(tmp_path, monkeypatch):
    _write_zip(tmp_path / "2024q2_form345.zip", "B-1", deriv=False, aff="0")
    _write_zip(tmp_path / "2024q1_form345.zip", "A-1", deriv=True, aff="true")
    (tmp_path / "notes.txt").write_text("not a zip")
    db = _Db()
    dsns: list[str] = []

    def connect(dsn):
        dsns.append(dsn)
        return db.conn

    monkeypatch.setattr(form345_bulk.psycopg, "connect", connect)

    total = load(tmp_path)

    assert total == 4
    assert dsns[0].startswith("postgresql://") and "+psycopg" not in dsns[0]
    db.cur.execute.assert_called_once_with("TRUNCATE raw.insider_transactions RESTART IDENTITY")
    assert len(db.copy_sql) == 2
    for sql in db.copy_sql:
        assert sql.startswith(f"COPY raw.insider_transactions ({', '.join(_COPY_COLUMNS)})")
        assert sql.endswith("FROM STDIN WITH (FORMAT csv)")
    q1, q2 = db.frames()
    # Quarters load in sorted file order.
    assert q1["accession_number"].unique().to_list() == ["A-1"]
    assert q1.height == 3
    assert q2["accession_number"].to_list() == ["B-1"]
    assert q2["issuer_ticker"].to_list() == ["AAPL"]
    assert q2["is_10b5_1"].to_list() == ["false"]
    db.conn.commit.assert_called_once()


def test_load_streams_large_payload_in_chunks(tmp_path, monkeypatch):
    path = _write_zip(tmp_path / "2024q1_form345.zip", "A-1", deriv=False, aff=None)
    one = parse_quarter(path)
    big = pl.concat([one] * 12_000)  # well over the 1 MiB COPY chunk size
    monkeypatch.setattr(form345_bulk, "parse_quarter", lambda z: big)
    db = _Db()
    monkeypatch.setattr(form345_bulk.psycopg, "connect", lambda dsn: db.conn)

    assert load(tmp_path) == 12_000
    chunks = db.payloads[0]
    assert len(chunks) >= 2
    assert all(len(c) <= 1 << 20 for c in chunks)
    assert db.frames()[0].height == 12_000


def test_main_entry_loads_given_folder(tmp_path, monkeypatch, capsys):
    _write_zip(tmp_path / "2024q1_form345.zip", "A-1", deriv=False, aff=None)
    db = _Db()
    monkeypatch.setattr(psycopg, "connect", lambda dsn: db.conn)
    monkeypatch.setattr(sys, "argv", ["form345_bulk", str(tmp_path)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # module already imported
        runpy.run_module("sec_filings.ingestion.form345_bulk", run_name="__main__")
    assert "Loaded 1 Form 4 transaction rows" in capsys.readouterr().out
