# Task 18: Router
Branch: task/18-router | Date: 2026-11-16

## What changed
- `src/regrag/query/router.py`: `RuleThenLLMRouter(llm)` (implements `Router`).
  - **Keyword rules first.** GST words: GST/ITC/GSTR/place of supply/e-invoice/CBIC/TCS/valuation/circular numbers ending -GST, and so on. RBI words: RBI/KYC/NBFC/PPI/bank/loan/deposit/PSL/FEMA/LRS/fraud/payment systems, and so on. Hits on both sides route to `both`, and no LLM call is made.
  - **One-word LLM call** only when no rule fires; an unparseable reply, an LLM error or no LLM all give `both`.
  - `last_path` (`rules`/`llm`/`default`) and `last_usage` are kept for the log.
- `tests/query/test_router.py`: tests (see below).

## How to verify
- `uv run pytest tests/query/test_router.py` → 28 passed

## Tests
- 20 table-driven questions (8 RBI, 8 GST, 4 both) decided by rules alone with zero LLM calls; a no-keyword question makes exactly one LLM call; 4 garbage replies give `both`; LLM failure and no LLM give `both`; parsing helpers; protocol check.

## Out of scope / follow-ups
- The keyword lists are a starting point. Task 28 can check routing mistakes on the golden set.

## Review log
- Self-review: passed. One miss found by the tests ("valued" vs "valuation") was fixed.
