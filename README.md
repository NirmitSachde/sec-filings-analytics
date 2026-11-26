# SEC Filings Analytics Platform

> **Disclaimer.** This is a **non-commercial personal portfolio project** built for skill demonstration. It is **not a product, not a service, and not investment advice**. The **Signal Validation backtest is measured on real SEC data** (see below); every other figure on the live dashboard is **illustrative sample data**. The author is not a registered investment adviser. No warranty, no liability. Use is entirely at your own risk. Full terms: [DISCLAIMER.md](./DISCLAIMER.md) · [LICENSE](./LICENSE).

A data engineering + analytics platform that ingests SEC EDGAR filings (Form 4, 13F-HR, 10-K/10-Q), normalizes them into a queryable warehouse, and surfaces insights through Metabase dashboards, a FastAPI REST service, and a static web dashboard.

**Stack:** Python 3.12 · PostgreSQL 16 + pgvector · Prefect 3 · dbt-core · FastAPI · Metabase · Ollama (Llama 3.1 8B)

**🌐 Live demo:** **https://nirmitsachde.github.io/sec-filings-analytics/**

The dashboard demonstrates six analytics views built on the platform: cluster-buying screener, hedge-fund 13F tracker, ownership concentration (HHI), insider buy/sell time series, year-over-year risk-factor drift (NLP + pgvector + local Llama), and a signal-validation backtest measured on 12 years of real Form 4 filings.

## Architecture

```
EDGAR (filings + index)
      │
      ▼
 Prefect 3 flows ── respecting 10 req/s
      │
      ▼
 Raw zone: filings stored as-received under data/raw/{form}/{cik}/{accession}/
      │
      ▼
 Parsers by form type:
   ├─ Form 4 XML parser     → raw.insider_transactions
   ├─ 13F-HR XML parser     → raw.holdings_positions
   └─ XBRL / HTML parser    → raw.xbrl_facts + raw.filing_sections
      │
      ▼
 PostgreSQL 16 + pgvector
      │
      ▼
 dbt-core: staging → intermediate → marts (20 models)
      │
      ▼
 ┌──────────────────────┬────────────────────────┐
 │  Metabase (BI, :3000) │  FastAPI (REST, :8000)  │
 └──────────────────────┴────────────────────────┘
```

## Quick Start

```bash
# Clone and set up
git clone <repo-url> && cd sec-filings-analytics
cp .env.example .env   # edit EDGAR_USER_AGENT with your name + email

# Start all services
make up

# Install Python dependencies (local dev)
make install

# Run database migrations
make migrate

# Crawl EDGAR index (last 5 years)
make ingest-index

# Fetch and parse filings
make ingest-filings

# Build dbt models
make dbt-build

# Measured cluster-buy backtest (real data, about an hour end to end)
make backfill-form4   # ~50 SEC quarterly zips -> raw.insider_transactions
make backtest         # tickers, events, Yahoo prices, SEC sectors, marts, dashboard export

# Launch API (localhost:8000/docs)
make serve
```

## Key Features

- **Bulk Form 4 backfill**: 12 years of SEC quarterly insider data sets loaded with Polars and COPY in minutes
- **EDGAR-compliant scraping**: User-Agent per SEC policy, 10 req/s ceiling, exponential backoff
- **Idempotent ingestion**: accession-number-based deduplication, amendment tracking
- **Dead-letter pipeline**: failed parses persisted with stack traces for replay
- **Cluster-buying screener**: companies with ≥3 insiders buying in 90 days
- **Holdings-change detection**: QoQ new positions, exits, increases, reductions per manager
- **Semantic search**: pgvector-powered risk-factor similarity across companies
- **10-K diff analyzer**: year-over-year risk-factor text changes summarized by local LLM
- **Weekly digest**: automated email with top signals

## Measured Backtest: Does Cluster Buying Work?

**Result (measured, Jan 2014 to May 2026, 5,395 signals):** following insider cluster buys did **not** reliably beat the market.

