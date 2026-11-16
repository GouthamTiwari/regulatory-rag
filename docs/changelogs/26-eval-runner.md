# Task 26: Eval runner and report
Branch: task/26-eval-runner | Date: 2026-11-16

## What changed
- `src/regrag/eval/run.py` and `src/regrag/eval/__main__.py`: `uv run python -m regrag.eval [--configs ...] [--retrieval-only] [--limit N] [--include-unreviewed] [--sample] [--out docs/eval]`.
  - **Per question and configuration:** `answer_question` runs (or search + rerank only with `--retrieval-only`, where routing is rules-only, so there's no LLM call at all). Then recall@5/10 and MRR on the final ranking (reranked list first, then the rest retrieved), citation markers and cited documents, abstention, supersession notes, latency and cost. The judge (Task 25) scores faithfulness on the cited passages.
  - **One pipeline per configuration**, reused for all its questions, so the Bedrock pacers hold.
  - A question that raises is recorded as an error row, and the run continues.
  - Before starting, it prints the question count, the judge model and an estimated cost that uses the judge's own price.
  - `results.md` lists the date, golden-set size and reviewed count, mode, generator and judge models, embed and rerank models, regions, `PRICES_CHECKED_ON` and the total cost, then one table row per configuration with **honest labels**: "keyword (Postgres FTS, BM25-like)", never "BM25" alone. `results.json` keeps the summary and every per-question row.
- `tests/eval/test_run.py`: tests (see below).
- `docs/eval/results.md`, `docs/eval/results.json`: the **sample** run, labelled "Sample, not final".

## How to verify
- `uv run pytest tests/eval/test_run.py` → 6 passed
- Sample run: `uv run python -m regrag.eval --include-unreviewed --sample` → 20 questions × 4 configurations, **0 errors, $0.2637**.

| Configuration | Recall@5 | MRR | Citation acc. | Faithfulness | Abstain acc. | Abstain P | p95 latency |
|---|---|---|---|---|---|---|---|
| keyword (BM25-like) | 0.94 | 0.86 | 0.91 | 0.90 | 0.65 | 0.30 | 3.7 s |
| vector | 1.00 | 1.00 | 0.96 | 0.96 | 1.00 | 1.00 | 6.1 s |
| hybrid (RRF) | 1.00 | 1.00 | 0.95 | 0.94 | 0.80 | 0.43 | 5.2 s |
| hybrid + rerank | 1.00 | 1.00 | 0.94 | 0.93 | 0.95 | 0.75 | 38.5 s |

**Reading:**
- Document-level retrieval is saturated: the seed questions only list expected *documents*, and finding the right one of 65 is easy.
- The setups differ in **wrong abstentions**: keyword search often gives the generator the right document but the wrong paragraph, so it replies `INSUFFICIENT_EVIDENCE`.
- On this small unreviewed set, vector search alone matches hybrid + rerank.
- The rerank latency comes from the account's 2 requests/minute quota, not from the model.

## Tests
- 6 tests with fake pipelines:
  - 4 configs × 3 questions → 12 rows, a 4-row table with 14 metric columns, and the failing question recorded as an error in every config while the run continues;
  - retrieval-only makes 0 LLM and 0 rerank calls for bm25/vector/hybrid;
  - the report names the date, size, models, region, prices date and the sample label;
  - "BM25" never appears alone as a row label;
  - an abstain question counts toward abstention, not retrieval;
  - the cost estimate rises when the judge is Nova Pro.
- Full suite: 326 passed, 0 failed.

## Out of scope / follow-ups
- **Task 27/28:** add `expected_sections` (section-level gold) while reviewing questions, so retrieval metrics separate the configurations. Grow the set toward 60, and look at the wrong abstentions of the keyword and hybrid setups.
- Task 28: the final run with Nova Pro as judge.

## Review log
- Self-review: passed. All 5 acceptance criteria met. The sample run finished with no errors.
