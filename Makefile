.PHONY: up down build test lint type-check fmt ci migrate dbt-run ingest backfill-form4 backtest

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ --cov=sec_filings --cov-report=html

lint:
	uv run ruff check src/ tests/

fmt:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

type-check:
	uv run mypy src/sec_filings/

ci: lint type-check test

migrate:
	uv run alembic upgrade head

migrate-new:
	uv run alembic revision --autogenerate -m "$(msg)"

dbt-run:
	cd dbt && dbt run

dbt-test:
	cd dbt && dbt test

dbt-build:
	cd dbt && dbt build

ingest-index:
	uv run python -m sec_filings.ingestion.index_flow

ingest-filings:
	uv run python -m sec_filings.ingestion.filing_flow

embed:
	uv run python -m sec_filings.embeddings.encoder

serve:
	uv run uvicorn sec_filings.api.main:app --reload --host 0.0.0.0 --port 8000

install:
	uv sync --all-extras

# ---- Measured cluster-buy backtest (real data) ----
# 1. download the SEC quarterly insider data sets into data/raw/form345 (see scripts/download_form345.sh)
# 2. load Form 4 rows, map tickers, find events, price them, classify sectors, export to the dashboard
backfill-form4:
	bash scripts/download_form345.sh
	uv run python -m sec_filings.ingestion.form345_bulk data/raw/form345

backtest:
	uv run python -m sec_filings.ingestion.security_master tickers
	cd dbt && DBT_PROFILES_DIR=. uv run dbt run --select +int_cluster_buy_events
	uv run python -m sec_filings.ingestion.price_flow
	uv run python -m sec_filings.ingestion.security_master sectors
	cd dbt && DBT_PROFILES_DIR=. uv run dbt run --select +mart_signal_validation
	uv run python scripts/export_backtest.py
