# Task 11: Reranker (Amazon Rerank 1.0, Cohere adapter)
Branch: task/11-reranker | Date: 2026-11-16

## What changed
- `src/regrag/bedrock/reranker.py`:
  - `BedrockReranker` (implements `Reranker`) calls a rerank model with `InvokeModel` on `bedrock-runtime`; the agent-runtime Rerank API doesn't accept API keys.
    - It picks an adapter per model ID (`amazon.rerank-v1:0`, `cohere.rerank-v3-5:0`); an unknown ID raises.
    - It sends at most 100 documents per call, counts each call as one billed unit (`last_queries` / `total_queries`), and sets `rerank_score` on copies (inputs untouched).
    - Results come back sorted by score, with ties keeping the retrieval order.
    - Each document is the chunk with its title and section path in front.
  - `NoopReranker` keeps the order and cuts to `top_n`, for the non-rerank configurations.
- **Format verified live (Tokyo, 2026-11-16)**, closing SPEC's "to verify":
  - request `{"query": str, "documents": [str], "top_n": int}`;
  - response `{"results": [{"index": int, "relevance_score": float}]}`.
  - The client is created with `region=settings.bedrock_rerank_region`.
- `tests/bedrock/test_reranker.py`: tests (see below).

## How to verify
- `uv run pytest tests/bedrock/test_reranker.py` → 9 passed
- `uv run pytest -m live tests/bedrock/test_reranker.py -s` → 1 passed: `scores=[0.1668, 0.0, 0.0] queries=1`, with the relevant passage first.

## Tests
- 9 unit tests (fake client): scores map back to the right chunks; inputs untouched; `top_n`; 150 chunks → calls of 100 + 50, billed as 2; empty input makes no call; both adapters build the right body; unknown model rejected; document text; NoopReranker; protocol checks.
- 1 live test, recorded above.
- Full suite: 249 passed, 0 failed.

## Out of scope / follow-ups
- **Score scale:** Amazon Rerank gave the clearly relevant passage only **0.17–0.21** (two live probes). SPEC's starting abstain threshold of 0.30 was guessed for Cohere and would wrongly abstain here. Task 22 must check real scores before relying on the threshold, and Task 28 tunes it on the golden set.
- What exactly one "search unit" covers is assumed to be one request of up to 100 documents (SPEC 2.4). Confirm on the first bill.

## Review log
- Self-review: passed. All acceptance criteria met, and the field names were confirmed live.
