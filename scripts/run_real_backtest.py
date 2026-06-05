"""Real cluster-buy backtest.

Pulls historical insider purchases from openinsider.com (which parses Form 4
from SEC EDGAR), groups into cluster-buy events (>=3 distinct insiders within
a 90-day window per issuer, deduplicated to one event per issuer-quarter),
pulls forward 30/90/180-day adjusted-close returns from yfinance, benchmarks
against SPY over the same window, and emits aggregate stats by GICS sector.

Output: web/js/data.backtest.json (consumed by the dashboard)

Run: .venv/bin/python scripts/run_real_backtest.py
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backtest")

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "scripts" / ".cache"
CACHE.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 SECFilingsAnalytics/0.1"
SESS = requests.Session()
SESS.headers.update({"User-Agent": UA})


def scrape_openinsider_window(year_from: int, year_to: int) -> pd.DataFrame:
    """Scrape openinsider cluster-buy purchases (>=3 insiders flag) across a year window.

    We page through one calendar year at a time to keep result sets under
    openinsider's pagination ceiling. Filters: purchases only (xp=1),
    cluster size lower bound 3 (nil=3), 1000 results per page.
    """
    all_rows: list[dict[str, Any]] = []
    for year in range(year_from, year_to + 1):
        cached = CACHE / f"openinsider_{year}.csv"
        if cached.exists():
            log.info("Using cached %s", cached.name)
            df_year = pd.read_csv(cached)
            all_rows.extend(df_year.to_dict("records"))
            continue

        log.info("Scraping openinsider for %d", year)
        year_rows: list[dict[str, Any]] = []
        page = 1
        while True:
            fdr = f"01%2F01%2F{year}-12%2F31%2F{year}"
            url = (
                f"http://openinsider.com/screener?"
                f"fd=0&fdr={fdr}&xp=1&nil=3&cnt=1000&page={page}"
            )
            r = SESS.get(url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            table = soup.find("table", class_="tinytable")
            if not table:
                break
            tbody = table.find("tbody")
            rows = tbody.find_all("tr") if tbody else []
            if not rows:
                break

            for tr in rows:
                tds = tr.find_all("td")
                if len(tds) < 13:
                    continue
                try:
                    filing_date = tds[1].get_text(strip=True).split(" ")[0]
                    trade_date = tds[2].get_text(strip=True)
                    ticker = tds[3].get_text(strip=True)
                    company = tds[4].get_text(strip=True)
                    insider = tds[5].get_text(strip=True)
                    title = tds[6].get_text(strip=True)
                    qty = tds[9].get_text(strip=True).replace(",", "").replace("+", "")
                    price = tds[8].get_text(strip=True).replace("$", "").replace(",", "")
                    value = tds[10].get_text(strip=True).replace("$", "").replace(",", "").replace("+", "")
                    year_rows.append(
                        {
                            "filing_date": filing_date,
                            "trade_date": trade_date,
                            "ticker": ticker,
                            "company": company,
                            "insider": insider,
                            "title": title,
                            "qty": float(qty) if qty else 0,
                            "price": float(price) if price else 0,
                            "value": float(value) if value else 0,
                        }
                    )
                except (ValueError, IndexError):
                    continue

            log.info("  page %d -> %d rows so far", page, len(year_rows))
            if len(rows) < 1000:
                break
            page += 1
            time.sleep(1.2)

        df_year = pd.DataFrame(year_rows)
        if not df_year.empty:
            df_year.to_csv(cached, index=False)
        all_rows.extend(year_rows)
        time.sleep(1.5)

    return pd.DataFrame(all_rows)


def derive_cluster_events(transactions: pd.DataFrame) -> pd.DataFrame:
    """Group transactions into cluster events.

    For each ticker, sort by trade date. Use a 90-day rolling window: if a
    given trade is preceded (or accompanied) by purchases from 3+ distinct
    insiders within 90 days, mark that day as a cluster point. Dedupe to
    one event per (ticker, quarter).
    """
    if transactions.empty:
        return pd.DataFrame()

    transactions["trade_date"] = pd.to_datetime(transactions["trade_date"], errors="coerce")
    transactions = transactions.dropna(subset=["trade_date"])
    transactions = transactions[transactions["value"] > 0]

    events: list[dict[str, Any]] = []
    for ticker, group in transactions.groupby("ticker"):
        g = group.sort_values("trade_date").reset_index(drop=True)
        for i, row in g.iterrows():
            window_start = row["trade_date"] - pd.Timedelta(days=90)
            window = g[(g["trade_date"] >= window_start) & (g["trade_date"] <= row["trade_date"])]
            n_distinct = window["insider"].nunique()
            total_value = window["value"].sum()
            if n_distinct >= 3 and total_value >= 250_000:
                events.append(
                    {
                        "ticker": ticker,
                        "company": row["company"],
                        "signal_date": row["trade_date"],
                        "n_insiders_90d": int(n_distinct),
                        "total_value_90d": float(total_value),
                    }
                )

    df_ev = pd.DataFrame(events)
    if df_ev.empty:
        return df_ev

    df_ev["quarter"] = df_ev["signal_date"].dt.to_period("Q")
    df_ev = df_ev.sort_values(["ticker", "quarter", "signal_date"])
    df_ev = df_ev.drop_duplicates(subset=["ticker", "quarter"], keep="first")
    df_ev = df_ev.drop(columns=["quarter"]).reset_index(drop=True)
    return df_ev


def fetch_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Batch download adjusted close prices for tickers and SPY benchmark."""
    cached = CACHE / "prices.parquet"
    universe = sorted(set(tickers + ["SPY"]))

    if cached.exists():
        log.info("Using cached prices: %s", cached.name)
        df = pd.read_parquet(cached)
        have = set(df.columns.get_level_values(1)) if isinstance(df.columns, pd.MultiIndex) else set(df.columns)
        missing = [t for t in universe if t not in have]
        if not missing:
            return {t: df.xs(t, axis=1, level=1) if isinstance(df.columns, pd.MultiIndex) else df[[t]] for t in universe}
        log.info("Cache missing %d tickers, refetching", len(missing))

    log.info("yfinance download for %d tickers", len(universe))
    df = yf.download(
        universe,
        start="2018-01-01",
        end="2026-01-01",
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    df.to_parquet(cached)

    out: dict[str, pd.DataFrame] = {}
    if isinstance(df.columns, pd.MultiIndex):
        for t in universe:
            if t in df.columns.get_level_values(0):
                out[t] = df[t].dropna()
    else:
        out[universe[0]] = df.dropna()
    return out


def get_price_on_or_after(prices: pd.DataFrame, target_date: pd.Timestamp) -> float | None:
    """Return adjusted close on the first trading day >= target_date."""
    if prices is None or prices.empty:
        return None
    after = prices[prices.index >= target_date]
    if after.empty:
        return None
    val = after.iloc[0]["Close"]
    return float(val) if not pd.isna(val) else None


def compute_event_returns(events: pd.DataFrame, prices: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """For each event, compute stock + SPY returns at 30/90/180d."""
    spy = prices.get("SPY")
    if spy is None or spy.empty:
        raise RuntimeError("SPY price history missing")

    horizons = [30, 90, 180]
    rows: list[dict[str, Any]] = []
    for _, ev in events.iterrows():
        t = ev["ticker"]
        sp = prices.get(t)
        if sp is None or sp.empty:
            continue
        entry = get_price_on_or_after(sp, ev["signal_date"])
        spy_entry = get_price_on_or_after(spy, ev["signal_date"])
        if entry is None or spy_entry is None or entry <= 0 or spy_entry <= 0:
            continue
        row = {
            "ticker": t,
            "company": ev["company"],
            "signal_date": ev["signal_date"].strftime("%Y-%m-%d"),
            "n_insiders_90d": ev["n_insiders_90d"],
            "total_value_90d": ev["total_value_90d"],
            "entry_price": entry,
            "spy_entry": spy_entry,
        }
        complete = True
        for h in horizons:
            target = ev["signal_date"] + pd.Timedelta(days=h)
            stock_exit = get_price_on_or_after(sp, target)
            spy_exit = get_price_on_or_after(spy, target)
            if stock_exit is None or spy_exit is None or stock_exit <= 0 or spy_exit <= 0:
                complete = False
                break
            stock_ret = (stock_exit / entry) - 1
            spy_ret = (spy_exit / spy_entry) - 1
            row[f"stock_return_h{h}"] = stock_ret
            row[f"spy_return_h{h}"] = spy_ret
            row[f"excess_h{h}"] = stock_ret - spy_ret
            row[f"beat_h{h}"] = int(stock_ret > spy_ret)
        if complete:
            rows.append(row)
    return pd.DataFrame(rows)


def lookup_sectors(tickers: list[str]) -> dict[str, str]:
    """Best-effort GICS sector lookup via yfinance ticker info."""
    cached = CACHE / "sectors.json"
    cache: dict[str, str] = {}
    if cached.exists():
        cache = json.loads(cached.read_text())

    need = [t for t in tickers if t not in cache]
    if not need:
        return cache

    log.info("Sector lookup for %d new tickers", len(need))
    for i, t in enumerate(need, 1):
        try:
            info = yf.Ticker(t).info
            cache[t] = info.get("sector") or "Unclassified"
        except Exception:
            cache[t] = "Unclassified"
        if i % 25 == 0:
            cached.write_text(json.dumps(cache, indent=2))
            log.info("  %d/%d", i, len(need))
        time.sleep(0.1)
    cached.write_text(json.dumps(cache, indent=2))
    return cache


def aggregate(detail: pd.DataFrame, sectors: dict[str, str]) -> dict[str, Any]:
    """Roll up per-event detail into overall + by-sector stats."""
    detail = detail.copy()
    detail["sector"] = detail["ticker"].map(lambda t: sectors.get(t, "Unclassified") or "Unclassified")

    def _summary(df: pd.DataFrame) -> dict[str, Any]:
        if df.empty:
            return {}
        excess = df["excess_h180"].tolist()
        stddev = statistics.pstdev(excess) if len(excess) > 1 else 0.0
        avg_excess = float(df["excess_h180"].mean())
        return {
            "n_signals": int(len(df)),
            "avg_stock_return_180d": float(df["stock_return_h180"].mean()),
            "avg_bench_return_180d": float(df["spy_return_h180"].mean()),
            "avg_excess_return_180d": avg_excess,
            "median_excess_return_180d": float(df["excess_h180"].median()),
            "hit_rate_30d": float(df["beat_h30"].mean()),
            "hit_rate_90d": float(df["beat_h90"].mean()),
            "hit_rate_180d": float(df["beat_h180"].mean()),
            "stddev_excess_180d": float(stddev),
            "info_ratio_180d": float(avg_excess / stddev) if stddev > 0 else 0.0,
        }

    overall = _summary(detail)
    by_sector_raw = [
        {"sector": sec, **_summary(g)}
        for sec, g in detail.groupby("sector")
        if len(g) >= 10
    ]
    by_sector = [
        {
            "sector": s["sector"],
            "n": s["n_signals"],
            "hit_rate": s["hit_rate_180d"],
            "avg_excess": s["avg_excess_return_180d"],
            "avg_stock": s["avg_stock_return_180d"],
            "avg_bench": s["avg_bench_return_180d"],
        }
        for s in by_sector_raw
    ]
    by_sector.sort(key=lambda x: x["avg_excess"], reverse=True)

    # Distribution histogram
    buckets = [
        ("<-40%", -float("inf"), -0.40),
        ("-40--30%", -0.40, -0.30),
        ("-30--20%", -0.30, -0.20),
        ("-20--10%", -0.20, -0.10),
        ("-10-0%", -0.10, 0.0),
        ("0-10%", 0.0, 0.10),
        ("10-20%", 0.10, 0.20),
        ("20-30%", 0.20, 0.30),
        ("30-40%", 0.30, 0.40),
        ("40-60%", 0.40, 0.60),
        (">60%", 0.60, float("inf")),
    ]
    dist = []
    for label, lo, hi in buckets:
        count = int(((detail["excess_h180"] >= lo) & (detail["excess_h180"] < hi)).sum())
        dist.append({"bucket": label, "count": count})

    # Top 3 wins and bottom 3 losses by excess_h180, with full row context.
    sorted_by_excess = detail.sort_values("excess_h180", ascending=False)
    wins = sorted_by_excess.head(3)
    losses = sorted_by_excess.tail(3).iloc[::-1]

    def _case(row: pd.Series, label: str) -> dict[str, Any]:
        return {
            "ticker": row["ticker"],
            "name": row["company"],
            "signal_date": row["signal_date"],
            "stock_return": float(row["stock_return_h180"]),
            "bench_return": float(row["spy_return_h180"]),
            "excess": float(row["excess_h180"]),
        }

    case_studies = [_case(r, "win") for _, r in wins.iterrows()] + [
        _case(r, "loss") for _, r in losses.iterrows()
    ]

    return {
        "horizon_days": 180,
        "period": f"{detail['signal_date'].min()} to {detail['signal_date'].max()}",
        "benchmark": "SPY (total return)",
        "methodology": (
            "Cluster-buy events scraped from openinsider.com (filtered to "
            "open-market purchases by >=3 distinct insiders within 90 days, "
            "deduplicated to one event per issuer per calendar quarter). "
            "Forward returns from yfinance adjusted closes; entry on first "
            "trading day on or after the signal date, exits at 30/90/180 "
            "calendar days forward (nearest trading day). Benchmark is SPY "
            "matched on same legs. Excess return = stock return minus SPY "
            "over the same window. Equal-weight, no slippage, no fees, "
            "no survivorship adjustment."
        ),
        "overall": overall,
        "by_sector": by_sector,
        "distribution_180d": dist,
        "case_studies": case_studies,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--year-from", type=int, default=2019)
    p.add_argument("--year-to", type=int, default=2024)
    args = p.parse_args()

    log.info("=== Stage 1: scrape openinsider %d-%d ===", args.year_from, args.year_to)
    txns = scrape_openinsider_window(args.year_from, args.year_to)
    log.info("Loaded %d insider purchase transactions", len(txns))

    log.info("=== Stage 2: derive cluster events ===")
    events = derive_cluster_events(txns)
    log.info("Derived %d cluster-buy events across %d tickers", len(events), events["ticker"].nunique() if not events.empty else 0)
    if events.empty:
        log.error("No events. Aborting.")
        return

    tickers = events["ticker"].unique().tolist()
    log.info("=== Stage 3: fetch prices for %d tickers + SPY ===", len(tickers))
    prices = fetch_prices(tickers)
    log.info("Got prices for %d tickers", sum(1 for v in prices.values() if not v.empty))

    log.info("=== Stage 4: compute returns ===")
    detail = compute_event_returns(events, prices)
    log.info("Computed returns for %d events (lost %d to missing prices)", len(detail), len(events) - len(detail))

    log.info("=== Stage 5: sector lookup ===")
    used_tickers = detail["ticker"].unique().tolist()
    sectors = lookup_sectors(used_tickers)

    log.info("=== Stage 6: aggregate ===")
    result = aggregate(detail, sectors)
    log.info("Overall: n=%d, avg_excess_180d=%.4f, hit_rate_180d=%.4f",
             result["overall"]["n_signals"],
             result["overall"]["avg_excess_return_180d"],
             result["overall"]["hit_rate_180d"])
    log.info("Top sector: %s (excess=%.4f, hit=%.4f)",
             result["by_sector"][0]["sector"], result["by_sector"][0]["avg_excess"], result["by_sector"][0]["hit_rate"])

    out = ROOT / "web" / "js" / "data.backtest.json"
    out.write_text(json.dumps(result, indent=2, default=str))
    log.info("Wrote %s", out)

    # Also dump the per-event detail for auditability.
    detail_out = ROOT / "scripts" / ".cache" / "backtest_detail.csv"
    detail.to_csv(detail_out, index=False)
    log.info("Wrote per-event detail to %s", detail_out)


if __name__ == "__main__":
    main()
