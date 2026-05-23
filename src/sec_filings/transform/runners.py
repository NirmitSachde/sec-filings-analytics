"""Programmatic dbt invocation."""

import subprocess
from pathlib import Path

_DBT_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "dbt"


def dbt_run(select: str | None = None) -> int:
    """Run dbt models."""
    cmd = ["dbt", "run", "--project-dir", str(_DBT_PROJECT_DIR)]
    if select:
        cmd.extend(["--select", select])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr)
    return result.returncode


def dbt_test(select: str | None = None) -> int:
    """Run dbt tests."""
    cmd = ["dbt", "test", "--project-dir", str(_DBT_PROJECT_DIR)]
    if select:
        cmd.extend(["--select", select])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr)
    return result.returncode


def dbt_build() -> int:
    """Run dbt build (run + test)."""
    cmd = ["dbt", "build", "--project-dir", str(_DBT_PROJECT_DIR)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr)
    return result.returncode
