# Task 27: Grow the golden set (part 1: drafting and review tool)
Branch: task/27-golden-drafts | Date: 2026-11-16

## What changed
- `src/regrag/eval/draft_questions.py`, with two commands:
  - **`draft`**:
    - Samples passages across documents, round robin, so every document is used once before any repeats; the seed is fixed.
    - Takes 16 text passages per corpus plus 3 tables, only active documents, at least 120 tokens and not preambles.
    - Asks the generator model for ONE question and a 1–2 sentence answer **from that passage only**, as JSON. Unusable drafts (too short, referring to "this passage", invalid JSON) are dropped.
    - Each draft carries **section-level gold** (doc, section, page) from its passage.
    - Adds 8 hand-written questions of the kinds an LLM can't draft from one passage: 3 superseded or clarified (taken from the reviewed relations), 1 cross-corpus and 4 should-refuse.
    - Writes **one Excel-friendly review sheet** (`data/raw/golden_review.csv`, UTF-8 with BOM, gitignored): the 20 existing questions + 8 hand-written + the drafts, each with a `keep` column and a source excerpt.
  - **`accept`**:
    - Rows marked Y/yes are written to `data/golden/golden.jsonl` with `reviewed=true`.
    - Existing ids are **updated, not duplicated**; new rows get the next ids (g021, …).
    - Section-level gold is kept, and the whole file is **validated by the golden loader before it replaces the real file**.
  - Why one review sheet, not drafts committed to the repo: drafts are scratch, and only human-checked rows belong in the golden set (SPEC 6.2). `drafts.jsonl` from TASKS.md is replaced by this CSV.
- `tests/eval/test_draft_questions.py`: tests (see below).

## How to verify
- `uv run pytest tests/eval/test_draft_questions.py` → 9 passed
- `uv run python -m regrag.eval.draft_questions draft` → 35 passages drafted, 35 usable (about $0.03); review sheet with 63 rows.

## Tests
- 9 tests (mocked LLM, no DB): sampling covers every document before repeating and is repeatable; drafts carry doc/section/page and unusable replies are skipped (3 cases); accept writes only kept rows, updates a seed in place, adds new ids, keeps section gold, marks them reviewed and validates; review sheet columns; hand-written questions point at manifest documents and abstain flags agree; the committed golden file is untouched by the tests.
- Full suite: 335 passed, 0 failed.

## Out of scope / follow-ups
- **Part 2 (pending Goutham's review):** mark keep = Y in the sheet, run `accept`, then commit `data/golden/golden.jsonl`. Target ≈ 60 reviewed rows (SPEC decision 6 fallback). The type counts depend on what he keeps.

## Review log
- Self-review: passed for part 1. Drafts were spot-checked: they're specific, answerable from the cited passage, and have correct section and page.
