# Task 16: Vector retriever
Branch: task/16-vector-retriever | Date: 2026-11-16

## What changed
- `src/regrag/retrieval/vector.py`: `VectorRetriever(conn, embedder, ef_search=100)` (implements `Retriever`).
  - Embeds the question once, then orders by cosine distance (`<=>`) on the HNSW index, with a route filter. Sets `vector_score = 1 - distance` and `vector_rank`. `last_embed_tokens` feeds the cost log.
  - Inside its own transaction it sets `hnsw.ef_search` and `hnsw.iterative_scan = relaxed_order` via `set_config(..., true)`, because SET can't take parameters. The iterative scan (pgvector 0.8) keeps searching until enough rows pass the route filter.
- `tests/retrieval/test_vector.py`: tests (see below).

## How to verify
- `uv run pytest -m db tests/retrieval/test_vector.py` → 4 passed

## Tests
- 4 db tests with hand-made unit vectors: the nearest vector is rank 1, with a score of cos(angle); 30 nearer RBI chunks are filtered out by route `gst`, yet 5 GST chunks still come back; the embedder is called once and its tokens recorded; a blank question makes no call.

## Out of scope / follow-ups
- None.

## Review log
- Self-review: passed. All acceptance criteria met.
