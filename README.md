# SEC Filings Analytics Platform

A data engineering + analytics platform that ingests SEC EDGAR filings (Form 4, 13F-HR, 10-K/10-Q), normalizes them into a queryable warehouse, and surfaces insights through Metabase dashboards, a FastAPI REST service, and a static web dashboard.

**Stack:** Python 3.12 · PostgreSQL 16 + pgvector · Prefect 3 · dbt-core · FastAPI · Metabase · Ollama (Llama 3.1 8B)

**🌐 Live demo:** **https://nirmitsachde.github.io/sec-filings-analytics/** — Bloomberg-style analytics terminal with cluster-buying screener, hedge-fund tracker, ownership concentration, and risk-factor drift visualizations.

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
 dbt-core: staging → intermediate → marts (25+ models)
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

# Launch API (localhost:8000/docs)
make serve
```

## Key Features

- **EDGAR-compliant scraping** — User-Agent per SEC policy, 10 req/s ceiling, exponential backoff
- **Idempotent ingestion** — accession-number-based deduplication, amendment tracking
- **Dead-letter pipeline** — failed parses persisted with stack traces for replay
- **Cluster-buying screener** — companies with ≥3 insiders buying in 90 days
- **Holdings-change detection** — QoQ new positions, exits, increases, reductions per manager
- **Semantic search** — pgvector-powered risk-factor similarity across companies
- **10-K diff analyzer** — year-over-year risk-factor text changes summarized by local LLM
- **Weekly digest** — automated email with top signals

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

### 1. Cluster Buying — "Who's buying their own stock?"
```bash
curl "localhost:8000/screen/cluster-buying?min_insiders=3&min_value=250000"
```

### 2. Hedge Fund Tracker — "What did Berkshire change?"
```bash
curl "localhost:8000/holdings/changes/1067983"
```

### 3. Risk Factor Similarity — "Who has risk factors like MRNA?"
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
