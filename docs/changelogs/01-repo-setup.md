# Task 01: Repo setup
Branch: task/01-repo-setup | Date: 2026-11-16

## What changed
- `pyproject.toml`: uv project `regrag` (Python 3.12, `src/` layout, `uv_build` backend). Installs every runtime dependency the spec needs up front, so later tasks never edit this file. Dev group: `ruff`, `pytest`, `fpdf2` (Task 07's fixture PDF). Ruff: line length 100, rules E, F, I, UP, B. The formatter skips `*.md`, because this ruff version also reformats code snippets inside Markdown and would rewrite the illustrative code in `docs/SPEC.md`. Pytest: `live` and `db` markers, which plain `pytest` skips by default.
- `uv.lock`, `.python-version`: pin exact dependency versions and Python 3.12, so every checkout installs the same thing.
- `.gitignore`: extended (not replaced) with `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`.
- `.env.example`: all 13 variables from the task, every value empty, with a comment per variable giving the recommended value and saying "set only one auth option".
- `README.md`: skeleton with the 7 required headings only.
- `src/regrag/__init__.py`: package marker with `__version__`.
- `tests/__init__.py`, `tests/test_smoke.py`: the package imports; `.env.example` lists exactly the 13 variables and has no values; `-m live` / `-m db` runs succeed with zero tests.
- `tests/conftest.py` (**not in the task's file list**): a small `pytest_sessionfinish` hook. Why: pytest exits with code 5 ("no tests collected") when `-m live` or `-m db` selects nothing, which the acceptance criteria count as an error. The hook turns code 5 into 0 only for those opt-in marker runs; any other empty run still reports code 5 (tested).

## How to verify
- `uv sync` → exit 0
- `uv run python -c "import regrag, fpdf"` → no error
- `uv run ruff check .` and `uv run ruff format --check .` → both pass
- `uv run pytest` → 12 passed
- `uv run pytest -m live` and `uv run pytest -m db` → "12 deselected", exit 0
- `git check-ignore .env data/raw/x.pdf .venv` → prints all three paths

## Tests
- `tests/test_smoke.py`: 12 tests (import, env template contents, empty values, marker-selection helper, opt-in exit codes, narrow-hook guard), result: 12 passed, 0 failed.

## Out of scope / follow-ups
- An earlier attempt was stopped part-way; the work was then finished, checked and committed.
- The opt-in exit-code tests run pytest in a subprocess (~4 s). They're acceptable for now, and can be removed once real `live`/`db` tests exist.

## Review log
- Self-review: passed. Every acceptance criterion was checked; one ruff-format issue (Markdown snippets) was fixed before commit; no secrets in the diff.
