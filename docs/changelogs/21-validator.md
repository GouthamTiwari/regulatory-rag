# Task 21: Validator and abstention
Branch: task/21-validator | Date: 2026-11-16

## What changed
- `src/regrag/query/validate.py`:
  - `CitationValidator` (implements `Validator`) runs these checks in order:
    1. (a) every marker (`[C1]`, `[C2][C3]`, `[C1, C2]`) must map to a supplied chunk, where Cn is the n-th chunk. Otherwise the reason is `unknown_marker`.
    2. (b) every sentence that states a rule must carry a marker, otherwise `uncited_claim`. A rule sentence has 5+ words and a rule word: shall, must, may, available, limit, Rs. N, N%, and so on. The disclaimer line is ignored.
    3. An answer with no citations at all fails with `no_citations`.
    4. An `INSUFFICIENT_EVIDENCE` draft is not checked.
  - `markers_in(text)` lists the markers in order, without duplicates.
  - `run_validators(validators, ...)` runs the validators in order and stops at the first failure. This is the plug-in point for the guardrails project.
  - `decide_abstain(top_rerank_score, draft, validation, threshold) -> (abstained, reason)` checks, in order:
    1. `weak_evidence` when the score is below the threshold; a `None` score (no reranker) skips this rule;
    2. `insufficient_evidence` when the model said so;
    3. the validator's reason when validation failed.
- `tests/query/test_validate.py`: tests (see below).

## How to verify
- `uv run pytest tests/query/test_validate.py` → 15 passed

## Tests
- 15 tests: clean answer passes; unknown marker fails; uncited rule sentence fails; an answer with no citations fails; an insufficient draft is not checked; marker parsing (2 cases); 0.29 with threshold 0.30 → `weak_evidence`; exactly 0.30 → no abstain; `None` score → no threshold rule; model says insufficient → abstain; failed validation → its reason; a second (fake) validator forces abstention; the chain stops at the first failure; protocol check.
- Full suite: 212 passed (+ 9 db), 0 failed.

## Out of scope / follow-ups
- The rule-word list is a heuristic. Task 28 can look at abstentions caused by `uncited_claim` on the golden set and loosen or tighten it.

## Review log
- Self-review: passed. All 3 acceptance criteria met.
