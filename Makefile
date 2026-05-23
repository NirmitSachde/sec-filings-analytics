.PHONY: up down build test lint type-check fmt ci migrate dbt-run ingest

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
