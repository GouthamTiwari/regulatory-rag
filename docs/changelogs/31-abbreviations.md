# Task 31: Spell out abbreviations before search
Branch: task/31-abbreviations | Date: 2026-11-19

## What changed
- `src/regrag/query/abbreviations.py` (new): a glossary of 26 abbreviations that appear in the corpus with one meaning (RCM, ITC, TCS, PSL, KYC, NBFC, PPI, …). Ambiguous ones (AD, PoS, SEZ) were left out after counting them in the corpus. `expand_abbreviations()` adds the full form after the first upper-case use ("RCM (reverse charge mechanism)"), keeps plurals, and leaves the question alone when the full form is already there.
- `src/regrag/query/pipeline.py`: `answer_question` routes, searches, reranks and generates with the expanded question; `QueryResult.question` still holds what the user typed.
- `README.md`: design-decision bullet, test count 350. `docs/TASKS.md`: Task 31 entry.

## How to verify
- `uv run python -m regrag.query "What is RCM?"` → route=gst, cited answer from Circular 211/05/2024-GST and others. Before this change: refused, route=both, top rerank score 0.0051 (threshold 0.01). Checked live 2026-11-19: 5.9 s, $0.00459.

## Tests
- `tests/query/test_abbreviations.py` (8 new): bare abbreviation, routing now reaches GST by rules, plurals and several abbreviations, first use only, full form already present, lower-case words and longer words untouched, glossary shape, and the pipeline passing the expanded text to router/retriever/generator while returning the typed question.
- Full suite: 350 passed, 36 deselected. Ruff clean.

## Out of scope / follow-ups
- The published eval numbers (Task 28) were measured before this change. Golden questions that use abbreviations (ITC, PSL, KYC) now search with the full form, so a re-run may shift the numbers slightly. Not re-run here (about 1 hour at the rerank quota).
- The glossary is hand-made; new documents may need new entries.

## Review log
- Self-review: read the full diff. Checked that matching is case-sensitive (so "emi" in lower case is untouched), whole-word (ITCX untouched), and that every stage after routing gets the same expanded text. No secrets, no `data/raw/`, no AWS resources, Bedrock mocked in tests. Passed.
