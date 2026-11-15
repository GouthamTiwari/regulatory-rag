# Task 03: Docker Postgres + schema
Branch: task/03-docker-postgres-schema | Date: 2026-11-16

## What changed
- `docker-compose.yml`: one `db` service on `pgvector/pgvector:pg17`.
  - Credentials come from `.env`. Compose refuses to start with a clear message if `POSTGRES_PASSWORD` is missing.
  - The port is published on `127.0.0.1` only (not the local network), on `POSTGRES_PORT` (default 5433).
  - A named volume keeps the data, and a `pg_isready` healthcheck reports when the database is ready.
- `src/regrag/db/schema.sql`: the four tables from SPEC section 4, with check constraints for corpus, status, content type, relation and source.
  - `tsv` is a stored generated column, so it can never drift from `content`.
  - Indexes: HNSW (cosine) on `embedding`, GIN on `tsv`, plus the B-tree indexes from the spec.
  - `chunks(doc_id)` is served by the `UNIQUE (doc_id, chunk_index)` index, which leads with `doc_id`, so no separate index was added.
  - Everything is `IF NOT EXISTS` and table names are unqualified, so the file runs repeatedly and inside any schema.
  - Additions beyond the spec: `CHECK (page_end >= page_start)`, and `to_doc_id ... ON DELETE SET NULL` (removing a target document clears the link instead of deleting the relation).
- `src/regrag/db/connection.py`: `connect(settings, schema=..., register_vector_type=..., autocommit=...)`.
  - The schema name is checked against a strict pattern, because it goes into a connection option (no SQL injection).
  - Connection failures become a friendly error naming host, port and `docker compose up -d`, never the password.
- `src/regrag/db/init.py`: `apply_schema(conn)` and `python -m regrag.db.init`.
- `tests/db/conftest.py`: a session fixture that creates a throw-away schema `test_<random>` and drops it afterwards. `db_conn` rolls back after each test. `insert_document()` is a helper.
- `tests/db/test_schema.py`: tests (see below).
- **Outside the task's file list:**
  - `src/regrag/config.py` (Task 02's file): `database_dsn()` now uses `127.0.0.1` instead of `localhost`. Why: on Windows, `localhost` tries IPv6 first and the container listens on IPv4 only, so every connection waited 5 s (measured 5.04 s vs 0.01 s). The db test run went from 56 s to 0.95 s.
  - `tests/test_config.py`: the expected DSN string was updated to match.
- Not committed: a local `.env` was created from `.env.example` with a randomly generated local-only DB password. It is gitignored. The AWS values are still empty, for Goutham to fill in.

## How to verify
- `docker compose up -d` → container `regrag-db` becomes healthy
- `uv run python -m regrag.db.init` twice → prints "Schema applied." both times
- `uv run pytest -m db` → 9 passed
- `uv run pytest` → 44 passed (db tests deselected)

## Tests
- `tests/db/test_schema.py`:
  - 9 `db` tests: tables exist; indexes exist (HNSW with cosine ops, GIN); schema applies twice; `tsv` filled automatically (stemming works); a 1024-dim vector round-trips; a 1023-dim vector is rejected; deleting a document deletes its chunks; bad corpus rejected; duplicate chunk index rejected.
  - 2 plain tests: invalid schema name rejected; connection-failure message hides the password (simulated, no network).
- Result: default run 44 passed; db run 9 passed; 0 failed. No leftover `test_%` schemas after the runs.

## Out of scope / follow-ups
- pgvector returns `pgvector.Vector` objects (use `.to_list()`), because numpy isn't installed. Tasks 13 and 16 should use `.to_list()` rather than expecting numpy arrays.
- The image tag `pg17` floats on pgvector minor versions (0.8.7 today). Pin it later if reproducibility matters.

## Review log
- Self-review: passed. All 3 acceptance criteria met; one performance bug found (IPv6 localhost delay) and fixed; no secrets in the diff.
