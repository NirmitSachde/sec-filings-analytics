"""Unit tests for the parse-failure dead-letter writer."""

from unittest.mock import MagicMock

from sec_filings.ingestion import deadletter
from sec_filings.models import ParseFailure


def _raise_and_record(session_mock, monkeypatch):
    monkeypatch.setattr(deadletter, "get_session", lambda: session_mock)
    try:
        raise ValueError("bad xml at line 3")
    except ValueError as exc:
        deadletter.record_parse_failure("0000320193-24-000001", "4", exc, "0.1.0")


def test_record_parse_failure_stores_exception_details(monkeypatch):
    session = MagicMock()
    _raise_and_record(session, monkeypatch)

    session.add.assert_called_once()
    failure = session.add.call_args.args[0]
    assert isinstance(failure, ParseFailure)
    assert failure.accession_number == "0000320193-24-000001"
    assert failure.form_type == "4"
    assert failure.exception_class == "ValueError"
    assert failure.parser_version == "0.1.0"
    assert "ValueError: bad xml at line 3" in failure.traceback
    assert "Traceback" in failure.traceback
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.close.assert_called_once()


def test_record_parse_failure_swallows_db_errors(monkeypatch):
    session = MagicMock()
    session.commit.side_effect = RuntimeError("db down")
    _raise_and_record(session, monkeypatch)  # must not raise

    session.rollback.assert_called_once()
    session.close.assert_called_once()


def test_record_parse_failure_outside_except_block(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(deadletter, "get_session", lambda: session)
    deadletter.record_parse_failure("A", "10-K", KeyError("k"), "0.1.0")
    failure = session.add.call_args.args[0]
    assert failure.exception_class == "KeyError"
    # No active exception: format_exc() reports none.
    assert failure.traceback.strip() == "NoneType: None"
