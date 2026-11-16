# Task 24: Metrics
Branch: task/24-metrics | Date: 2026-11-16

## What changed
- `src/regrag/eval/metrics.py`: pure functions for every metric in SPEC 6.3.
  - `is_relevant`: matches on an expected section when the question lists sections (the section text is contained in the chunk's `section_no`, e.g. "para 4" in "Chapter I, para 4"); otherwise falls back to the document.
  - `recall_at_k`: hit rate, 1 or 0.
  - `mrr`: 1/rank of the first relevant chunk within the top k, else 0.
  - `citation_validity`: share of markers that point to a supplied chunk; 1.0 when nothing was cited.
  - `citation_accuracy`: share of cited chunks from an expected document; `None` when nothing was cited.
  - `abstention_scores`: accuracy, precision (`None` if it never abstained) and recall (`None` if no question should abstain).
  - `supersession_flag_rate`: share of must-flag questions whose answer carried a note; `None` if there are none.
  - `latency_summary`: mean and nearest-rank p95.
  - `mean`: average that skips `None`.
- `tests/eval/test_metrics.py`: tests (see below).

## How to verify
- `uv run pytest tests/eval/test_metrics.py` → 11 passed

## Tests
- 11 tests, each with hand-computed values: document-level vs section-level relevance (including the fallback); recall@k at k=2 vs k=3; MRR including 0 when nothing is relevant and when the hit is beyond the top 10; citation validity 0.75, and 1.0 with no citations; citation accuracy 0.5, and `None` with no citations; abstention TP/FP/FN/TN = 0.5/0.5/0.5; zero abstentions → precision `None`, not a crash; flag rate; p95 of 1..20 = 19; mean skipping `None`.
- Full suite: 233 passed (+ 9 db), 0 failed.

## Out of scope / follow-ups
- None.

## Review log
- Self-review: passed. All acceptance criteria met, including the edge cases (MRR 0, validity 1.0 with no citations, precision `None`, section-to-document fallback).
