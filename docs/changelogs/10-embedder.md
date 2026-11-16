# Task 10: Embedder (Titan V2)
Branch: task/10-embedder | Date: 2026-11-16

## What changed
- `src/regrag/bedrock/embedder.py`: `TitanEmbedder` (implements `Embedder`).
  - One `InvokeModel` call per text with `{"inputText", "dimensions": 1024, "normalize": true}`, up to 4 in parallel. `pool.map` keeps the input order.
  - Token counts are summed from `inputTextTokenCount`.
  - Texts over about 7,500 estimated tokens are truncated, with a warning. An empty list makes no call.
  - The client is passed in (dependency injection); `from_settings()` builds it from Settings.
- `src/regrag/bedrock/retry.py` (**not in the task's file list**): `with_retries(call)` retries throttling and temporary AWS errors with 1/2/4 s pauses. Why a separate file: the reranker (Task 11) and LLM wrapper (Task 12) need the same behaviour, and it makes retries testable with fake clients.
- `tests/bedrock/test_embedder.py`: tests (see below).

## How to verify
- `uv run pytest tests/bedrock/test_embedder.py` → 7 passed
- `uv run pytest -m live tests/bedrock/test_embedder.py -s` → 1 passed: `region=ap-south-1 tokens=17 latency=0.42s`. Two 1024-dim vectors, each with length ≈ 1.0.

## Tests
- 7 unit tests with a fake Bedrock client: order kept even when one call finishes last; request body and token total; throttling retried (2 failures, then success); a non-retryable error is raised; an empty list makes no call; truncation warning; protocol check.
- 1 live test (Titan in Mumbai), recorded above.
- Full suite: 240 passed (+ 9 db, + live), 0 failed.

## Out of scope / follow-ups
- None.

## Review log
- Self-review: passed. All acceptance criteria met. The live latency from Mumbai is recorded, as SPEC 2.2 asked.
