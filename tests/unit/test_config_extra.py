"""Extra configuration tests: sync database URL and defaults."""

from sec_filings.config import get_settings


def test_database_url_sync(monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test App test@test.com")
    monkeypatch.setenv("POSTGRES_HOST", "sync.example.com")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_USER", "u1")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p1")
    monkeypatch.setenv("POSTGRES_DB", "db1")

    settings = get_settings()
    assert settings.database_url_sync == "postgresql+psycopg://u1:p1@sync.example.com:6543/db1"
    assert settings.database_url_sync == settings.database_url


def test_port_env_is_coerced_to_int(monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test App test@test.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("API_PORT", "9000")
    settings = get_settings()
    assert settings.smtp_port == 2525
    assert settings.api_port == 9000
