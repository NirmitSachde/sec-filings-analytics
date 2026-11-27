"""Tests for the weekly email digest (DB session and SMTP are mocked)."""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sec_filings.digest import weekly

_CHAIN = ("filter", "group_by", "having", "order_by", "limit", "distinct")


def _query(rows):
    q = MagicMock()
    for name in _CHAIN:
        getattr(q, name).return_value = q
    q.all.return_value = rows
    return q


def _session(cluster_rows, diff_rows):
    session = MagicMock()
    session.query.side_effect = [_query(cluster_rows), _query(diff_rows)]
    return session


def _cluster(ticker, name, n, total):
    return SimpleNamespace(issuer_ticker=ticker, issuer_name=name, n_insiders=n, total_value=total)


def _settings(**overrides):
    base = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 2525,
        "smtp_user": "bot@example.com",
        "smtp_password": "pw",
        "digest_recipients": "a@example.com, b@example.com",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_digest_html_renders_clusters_and_diffs(monkeypatch):
    session = _session(
        [
            _cluster("AAPL", "Apple Inc", 3, 1_725_000.4),
            _cluster(None, "Private Co", 2, None),
        ],
        [
            SimpleNamespace(issuer_cik=320193, year=2024),
            SimpleNamespace(issuer_cik=789019, year=2023),
        ],
    )
    monkeypatch.setattr(weekly, "get_session", lambda: session)

    html = weekly.build_digest_html.fn()

    assert "SEC Filings Weekly Digest" in html
    assert f"Week ending {datetime.date.today().isoformat()}" in html
    assert ">AAPL<" in html
    assert "Apple Inc" in html
    assert "$1,725,000" in html
    assert ">3<" in html
    # Missing ticker and missing total value both fall back to N/A.
    assert html.count(">N/A<") == 2
    assert "Private Co" in html
    assert "CIK 320193</strong> (2024)" in html
    assert "CIK 789019</strong> (2023)" in html
    assert "No recent risk factor diffs" not in html
    # Rows keep the query order (most insiders first).
    assert html.index("Apple Inc") < html.index("Private Co")
    assert html.strip().endswith("</html>")
    session.close.assert_called_once()


def test_build_digest_html_cluster_query_filters(monkeypatch):
    session = _session([], [])
    monkeypatch.setattr(weekly, "get_session", lambda: session)

    weekly.build_digest_html.fn()

    assert session.query.call_count == 2
    # Ticker, name, distinct-insider count and total value.
    cluster_q = session.query.call_args_list[0]
    assert len(cluster_q.args) == 4
    diff_q = session.query.call_args_list[1]
    assert diff_q.args == (weekly.RiskFactorDiff,)


def test_build_digest_html_limits_requested(monkeypatch):
    cluster_q = _query([])
    diff_q = _query([])
    session = MagicMock()
    session.query.side_effect = [cluster_q, diff_q]
    monkeypatch.setattr(weekly, "get_session", lambda: session)

    weekly.build_digest_html.fn()

    cluster_q.limit.assert_called_once_with(10)
    diff_q.limit.assert_called_once_with(5)
    # Four filter conditions: code P, date window, non-null shares, non-null price.
    assert len(cluster_q.filter.call_args.args) == 4


def test_build_digest_html_empty_results(monkeypatch):
    session = _session([], [])
    monkeypatch.setattr(weekly, "get_session", lambda: session)

    html = weekly.build_digest_html.fn()

    assert "No recent risk factor diffs available." in html
    assert "CIK" not in html
    assert "$" not in html
    session.close.assert_called_once()


def test_build_digest_html_closes_session_on_error(monkeypatch):
    session = MagicMock()
    session.query.side_effect = RuntimeError("db down")
    monkeypatch.setattr(weekly, "get_session", lambda: session)

    with pytest.raises(RuntimeError, match="db down"):
        weekly.build_digest_html.fn()
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "overrides",
    [{"smtp_host": ""}, {"digest_recipients": ""}, {"smtp_host": "", "digest_recipients": ""}],
)
def test_send_digest_skips_when_not_configured(monkeypatch, capsys, overrides):
    smtp = MagicMock()
    monkeypatch.setattr(weekly.smtplib, "SMTP", smtp)
    monkeypatch.setattr(weekly, "get_settings", lambda: _settings(**overrides))

    assert weekly.send_digest.fn("<p>hello digest</p>") is False

    out = capsys.readouterr().out
    assert "SMTP not configured" in out
    assert "<p>hello digest</p>" in out
    smtp.assert_not_called()


def test_send_digest_sends_via_smtp(monkeypatch):
    smtp_cls = MagicMock()
    server = smtp_cls.return_value.__enter__.return_value
    monkeypatch.setattr(weekly.smtplib, "SMTP", smtp_cls)
    monkeypatch.setattr(weekly, "get_settings", lambda: _settings())

    assert weekly.send_digest.fn("<h1>Digest body</h1>") is True

    smtp_cls.assert_called_once_with("smtp.example.com", 2525)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("bot@example.com", "pw")
    server.send_message.assert_called_once()

    msg = server.send_message.call_args.args[0]
    assert msg["Subject"].endswith(datetime.date.today().isoformat())
    assert msg["Subject"].startswith("SEC Filings Weekly Digest")
    assert msg["From"] == "bot@example.com"
    assert msg["To"] == "a@example.com, b@example.com"
    assert msg.get_content_subtype() == "alternative"
    parts = msg.get_payload()
    assert len(parts) == 1
    assert parts[0].get_content_type() == "text/html"
    assert "<h1>Digest body</h1>" in parts[0].get_payload(decode=True).decode()
    # starttls must happen before credentials go over the wire.
    names = [c[0] for c in server.method_calls]
    assert names.index("starttls") < names.index("login") < names.index("send_message")


def test_run_weekly_digest_wires_build_into_send(monkeypatch):
    calls = []

    def fake_build():
        calls.append("build")
        return "<html>built</html>"

    def fake_send(html):
        calls.append(("send", html))
        return True

    monkeypatch.setattr(weekly, "build_digest_html", fake_build)
    monkeypatch.setattr(weekly, "send_digest", fake_send)

    assert weekly.run_weekly_digest.fn() is True
    assert calls == ["build", ("send", "<html>built</html>")]


def test_run_weekly_digest_propagates_skip(monkeypatch):
    monkeypatch.setattr(weekly, "build_digest_html", lambda: "x")
    monkeypatch.setattr(weekly, "send_digest", lambda html: False)
    assert weekly.run_weekly_digest.fn() is False
