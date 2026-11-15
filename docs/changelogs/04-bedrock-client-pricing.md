# Task 04: Bedrock client + pricing
Branch: task/04-bedrock-client-pricing | Date: 2026-11-16

## What changed
- `src/regrag/bedrock/client.py`:
  - `auth_mode(settings)` picks Option A (Bedrock API key) or Option B (IAM keys). It refuses both at once, half an IAM key, or nothing at all, with errors that name env vars but never their values.
  - `get_runtime_client(settings)` returns a `bedrock-runtime` client cached per (region, auth mode), with adaptive retries (6 attempts) and a 120 s read timeout.
  - **Bug guarded against:** botocore treats an *empty* `AWS_BEARER_TOKEN_BEDROCK` (exactly what an unfilled `.env` line creates) as "a token exists" (`is not None` in `botocore/handlers.py`). In IAM mode the client removes the empty variable. In API-key mode it puts the trimmed key from Settings into the environment, because boto3 only reads it from there.
  - `clear_client_cache()` resets the cache for tests.
- `src/regrag/bedrock/pricing.py`:
  - The `PRICES` table (Tokyo, USD) covers the v1 Amazon models (Titan V2, Amazon Rerank 1.0, Nova 2 Lite `global.` and `jp.`, Nova Pro `apac.`) and the upgrade-path models (Cohere Rerank 3.5, Claude Haiku 5.5, Sonnet 5.5).
  - `PRICES_CHECKED_ON = 2026-11-16`.
  - `cost_usd(model_id, input_tokens, output_tokens, rerank_queries)`. An unknown model raises `UnknownModelPriceError` instead of costing $0, and negative counts raise.
- `tests/bedrock/test_client.py`, `tests/bedrock/test_pricing.py`, `tests/bedrock/test_live_auth.py`: tests (see below).

## How to verify
- `uv run pytest` → 65 passed
- `uv run pytest -m live tests/bedrock/test_live_auth.py -s` → with no key in `.env`: 1 skipped with a clear reason. With a key: 1 passed, and it prints auth mode, region, model, reply, tokens, latency and cost (never the key).

## Tests
- `test_client.py` (8, boto3 replaced by a spy, no network): no credentials; both options set (no values leaked); half an IAM key; whitespace-only token; API-key mode (env var set, region passed, no IAM keys passed); IAM mode (keys passed, empty bearer var removed); client caching per region; adaptive retries configured.
- `test_pricing.py` (13): 9 known prices, including the upgrade path; a typical question costs about $0.003; unknown model raises; negative counts rejected; every default model ID in Settings has a price.
- `test_live_auth.py` (1, `live`): one `Converse` call to Nova 2 Lite.
- Result: 65 passed, 0 failed; live: 1 skipped (no key yet).

## Out of scope / follow-ups
- **The live acceptance criterion is still pending.** It needs Goutham's Bedrock API key in `.env`. When that is done, run the live test and add its printed line here. That run is the first proof that the account can call Nova 2 Lite from Tokyo, and it confirms the IAM ARNs in SPEC section 2.3. If it fails with an access error, stop and report the exact error.
- Console steps (budget alarm with "Credits" excluded): not done yet, per Goutham.
- The Nova Pro `apac.` price is assumed equal to the Tokyo list price. Check it against the first bill.

## Review log
- Self-review: passed for all unit-testable criteria. One real bug was found while reading the botocore source (empty bearer variable) and is guarded with a test. The live test is written, but not yet run.
