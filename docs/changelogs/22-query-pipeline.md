# Task 22: Query pipeline, logging, command line
Branch: task/22-query-pipeline | Date: 2026-11-16

## What changed
- `src/regrag/query/pipeline.py`: `answer_question(question, *, config=None, parts=None, log=True) -> QueryResult`, the single entry point (SPEC 7).
  - **Stages:** route → retrieve (`fused_top_k`) → rerank (`rerank_top_n`) → supersession check → generate → validate → **one** regeneration with a "fix your citations" instruction if validation failed → abstain decision.
  - **Result:** citations (document, section, pages, URL); per-stage latency plus a total; usage summed (router and generator tokens, embedding tokens, rerank queries); cost from `pricing.py` for each model used.
  - **Abstaining:** the answer is a polite message plus up to 3 "You may want to read" documents with their URLs.
  - It prints nothing itself.
  - `build_pipeline(config)` wires the real parts for `bm25` / `vector` / `hybrid` / `hybrid_rerank`. The configs differ only in retrieval and reranking (SPEC 6.4), and `PipelineConfig` can replace any part or add validators.
- `src/regrag/query/querylog.py`: one JSON log line per question (no answer text) and a `query_logs` row.
- `src/regrag/query/__main__.py`: `uv run python -m regrag.query "question" [--config NAME] [--json] [--verbose]`. It prints the answer, sources (title | section | page + URL), supersession notes, route, config, time and cost, and the disclaimer.
- **Fixes forced by the first live questions** (files from Tasks 11, 13, 19, 20, 04/10 and config):
  1. **Abstain threshold 0.30 → 0.01** (`config.py`), calibrated with real Amazon Rerank scores on all 20 golden questions (table below). 0.30 was a guess made for Cohere and would have refused good questions.
  2. **Reranker pacing** (`reranker.py`, `config.rerank_requests_per_minute = 2`). This account's applied quota for Amazon Rerank 1.0 in Tokyo is **2 requests/minute** (AWS default 200; shown as "not adjustable" in Service Quotas). Titan's applied quota is 60/minute (default 6,000), which matches the 1/s pacing from Task 14.
  3. **Supersession replacement by rule, not by question** (`supersession.py`, `repository.chunks_like`, `pipeline.py`). The question-nearest chunk of PSL 2025 was an unrelated annex, so the model cited the 2020 chunk for a 2025 claim, which is a mis-attribution. It now fetches the 2 chunks of the newer document closest to the *old passage* (stored vectors, no extra Bedrock call). Result: the current rule is cited from PSL 2025, para 7.1, page 9.
  4. **Prompt rule 3** (`prompts.py`): a supersession statement must cite the old source's marker, the current rule must come from the newer source with its own marker, and no dates, numbers or names may be added that aren't in the sources. Before this, the model invented "a newer directive dated September 04, 2020", which is the *old* document's date. The validator caught it as an uncited claim.
  5. **Deterministic pacer test** (`embedder.py`, `_Pacer(clock=...)`): one full-suite run failed once and passed on rerun. The pacer test depended on wall-clock timing; it now uses a frozen clock.
- Tests: `tests/query/test_pipeline.py` (unit), `tests/query/test_pipeline_live.py` (live + db); updated `test_supersession_filter.py`, `test_reranker.py`, `test_embedder.py`, `test_repository.py`.

## Abstain-threshold calibration (hybrid + Amazon Rerank, 20 golden questions, 2026-11-16)
| Group | Top rerank score | Expected document in top 8 |
|---|---|---|
| 17 answerable (factual, table, cross-corpus, superseded) | 0.058 – 0.997 (median ≈ 0.97) | **17 of 17, all at rank 1** |
| 3 out-of-corpus (income tax, SEBI, repo rate) | 0.0003 – 0.0007 | none expected |

## How to verify
- `uv run pytest tests/query/test_pipeline.py` → 11 passed
- `uv run pytest -m "live and db" tests/query/test_pipeline_live.py -s` → 2 passed:
  - the demo-vehicle question is answered with every citation from `gst-231-25-2024` (score 0.98, 5.8 s, $0.0047);
  - the income-tax question abstains (`weak_evidence`, score 0.0007).
- `uv run python -m regrag.query "Under the 2020 Priority Sector Lending Master Direction, what is the overall PSL target for a domestic commercial bank?"` → says the 2020 direction is superseded and gives 40% of ANBC/CEOBE cited to PSL 2025 para 7.1 p. 9, with the supersession note. 24.9 s (rerank pacing), $0.0017.

## Tests
- Unit (11): stages run in order, with cost, latency and citation fields; a failed validation regenerates once, then abstains with the closest documents; a successful retry is used; a weak rerank score abstains; an extra validator forces abstention; nothing printed and the result is JSON-serialisable; all 4 configurations build with the right retriever and reranker.
- Live + db (2), recorded above.
- Full suite: 314 passed; db: 32 passed (includes the 2 live+db tests); 0 failed.

## Out of scope / follow-ups
- PSL 2025 chunk labels read "Appendix, para 7.1": an "Appendix" heading early in that PDF becomes the top-level section for what follows. Chunker follow-up (Task 08 heuristics).
- Pacers live per pipeline instance; the eval runner (Task 26) must reuse one pipeline per configuration so the 2/min rerank pacing holds.
- Answers sometimes cite the same document several times (one marker per supporting chunk). Correct, but verbose.

## Review log
- Self-review: passed. All 4 acceptance criteria met, live. Five issues found by real questions were fixed, each with a test, and are listed above.
