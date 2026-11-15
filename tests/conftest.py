"""Project-wide pytest hooks."""

import pytest

# The opt-in markers from pyproject.toml. Selecting them is a deliberate choice.
OPT_IN_MARKERS = ("live", "db")


def _is_opt_in_selection(markexpr: str) -> bool:
    """True when `-m` asks for live or db tests (e.g. "live", "db", "live or db")."""
    return "not" not in markexpr.split() and any(m in markexpr.split() for m in OPT_IN_MARKERS)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Why: pytest exits with code 5 when nothing is selected. Until later tasks add
    # live/db tests, `pytest -m live` and `pytest -m db` select nothing, and an
    # "error" exit there would be misleading. We only relax this for those opt-in
    # runs: a plain `pytest` that finds zero tests is still a real problem and keeps code 5.
    markexpr = session.config.option.markexpr or ""
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED and _is_opt_in_selection(markexpr):
        session.exitstatus = pytest.ExitCode.OK
