"""Tests for configuration and settings."""

import os

import pytest

from sec_filings.config import UserAgentNotConfiguredError, get_settings


def test_get_settings_with_env(monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test App test@test.com")
    settings = get_settings()
    assert settings.edgar_user_agent == "Test App test@test.com"


def test_get_settings_missing_user_agent(monkeypatch):
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    with pytest.raises(UserAgentNotConfiguredError):
        get_settings()


def test_get_settings_empty_user_agent(monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "   ")
    with pytest.raises(UserAgentNotConfiguredError):
        get_settings()


def test_database_url(monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test App test@test.com")
    monkeypatch.setenv("POSTGRES_HOST", "db.example.com")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_USER", "myuser")
    monkeypatch.setenv("POSTGRES_PASSWORD", "mypass")
    monkeypatch.setenv("POSTGRES_DB", "mydb")

    settings = get_settings()
    assert "db.example.com:5433/mydb" in settings.database_url
    assert "myuser:mypass" in settings.database_url
