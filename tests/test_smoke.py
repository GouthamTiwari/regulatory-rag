"""Smoke tests: the package imports, and the project scaffolding keeps its promises."""

import subprocess
import sys
from pathlib import Path

import pytest

import regrag
from tests.conftest import _is_opt_in_selection

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every variable Task 01 promises in .env.example. Later code reads these names.
EXPECTED_ENV_VARS = [
    "AWS_REGION",
    "BEDROCK_RERANK_REGION",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "BEDROCK_EMBED_MODEL_ID",
    "BEDROCK_RERANK_MODEL_ID",
    "BEDROCK_LLM_MODEL_ID",
    "BEDROCK_JUDGE_MODEL_ID",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_PORT",
    "DATABASE_URL",
]


def _env_example_assignments() -> dict[str, str]:
    """Return {name: value} for every non-comment line in .env.example."""
    assignments = {}
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, value = stripped.partition("=")
        assignments[name.strip()] = value
    return assignments


def test_package_imports():
    assert regrag.__version__


def test_env_example_lists_every_variable():
    assert list(_env_example_assignments()) == EXPECTED_ENV_VARS


def test_env_example_has_no_values():
    # Why: a value here would be committed to git; a real key would leak.
    filled = {name: value for name, value in _env_example_assignments().items() if value}
    assert filled == {}


@pytest.mark.parametrize(
    ("markexpr", "expected"),
    [
        ("live", True),
        ("db", True),
        ("live or db", True),
        ("not live and not db", False),
        ("", False),
        ("slow", False),
    ],
)
def test_is_opt_in_selection(markexpr, expected):
    assert _is_opt_in_selection(markexpr) is expected


def _collect_only(markexpr: str) -> subprocess.CompletedProcess:
    # --collect-only so this never actually calls Bedrock or Postgres, even once
    # later tasks add live/db tests. We only look at the exit code.
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-m", markexpr, "--collect-only", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("marker", ["live", "db"])
def test_opt_in_marker_runs_succeed_when_empty(marker):
    result = _collect_only(marker)
    assert result.returncode == 0, result.stdout + result.stderr


def test_other_empty_selections_still_report_no_tests():
    # The conftest hook must stay narrow: an empty non-opt-in run is still exit code 5.
    result = _collect_only("no_such_marker")
    assert result.returncode == pytest.ExitCode.NO_TESTS_COLLECTED, result.stdout + result.stderr
