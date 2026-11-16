# Task 12: LLM wrapper (Converse; Nova 2 Lite by default)
Branch: task/12-llm | Date: 2026-11-16

## What changed
- `src/regrag/bedrock/llm.py`: `BedrockLLM(client, model_id, temperature=0.0).complete(system, user, max_tokens) -> (text, Usage)`.
  - Uses the Converse API, so Nova and Claude share one code path with no model-specific code.
  - Temperature is 0, for repeatable evaluation runs.
  - Only text blocks are joined; reasoning/thinking blocks are ignored. Input and output tokens come from `usage`.
  - Throttling is retried through `retry.with_retries`.
  - Raises `LLMError` with a clear message on `stopReason == "max_tokens"` with no text, or on an empty answer.
- `tests/bedrock/test_llm.py`: tests (see below).

## How to verify
- `uv run pytest tests/bedrock/test_llm.py` → 4 passed
- `uv run pytest -m live tests/bedrock/test_llm.py -s` → 1 passed: Nova 2 Lite in Mumbai answered "KYC stands for Know Your Customer…", tokens 59/44, latency 0.93 s, cost $0.000150.
- `temperature` is accepted by Nova 2 Lite (closes the SPEC "to verify" note). With reasoning off by default there is no thinking-token overhead: 44 output tokens for a two-sentence answer.

## Tests
- 4 unit tests (fake client): text, usage and request shape (system, temperature 0, maxTokens); only text blocks used when a reasoning block is present; throttling retried; max_tokens with no text raises a clear error.
- 1 live test, recorded above.
- Full suite: 253 passed, 0 failed.

## Out of scope / follow-ups
- The live reply used Markdown bold (`**Know Your Customer**`). The generator prompt (Task 20) should ask for plain text, or the CLI should render it.

## Review log
- Self-review: passed. All acceptance criteria met.
