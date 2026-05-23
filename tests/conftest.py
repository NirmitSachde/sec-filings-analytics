import os
from pathlib import Path

import pytest

os.environ.setdefault("EDGAR_USER_AGENT", "SECFilingsAnalytics Test test@test.com")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "sec_filings")
os.environ.setdefault("POSTGRES_PASSWORD", "sec_filings_dev")
os.environ.setdefault("POSTGRES_DB", "sec_filings_test")

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "filings"
