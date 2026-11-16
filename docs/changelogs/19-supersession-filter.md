# Task 19: Supersession filter/flag
Branch: task/19-supersession-filter | Date: 2026-11-16

## What changed
- `src/regrag/query/supersession.py`: `apply_supersession(chunks, documents, relations, fetch_replacement) -> (chunks, notes)`. Pure logic: the database lookups are passed in.
  - **Superseded/withdrawn document whose replacement is in the corpus:** at most one old chunk is kept, marked `SUPERSEDED BY <newer reference>`, and the newer document's best chunk is added if it isn't already present. Note: "X was superseded by Y; the current rule is in Y."
  - **Replacement not in the corpus:** the chunk is kept and marked, and the note names the reference.
  - **Amended, clarified or corrected document:** the chunk is kept, with a note "X was amended/clarified/corrected by Y."
  - **Active documents** pass through unchanged.
  - **Only `reviewed` links are used**, so the 61 unreviewed extracted links can never trigger a warning (SPEC 3.4).
- `tests/query/test_supersession_filter.py`: tests (see below).

## How to verify
- `uv run pytest tests/query/test_supersession_filter.py` → 6 passed

## Tests
- 6 tests: superseded with the replacement in the corpus (one old chunk kept and marked, new chunk added, exact note); the replacement isn't duplicated if already present; withdrawn with no replacement; a clarified document keeps its chunk and gets a note; active documents are unchanged; unreviewed links are ignored.

## Out of scope / follow-ups
- None.

## Review log
- Self-review: passed. All 4 acceptance criteria met.
