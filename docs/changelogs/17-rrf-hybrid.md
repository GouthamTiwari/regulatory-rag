# Task 17: RRF fusion + hybrid retriever
Branch: task/17-rrf-hybrid | Date: 2026-11-16

## What changed
- `src/regrag/retrieval/fusion.py`: `rrf_fuse(lists, k=60, top_k=30)`, a pure function.
  - Each chunk scores `sum(1/(k+rank))` with 1-based ranks; ties are broken by `chunk_id`, so the order is repeatable.
  - When one chunk arrives from several lists, every rank and score any list knew is kept (`keyword_rank`, `vector_rank`, ...) for logs.
  - The input chunks are never modified, and results carry `fused_score`.
- `src/regrag/retrieval/hybrid.py`: `HybridRetriever(keyword, vector, keyword_top_k=30, vector_top_k=30, rrf_k=60)` implements the `Retriever` protocol on top of any two Retrievers. It calls each with its own top-k, then fuses.
- `tests/retrieval/test_fusion.py`, `tests/retrieval/test_hybrid.py`: tests (see below).

## How to verify
- `uv run pytest tests/retrieval` → 9 passed

## Tests
- `test_fusion.py` (6): hand-computed example matches to 6 decimals; a chunk in both lists beats a rank-1 chunk in only one list; an empty list is handled; ties broken by `chunk_id`; `top_k` respected; original ranks kept and inputs not modified.
- `test_hybrid.py` (3): both retrievers called with their own top-k and the results fused; route and top-k respected; satisfies the `Retriever` protocol. Fake retrievers only, no database.
- Full suite: 197 passed (+ 9 db), 0 failed.

## Out of scope / follow-ups
- None.

## Review log
- Self-review: passed. All 3 acceptance criteria met.
