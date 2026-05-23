FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY dbt/ dbt/

ENV PYTHONPATH=/app/src
EXPOSE 8000

CMD ["uvicorn", "sec_filings.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
