# Task 15: Keyword retriever ("BM25-like" leg)
Branch: task/15-keyword-retriever | Date: 2026-11-16

## What changed
- `src/regrag/retrieval/keyword.py`: `KeywordRetriever(conn)` (implements `Retriever`).
  - `websearch_to_tsquery('english', q)` matched against `chunks.tsv` (GIN index), ranked by `ts_rank_cd`; ties broken by `chunk_id`.
  - Route filter through a join on `documents.corpus`.
  - If the strict all-words search finds fewer than 5 rows, it searches again with any-word matching (`a or b or c`) and adds new hits up to `top_k`.
  - Sets `keyword_score` and 1-based `keyword_rank`.
  - All values are query parameters, and `websearch_to_tsquery` never raises on odd punctuation.
- `tests/retrieval/test_keyword.py`: tests (see below).
- `tests/conftest.py` (**Task 01's file, outside this task's list**): imports the db fixtures (`db_conn`, `db_schema`) from `tests/db/conftest.py`. Without it, db tests outside `tests/db/` can't see them.

## How to verify
- `uv run pytest -m db tests/retrieval/test_keyword.py` → 9 passed

## Tests
- 9 db tests: the exact circular number `231/25/2024-GST` ranks first; route `gst` never returns RBI; no matching terms gives `[]`, and so does a blank question; 3 punctuation and quote variants don't raise; a natural question falls back to any-word matching; `any_word_query`; protocol check.

## Out of scope / follow-ups
- This is Postgres ranking, not exact BM25 (SPEC decision 5); results label it "keyword (Postgres FTS, BM25-like)".

## Review log
- Self-review: passed. All 4 acceptance criteria met.
