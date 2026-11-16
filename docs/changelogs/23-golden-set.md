# Task 23: Golden set schema, loader, seed questions
Branch: task/23-golden-set | Date: 2026-11-16

## What changed
- `data/golden/golden.jsonl`: **20 seed rows**, schema version 1.
  - Contents: the 10 example questions from SPEC section 1, plus 10 more. In total: 7 factual, 2 table, 4 cross-corpus, 4 superseded, 3 abstain.
  - `expected_doc_ids` were chosen from the manifest topics and the verified relations (e.g. PSL 2020 → `rbi-11959` and its successor `rbi-12799`; warranty → `gst-195-07-2023` and `gst-216-10-2024`; corrigendum → `gst-237-31-2024` and `gst-237-31-2024-corr`).
  - `expected_sections` are left empty, so metrics fall back to document-level matching (SPEC 6.3).
  - Reference answers are `TODO: Goutham to confirm …` (abstain rows state why they should abstain). **Every row has `reviewed: false`**, so none counts in results until Goutham checks it (SPEC 6.2).
- `src/regrag/eval/golden.py`: `load_golden(path, include_unreviewed=False, known_doc_ids=None)`.
  - **Checks every row:** required fields and their types, `schema_version == 1`, allowed `corpus`/`type`/`source` values, unique ids, and that abstain rows have no expected docs while answerable rows have at least one. `type == "abstain"` must agree with `should_abstain`, `expected_sections` docs must be among `expected_doc_ids`, and doc ids must exist in the manifest when it's given.
  - **Unknown fields are kept** in `extra` (the schema only grows), and all problems are reported together.
  - **CLI:** `python -m regrag.eval.golden --check` prints counts by type and corpus.
- `tests/eval/test_golden.py`: tests (see below).

## How to verify
- `uv run python -m regrag.eval.golden --check` → `Rows: 20 reviewed: 0 usable now: 0`, counts by type/corpus, exit 0

## Tests
- 10 tests: valid row; bad type; duplicate id; extra field kept; abstain row with expected docs rejected; unreviewed rows excluded by default; unknown doc id rejected; all problems reported together; the committed seed file is valid (≥20 rows, ≥3 superseded, ≥3 abstain, ≥2 cross-corpus, every doc id in the manifest); the `--check` command.
- Full suite: 222 passed (+ 9 db), 0 failed.

## Out of scope / follow-ups
- Goutham reviews the 20 seeds (and the drafts from Task 27): confirm or fix each reference answer, then set `reviewed: true`.

## Review log
- Self-review: passed. All 3 acceptance criteria met.
