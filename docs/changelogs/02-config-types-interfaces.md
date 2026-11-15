# Task 02: Config, shared types, interfaces
Branch: task/02-config-types-interfaces | Date: 2026-11-16

## What changed
- `src/regrag/config.py`: one `Settings` class (pydantic-settings) with every SPEC section 5 parameter at its start value, the region and model IDs from SPEC section 2, and the allowed download hosts. Each has a one-line "why" comment. `load_dotenv()` runs at import, because boto3 only reads the process environment. Empty values (`NAME=`) fall back to defaults (`env_ignore_empty`), so the judge model defaults to Haiku when `BEDROCK_JUDGE_MODEL_ID` is empty. Secrets are `SecretStr`, so they print as `**********`. A validator rejects impossible combinations (overlap ≥ target, rerank_top_n > fused_top_k). `database_dsn()` builds the Postgres connection string. `get_settings()` returns the one shared, cached object.
- `src/regrag/types.py`: the 13 dataclasses from the task plus `Route`. Additions beyond the task list:
  - `ChunkRef`: chunk ID, doc ID and section. `QueryResult.retrieved` / `.reranked` hold the ranked lists, so the eval can compute recall and MRR without a database.
  - Small `Literal` aliases: `Corpus`, `ContentType`, `DocStatus`, `RelationType`, `ConfigName`.
  - `QueryResult.to_dict()` / `from_dict()`. `from_dict` ignores unknown keys, so the schema can grow without breaking old readers.
  - `PipelineConfig`: validates its name, exposes `uses_keyword` / `uses_vector` / `uses_rerank`, and carries optional replacement parts plus a `validators` list (the guardrails plug-in point).
- `src/regrag/interfaces.py`: the six Protocols from SPEC section 7, marked `runtime_checkable`. The only difference from the SPEC text is line wrapping, to fit ruff's 100-character limit.
- `src/regrag/{bedrock,db,ingest,retrieval,query,eval}/__init__.py`, `tests/{same six}/__init__.py`: package markers, created once here so parallel tasks never collide on them.
- `tests/fakes.py`: fakes for all six Protocols (each records `.calls`), plus a `make_chunk()` factory.
- `tests/test_config.py`, `tests/test_types.py`: tests (see below).

## How to verify
- `uv run pytest` → 42 passed
- `uv run ruff check .` and `uv run ruff format --check .` → pass

## Tests
- `test_config.py` (14): import with no `.env` in a fresh interpreter; defaults; empty values fall back; env overrides; bearer token and DB password masked in `repr`/`str`/`model_dump`; DSN building; invariants; 5 bad-value cases rejected.
- `test_types.py` (16): `QueryResult` JSON round-trip; unknown fields ignored; `Usage` addition; config flags for all 4 names; bad config name rejected; all 6 fakes pass `isinstance` against their Protocol; behaviour of the fake embedder, retriever and reranker.
- Result: 42 passed (12 existing + 30 new), 0 failed.

## Out of scope / follow-ups
- If `.env` contains `AWS_BEARER_TOKEN_BEDROCK=` (empty), `load_dotenv()` puts an empty variable into the process environment. Task 04's `get_runtime_client` should treat empty as "not set" when choosing the auth option.
- `allowed_download_hosts` lists base domains. Task 05's validator must accept their subdomains (for example `www.rbi.org.in`) and nothing else (not `rbi.org.in.evil.com`).

## Review log
- Self-review: passed. All 4 acceptance criteria met; no files outside the task list; no secrets in the diff (test tokens are obviously fake strings).
