# Task 30: Web page (Streamlit)
Branch: task/30-web-ui | Date: 2026-11-18

## What changed
- `src/regrag/ui/view.py` (new): turns a `QueryResult` into display pieces: source cards (title, "section | pages", official link, superseded flag), a plain-English reason for a refusal, and time/cost/route stats. No Streamlit import, so it is unit-tested like the rest of the code.
- `src/regrag/ui/app.py` (new): the Streamlit page. Question box, example questions (in an expander on the main page, because narrow screens collapse the sidebar), search-setup dropdown with the four eval configs, the answer, a refusal warning, "Rule changed" notes, source cards with a "superseded" badge, and time/cost. The pipeline parts are built once per setup (`st.cache_resource`) and questions run one at a time behind a lock (one shared DB connection; rerank quota of 2/min).
- `src/regrag/ui/__init__.py`, `tests/ui/__init__.py` (new): package files.
- `pyproject.toml`, `uv.lock`: add `streamlit` (1.67.0).
- `README.md`: web page in Usage, `ui/` in the layout, test count 342, limitation line now about local single-user use.
- `docs/SPEC.md`: non-goal line now says the web page was added after v1. `docs/TASKS.md`: Task 30 entry (scope change agreed by the owner on 2026-11-16).

## How to verify
- `docker compose up -d` then `uv run streamlit run src/regrag/ui/app.py` → page at http://localhost:8501.
- Pick the 2020 PSL example and click Ask → answer citing the 2025 directions, a "Rule changed" note, a "superseded" badge on the 2020 source, route RBI, cost about $0.0017. (Checked live on 2026-11-18: 3.1 s, $0.00169.)

## Tests
- `tests/ui/test_view.py` (7 new): page labels, source cards, stats, refusal wording, labels for every config, and two runs of the real page script with Streamlit's `AppTest` and the pipeline mocked (answer path, refusal path).
- Full suite: 342 passed, 36 deselected (live/db). Ruff check and format clean.

## Out of scope / follow-ups
- No screenshot in the README yet (add one by hand from the running page).
- Not built for many users at once: one shared DB connection, no login, no rate limiting. Fine for a local demo.

## Review log
- Self-review: read the full diff. Found and fixed during the task: the examples were in the sidebar, which collapses on narrow screens (moved to the main page); the smoke test clicked the wrong button (now found by label); an abstain label for a reason code the validator never produces was removed. No secrets, no `data/raw/`, no AWS resources created, Bedrock mocked in tests.