- Median excess return vs SPY after 180 days: **-3.9%**. Only **42.6%** of signals beat SPY (48.4% at 30 days, 44.4% at 90 days).
- Average excess return: **+1.5%**, but only because of a few huge winners (mostly biotech: Life Sciences averages +9.7% while its median is -9.6%).
- Against small caps (IWM) instead of SPY: median -2.2%, hit rate 46.2%.
- Stocks priced $5 or more only: median -3.8%, average -1.4%.
- The median signal lagged SPY in 12 of the 13 signal years (2016 was the exception).
- Coverage: 11,387 signals found in 5.28M Form 4 rows; 5,395 passed the data checks. The rest had no Yahoo price history (mostly delisted companies), no trading volume on the entry or exit day, an entry price more than 2x away from what the insiders paid, or were too recent for a 180-day window.

Takeaway: by the time a cluster of insider buys is public, most of the edge is gone. Full numbers: [`web/js/backtest_data.js`](web/js/backtest_data.js).


**How it is measured**

- **Data:** every original Form 4 in the SEC's quarterly insider transaction data sets since January 2014 (5.28M transaction rows, 2.32M filings, 11,958 companies), loaded by `sec_filings/ingestion/form345_bulk.py`. Amendments, Forms 3 and 5 are left out so no trade counts twice, and joint filings count once (first listed owner), so a fund and its affiliates can't fake a cluster.
- **Signal:** open-market purchases (Table I, code P). A cluster fires on the filing date when 3 or more distinct insiders filed buys worth $250K or more within the trailing 90 days. One signal per company per quarter (`int_cluster_buy_events`).
- **Data checks:** the stock must have traded (volume above zero) on the entry and 180-day exit days, and the entry price must be within 0.5x to 2x of the average price the insiders paid. This removes stale OTC quotes and broken Yahoo histories.
- **No look-ahead:** the window and the signal both use the filing date, the day the trade became public, not the trade date. Entry is the close of the next trading day.
- **Returns:** 30, 90 and 180-day total returns from split and dividend adjusted Yahoo Finance closes, minus SPY over the same window (`int_cluster_signal_returns`). Companies are priced under their current SEC ticker, so renamed tickers (FB to META) still match.
- **Sectors:** the SEC's own industry office for each company (EDGAR submissions `ownerOrg`), not MSCI GICS.

**Known biases, stated up front:** Yahoo has no prices for most delisted, acquired or bankrupt companies, so those signals drop out (survivorship bias, which flatters the result). No slippage, no transaction costs, equal weight. Descriptive, not a trading strategy, not investment advice.

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /insiders/{ticker}` | Insider transactions for a ticker |
| `GET /holdings/{manager_cik}` | Top holdings for an institutional manager |
| `GET /holdings/changes/{manager_cik}` | Quarter-over-quarter holding changes |
| `GET /screen/cluster-buying` | Cluster insider buying screen |
| `GET /screen/concentration` | Institutional ownership concentration |
| `GET /search/risk-similar/{ticker}` | Companies with similar risk profiles |
| `GET /search/diffs/{ticker}/{year}` | LLM-generated risk-factor diff |
| `GET /health` | Health check |

Full Swagger docs at `localhost:8000/docs`.

## Case Study Queries

### 1. Cluster Buying: "Who's buying their own stock?"
```bash
curl "localhost:8000/screen/cluster-buying?min_insiders=3&min_value=250000"
```

### 2. Hedge Fund Tracker: "What did Berkshire change?"
```bash
curl "localhost:8000/holdings/changes/1067983"
```

### 3. Risk Factor Similarity: "Who has risk factors like MRNA?"
```bash
curl "localhost:8000/search/risk-similar/MRNA?top_k=10"
```

## Data Dictionary

See [docs/data_dictionary.md](docs/data_dictionary.md) for complete table documentation.

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.12 |
| Package manager | uv |
| HTTP | httpx (async, HTTP/2) + tenacity (retries) |
| Parsing | lxml (XML), selectolax (HTML) |
| DataFrames | Polars |
| Embeddings | sentence-transformers (BAAI/bge-small-en-v1.5) |
| Local LLM | Ollama + Llama 3.1 8B Instruct |
| Database | PostgreSQL 16 + pgvector |
| Orchestration | Prefect 3 |
| Transformation | dbt-core 1.8+ |
| Migrations | Alembic |
| BI | Metabase OSS |
| API | FastAPI |
| Validation | Pydantic v2 |
| Containers | Docker Compose v2 |
| Quality | Ruff + mypy (strict) + pytest |
| CI | GitHub Actions |

## Development

```bash
make lint        # ruff check
make fmt         # ruff format + fix
make type-check  # mypy --strict
make test        # pytest with coverage
make ci          # all of the above
```

## License

MIT
