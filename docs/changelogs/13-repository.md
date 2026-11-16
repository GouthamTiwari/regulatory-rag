# Task 13: Repository (database reads and writes)
Branch: task/13-repository | Date: 2026-11-16

## What changed
- `src/regrag/db/repository.py`. Every value goes in as a query parameter (no SQL injection).
  - **Documents and chunks:**
    - `upsert_document(conn, row, chunks, page_count, embedding_model)` inserts or updates the document and *replaces* all its chunks in one transaction.
    - `insert_chunks` writes all chunks, with their vectors, in one batch.
    - `document_state` returns (sha256, embedding_model) so Task 14 can skip unchanged documents.
  - **Lookups:**
    - `get_documents(doc_ids)`.
    - `get_chunks(chunk_ids)` returns chunks in the order requested, joined with their document.
    - `top_chunk_for_document(doc_id, query_embedding)` finds the nearest chunk by cosine.
  - **Relations:**
    - `replace_relations(doc_id, relations, source="extracted")` re-ingests one document's extracted links without touching manual ones.
    - `load_manual_relations` replaces all `source='manual'` rows.
    - `get_relations_for(doc_ids)` returns links in **both directions**.
    - `to_doc_ref` is **resolved to `to_doc_id`** by comparing `normalise_ref` (imported from Task 09, already merged) with each stored document's `reference_no`.
  - **Logs:** `insert_query_log(QueryResult)` stores arrays as Postgres arrays and citations, latencies and model IDs as JSON.
  - **Shared helpers:** `RETRIEVED_COLUMNS` and `row_to_retrieved`, so the retrievers (Tasks 15/16) build `RetrievedChunk` the same way.
- `tests/db/test_repository.py`: tests (see below).
- `tests/db/conftest.py` (**Task 03's file, outside this task's list**): `db_conn` now opens the outer transaction before the test runs. Without it, `conn.transaction()` inside the code under test started and *committed* a real transaction, and the data leaked into later tests (5 schema tests failed on duplicate keys). Now every write is a savepoint that the fixture rolls back.

## How to verify
- `uv run pytest -m db` → 16 passed (7 new + 9 schema), also in a second run (no leftovers).

## Tests
- 7 db tests: re-upsert leaves exactly the new chunks (and `document_state` reports them); a failure midway (a wrong-size vector) keeps the old chunks; relations found from both sides, with a messy reference spelling resolved to the corpus document; extracted re-ingest leaves manual links alone; `get_chunks` keeps order and joins the document; nearest chunk for a document (`None` when absent); query log round-trip (arrays, JSON, numeric cost).
- Full suite: 253 passed + 16 db passed, 0 failed.

## Out of scope / follow-ups
- None.

## Review log
- Self-review: passed. All 4 acceptance criteria met. A test-isolation bug was found and fixed in the shared db fixture.
