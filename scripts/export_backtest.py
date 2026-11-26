"""Export the measured cluster-buy backtest from the dbt marts to the static dashboard.

Writes web/js/backtest_data.js (window.SEC_BACKTEST) and prints a plain summary,
including the robustness checks that belong next to any headline number:
signals dropped for missing prices, median vs mean, a $5+ entry-price subset and
a by-year split.

Usage (after `dbt run`):
    uv run python scripts/export_backtest.py
"""

from __future__ import annotations

import json
import statistics
from datetime import date
from pathlib import Path

import psycopg

from sec_filings.config import get_settings

OUT = Path(__file__).resolve().parents[1] / "web" / "js" / "backtest_data.js"

BUCKETS = [
    ("<-40%", None, -0.40),
    ("-40--30%", -0.40, -0.30),
    ("-30--20%", -0.30, -0.20),
    ("-20--10%", -0.20, -0.10),
    ("-10-0%", -0.10, 0.0),
    ("0-10%", 0.0, 0.10),
    ("10-20%", 0.10, 0.20),
    ("20-30%", 0.20, 0.30),
    ("30-40%", 0.30, 0.40),
    ("40-60%", 0.40, 0.60),
    (">60%", 0.60, None),
]


def _stats(rows: list[dict]) -> dict:
    ex = [r["excess_return_h180"] for r in rows]
    n = len(ex)
    sd = statistics.pstdev(ex) if n > 1 else 0.0
    mean = statistics.fmean(ex) if n else 0.0
    return {
        "n_signals": n,
        "avg_stock_return_180d": statistics.fmean(r["stock_return_h180"] for r in rows) if n else 0,
        "avg_bench_return_180d": statistics.fmean(r["bench_return_h180"] for r in rows) if n else 0,
        "avg_excess_return_180d": mean,
        "median_excess_return_180d": statistics.median(ex) if n else 0,
        "hit_rate_30d": sum(r["beat_benchmark_h30"] for r in rows) / n if n else 0,
        "hit_rate_90d": sum(r["beat_benchmark_h90"] for r in rows) / n if n else 0,
        "hit_rate_180d": sum(r["beat_benchmark_h180"] for r in rows) / n if n else 0,
        "stddev_excess_180d": sd,
        "info_ratio_180d": mean / sd if sd else 0,
    }


