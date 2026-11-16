# Task 14: Ingest pipeline (end to end)
Branch: task/14-ingest-pipeline | Date: 2026-11-16

## What changed
- `src/regrag/ingest/pipeline.py`: `python -m regrag.ingest.pipeline [--only] [--limit] [--skip-download] [--dry-run]`.
  - **Per document:** download (unless skipped) → sha256 → skip if the hash and embedding model are unchanged → parse → chunk → extract relations → embed (title + section path + text) → store the document, its chunks and its extracted links in **one transaction**.
  - **Failures:** one failing document is reported and skipped; the exit code is 1 if any failed.
  - **`--dry-run`** makes no Bedrock calls and no database writes, and prints the estimated cost.
  - **After the run:** manual relations are reloaded (only those whose documents exist), `resolve_relation_targets` links targets stored later, the sha256 values are written into `data/manifest.csv` (that column only), and the extracted relations go to `data/raw/extracted_relations.csv` (gitignored) for human review.
  - Dependencies are passed in through `Deps`, so tests run with fakes.
- `src/regrag/db/repository.py` (Task 13's file): adds `resolve_relation_targets(conn)`, which fills `to_doc_id` for links whose target document was stored after the link.
- **Throttling fixes found by the real run** (Task 04/10 files and config):
  - **Root cause, measured:** this new account's Titan quota in Mumbai throttles *bursts*. With real ~300-token chunks, a steady **1 call per second gave 0 throttles in 60 calls**; 4 parallel unpaced calls were throttled within seconds.
  - `src/regrag/bedrock/client.py`: retry mode changed from `adaptive` to `standard` (8 attempts). The first ingest froze after 3 documents because botocore's adaptive client-side rate limiter (`retries/bucket.py`) starved all threads once throttling began. This was diagnosed with a `faulthandler` stack dump.
  - `src/regrag/bedrock/embedder.py`: a thread-safe `_Pacer` spaces **every attempt, retries included**, at `embed_requests_per_second`. An unpaced retry is itself a burst.
  - `src/regrag/config.py`: new setting `embed_requests_per_second = 1.0`, with its reason. Raise it once AWS grants a higher quota.
  - `tests/bedrock/test_client.py`: now checks for `standard` mode. `tests/bedrock/test_embedder.py`: new pacer spacing test.
- `tests/ingest/test_pipeline.py`: tests (see below).

## How to verify
- `uv run python -m regrag.ingest.pipeline --skip-download --dry-run` → 65 documents, 2,265 chunks, 251 tables, 691,204 estimated embedding tokens, **$0.0166**, 61 extracted relations.
- `uv run pytest tests/ingest/test_pipeline.py` → 6 passed
- Real run results: recorded below once the paced run completes.

## Tests
- 6 tests with fakes (no AWS, no database): 2 documents → upsert/relations calls in order, everything embedded before storing; a parse failure in one document doesn't stop the other; an unchanged document is skipped on the second run with no second embed call and $0; a missing PDF is reported; a dry run estimates cost and stores nothing; the manifest hash update changes only that column and is idempotent.
- Full suite: 311 passed, 0 failed.

## Out of scope / follow-ups
- The extracted relations in `data/raw/extracted_relations.csv` await Goutham's review. Reviewed ones can be appended to `data/relations.csv`.
- If AWS raises the Titan quota, set `EMBED_REQUESTS_PER_SECOND` higher in `.env`.

## Review log
- Self-review: passed for all unit-testable criteria. The real run exposed a throttling freeze and an unpaced-retry problem; both were fixed, measured and documented above.
