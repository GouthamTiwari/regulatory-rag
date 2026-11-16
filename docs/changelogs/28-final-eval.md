# Task 28: Full evaluation and tuning
Branch: task/28-final-eval | Date: 2026-11-16

## What changed
- `docs/eval/results.md`, `docs/eval/results.json`: the **final** run.
  - 61 reviewed golden questions × 4 configurations, judge **Nova Pro** (`apac.amazon.nova-pro-v1:0`), set by environment variable for this run only. The `config.py` default stays Nova 2 Lite.
  - **0 errors, $0.9410.** One Nova Pro call was made first, to confirm access.
- `docs/eval/tuning-notes.md`:
  - every changed setting, with old value, new value and evidence: the abstain threshold 0.30 → 0.01 calibrated in Task 22, plus the two quota pacers;
  - a reading of the table, the judge comparison and the next experiments.
- `README.md` (Task 29's file): the evaluation section now shows the final table, a reading, and a **disclosure that the golden set was reviewed by an AI assistant** (rows tagged `assistant-reviewed`). Test count and cost line updated.
- `src/regrag/config.py` is **unchanged**: the threshold was already calibrated in Task 22, and no other experiment was run (see below).

## Final table
| Configuration | Recall@5 | MRR | Citation acc. | Faithfulness | Abstain acc. | p95 |
|---|---|---|---|---|---|---|
| keyword (BM25-like) | 0.74 | 0.62 | 0.93 | 0.97 | 0.70 | 3.6 s |
| vector | 0.94 | 0.83 | 0.97 | 0.97 | 0.92 | 6.4 s |
| hybrid (RRF) | 0.89 | 0.81 | 0.96 | 0.96 | 0.87 | 6.4 s |
| hybrid + rerank | 0.98 | 0.93 | 0.97 | 0.96 | 0.90 | 32.4 s |

Citation validity was 1.00 everywhere, abstention recall 1.00 everywhere, and the supersession flag rate 1.00 everywhere.

## Acceptance
- Final table for all four configurations on the full reviewed set, with run cost, question count and judge model: met.
- Citation validity is 100% in every configuration: met.
- `tuning-notes.md` lists each changed setting with its evidence: met.
- **"Try at most two further changes": not done.** Each full run takes about an hour at the account's 2/min rerank quota. The candidates are listed in `tuning-notes.md`.
- All tests still pass with the defaults: 335 passed.

## Out of scope / follow-ups
- A human review of the 61 golden rows (they are assistant-reviewed).
- Experiments: `rerank_top_n` 12; per-corpus retrieval for `both` questions; storing the rerank score and abstain reason per row for free threshold sweeps.

## Review log
- Self-review: passed with one documented gap (no extra tuning experiments). The README numbers were checked against `docs/eval/results.md`, and a privacy scan was clean.
