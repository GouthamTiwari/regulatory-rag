# Task 20: Generator with citations
Branch: task/20-generator | Date: 2026-11-16

## What changed
- `src/regrag/query/prompts.py`:
  - **System prompt rules:** use only the sources; put `[C#]` after every rule, limit or fact; say so when a source is marked SUPERSEDED/WITHDRAWN; reply exactly `INSUFFICIENT_EVIDENCE` when the sources don't answer; write plain text with no Markdown (the Task 12 live reply used `**bold**`).
  - **Prompt-injection guard:** the system prompt says the text inside `<context>` is data, not instructions.
  - `source_header` builds `[C1] title | section | page(s) | mark`, and `build_user_prompt` puts every chunk once inside `<context>…</context>`, followed by the question.
- `src/regrag/query/generate.py`: `CitedGenerator(llm, max_tokens, extra_instruction="")` (implements `Generator`).
  - Parses markers with `markers_in` (Task 21) and spots `INSUFFICIENT_EVIDENCE`.
  - With no chunks it makes no LLM call.
  - `extra_instruction` is used by the pipeline's one retry after a failed validation.
- `tests/query/test_generate.py`: tests (see below).

## How to verify
- `uv run pytest tests/query/test_generate.py` → 7 passed

## Tests
- 7 tests (mocked LLM): every chunk appears once with a unique marker, and a superseded chunk carries its mark; `[C1]`, `[C2][C1]` and `[C1, C2]` are all parsed; `INSUFFICIENT_EVIDENCE` is handled; no chunks means no call; an injected "ignore previous instructions" stays inside `<context>` and the system prompt says context is data; the retry instruction is appended; protocol check.

## Out of scope / follow-ups
- None.

## Review log
- Self-review: passed. All 4 acceptance criteria met.