def main() -> None:
    dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn) as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "select count(*) as n, min(signal_date) as lo, max(signal_date) as hi "
            "from public_intermediate.int_cluster_buy_events"
        )
        events = cur.fetchone()
        cur.execute("select * from public_mart.mart_signal_validation_detail order by signal_date")
        detail = [
            {k: (float(v) if hasattr(v, "is_finite") else v) for k, v in r.items()}
            for r in cur.fetchall()
        ]
        cur.execute(
            "select count(distinct ticker) as n from raw.daily_prices where ticker <> 'SPY'"
        )
        priced_tickers = cur.fetchone()["n"]

        # Robustness 1: small-cap benchmark (IWM) instead of SPY, same windows.
        cur.execute(
            """
            select d.signal_id,
              (select adj_close from raw.daily_prices p where p.ticker = 'IWM'
                 and p.date > d.signal_date order by p.date limit 1) as i0,
              (select adj_close from raw.daily_prices p where p.ticker = 'IWM'
                 and p.date >= d.signal_date + 180 order by p.date limit 1) as i1
            from public_mart.mart_signal_validation_detail d
            """
        )
        iwm = {r["signal_id"]: (r["i0"], r["i1"]) for r in cur.fetchall()}

        # Robustness 2: signals whose Yahoo entry price is within 30% of the price the
        # insiders actually paid, which rules out mis-mapped tickers (and also drops
        # stocks with big later splits or high dividends, whose adjusted history moves).
        cur.execute(
            """
            select d.signal_id,
              d.entry_price / (sum(t.shares * t.price_per_share) / sum(t.shares)) as ratio
            from public_mart.mart_signal_validation_detail d
            join raw.insider_transactions t
              on t.issuer_cik = d.issuer_cik and t.transaction_code = 'P'
             and not t.is_derivative and t.price_per_share > 0 and t.shares > 0
             and t.filing_date between d.signal_date - 90 and d.signal_date
            group by d.signal_id, d.entry_price
            """
        )
        price_ok = {r["signal_id"] for r in cur.fetchall() if 0.7 <= float(r["ratio"]) <= 1.3}

    overall = _stats(detail)
    by_sector = []
    for sector in sorted({r["gics_sector"] for r in detail}):
        rows = [r for r in detail if r["gics_sector"] == sector]
        if len(rows) < 20:  # too few signals to say anything about a sector
            continue
        s = _stats(rows)
        by_sector.append(
            {
                "sector": sector,
                "n": s["n_signals"],
                "hit_rate": s["hit_rate_180d"],
                "avg_excess": s["avg_excess_return_180d"],
                "median_excess": s["median_excess_return_180d"],
                "avg_stock": s["avg_stock_return_180d"],
                "avg_bench": s["avg_bench_return_180d"],
            }
        )

    dist = []
    for label, lo, hi in BUCKETS:
        dist.append(
            {
                "bucket": label,
                "count": sum(
                    1
                    for r in detail
                    if (lo is None or r["excess_return_h180"] >= lo)
                    and (hi is None or r["excess_return_h180"] < hi)
                ),
            }
        )

    liquid = [r for r in detail if r["entry_price"] >= 5]
    clean = [r for r in detail if r["signal_id"] in price_ok]
    vs_iwm = []
    for r in detail:
        i0, i1 = iwm.get(r["signal_id"], (None, None))
        if i0 and i1:
            b = float(i1) / float(i0) - 1
            vs_iwm.append(
                {
                    **r,
                    "bench_return_h180": b,
                    "excess_return_h180": r["stock_return_h180"] - b,
                    "beat_benchmark_h180": int(r["stock_return_h180"] > b),
                }
            )
    by_year = {}
    for y in sorted({r["signal_year"] for r in detail}):
        s = _stats([r for r in detail if r["signal_year"] == y])
        by_year[str(y)] = {
            k: s[k]
            for k in (
                "n_signals",
                "avg_excess_return_180d",
                "median_excess_return_180d",
                "hit_rate_180d",
            )
        }

    # Biggest wins and misses among $5+ stocks, one per company.
    ranked = sorted(liquid, key=lambda r: r["excess_return_h180"])
    seen: set[str] = set()
    best, worst = [], []
    for r in reversed(ranked):
        if len(best) < 4 and r["issuer_ticker"] not in seen:
            best.append(r)
            seen.add(r["issuer_ticker"])
    for r in ranked:
        if len(worst) < 2 and r["issuer_ticker"] not in seen:
            worst.append(r)
            seen.add(r["issuer_ticker"])
    case = best + worst
    case_studies = [
        {
            "ticker": r["issuer_ticker"],
            "name": r["issuer_name"].title(),
            "signal_date": r["signal_date"].isoformat(),
            "stock_return": r["stock_return_h180"],
            "bench_return": r["bench_return_h180"],
            "excess": r["excess_return_h180"],
        }
        for r in case
    ]

    lo, hi = detail[0]["signal_date"], detail[-1]["signal_date"]
    payload = {
        "is_real": True,
        "generated": date.today().isoformat(),
        "horizon_days": 180,
        "period": f"{lo:%b %Y} to {hi:%b %Y}",
        "benchmark": "SPY (total return)",
        "overall": overall,
        "liquid_subset": {"rule": "entry price $5 or more", **_stats(liquid)},
        "price_checked_subset": {
            "rule": "Yahoo entry price within 30% of the insiders' own purchase price",
            **_stats(clean),
        },
        "vs_small_caps": {
            "rule": "same signals, benchmark IWM (Russell 2000) instead of SPY",
            **{k: v for k, v in _stats(vs_iwm).items() if "30d" not in k and "90d" not in k},
        },
        "coverage": {
            "events_found": events["n"],
            "events_priced": len(detail),
            "events_dropped": events["n"] - len(detail),
            "tickers_priced": priced_tickers,
        },
        "by_year": by_year,
        "by_sector": by_sector,
        "distribution_180d": dist,
        "case_studies": case_studies,
    }
    OUT.write_text(
        "// Measured cluster-buy backtest, generated by scripts/export_backtest.py.\n"
        "// Source: SEC Form 4 bulk data sets + Yahoo Finance adjusted prices.\n"
        "// Not investment advice.\n"
        f"window.SEC_BACKTEST = {json.dumps(payload, indent=2, default=str)};\n"
    )
    print(
        json.dumps(
            {
                k: payload[k]
                for k in (
                    "period",
                    "overall",
                    "liquid_subset",
                    "price_checked_subset",
                    "vs_small_caps",
                    "coverage",
                )
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
