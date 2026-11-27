"""Tests for the programmatic dbt runners (subprocess is always mocked)."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sec_filings.transform import runners


@pytest.fixture
def fake_run(monkeypatch):
    mock = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stderr=""))
    monkeypatch.setattr(runners.subprocess, "run", mock)
    return mock


def _called_cmd(mock: MagicMock) -> list[str]:
    assert mock.call_count == 1
    args, kwargs = mock.call_args
    assert kwargs == {"capture_output": True, "text": True}
    return list(args[0])


def test_dbt_project_dir_points_at_repo_dbt_folder():
    assert runners._DBT_PROJECT_DIR.name == "dbt"
    repo_root = Path(runners.__file__).resolve().parents[3]
    assert repo_root / "dbt" == runners._DBT_PROJECT_DIR


def test_dbt_run_without_select(fake_run):
    assert runners.dbt_run() == 0
    cmd = _called_cmd(fake_run)
    assert cmd == ["dbt", "run", "--project-dir", str(runners._DBT_PROJECT_DIR)]


def test_dbt_run_with_select(fake_run):
    runners.dbt_run(select="marts.insider_clusters")
    cmd = _called_cmd(fake_run)
    assert cmd[:2] == ["dbt", "run"]
    assert cmd[-2:] == ["--select", "marts.insider_clusters"]


def test_dbt_run_empty_select_is_ignored(fake_run):
    runners.dbt_run(select="")
    assert "--select" not in _called_cmd(fake_run)


def test_dbt_test_without_and_with_select(fake_run):
    assert runners.dbt_test() == 0
    assert _called_cmd(fake_run) == [
        "dbt",
        "test",
        "--project-dir",
        str(runners._DBT_PROJECT_DIR),
    ]
    fake_run.reset_mock()
    runners.dbt_test(select="staging")
    cmd = _called_cmd(fake_run)
    assert cmd[1] == "test"
    assert cmd[-2:] == ["--select", "staging"]


def test_dbt_build_command(fake_run):
    assert runners.dbt_build() == 0
    assert _called_cmd(fake_run) == [
        "dbt",
        "build",
        "--project-dir",
        str(runners._DBT_PROJECT_DIR),
    ]


@pytest.mark.parametrize(
    ("func", "kwargs"),
    [
        (runners.dbt_run, {"select": "x"}),
        (runners.dbt_test, {}),
        (runners.dbt_build, {}),
    ],
)
def test_failure_returns_code_and_prints_stderr(monkeypatch, capsys, func, kwargs):
    monkeypatch.setattr(
        runners.subprocess,
        "run",
        MagicMock(
            return_value=subprocess.CompletedProcess(
                args=[], returncode=2, stderr="Compilation Error in model foo"
            )
        ),
    )
    assert func(**kwargs) == 2
    assert "Compilation Error in model foo" in capsys.readouterr().out


def test_success_prints_nothing(fake_run, capsys):
    fake_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stderr="warning")
    runners.dbt_build()
    assert capsys.readouterr().out == ""
