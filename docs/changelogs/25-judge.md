# Task 25: Faithfulness judge
Branch: task/25-judge | Date: 2026-11-16

## What changed
- `src/regrag/eval/judge.py`: `judge_faithfulness(answer, cited_chunks, llm) -> JudgeResult(score, per_sentence, usage, model_id, failed)`.
  - **Sentences:** the answer is split into sentences, citation markers are removed, and the disclaimer ("not legal or tax advice"), "Sources:" lines and fragments under 3 words are skipped.
  - **One call:** the judge gets the cited passages as `[S#] title | section` blocks and the numbered sentences, and must reply with a JSON array `[{"n", "label": supported|unsupported, "reason"}]`. Code fences around the array are tolerated.
  - **Strict parsing:** every sentence must be labelled exactly once with a known label.
  - **One retry** with a reminder; after that, `score=None, failed=True`, never 0.
  - Score = supported / judged sentences. The judge model is whatever `llm.model_id` is (Nova 2 Lite for development, Nova Pro for the final run). There is no model name in the prompt.
- `tests/eval/test_judge.py`: tests (see below).

## How to verify
- `uv run pytest tests/eval/test_judge.py` → 6 passed

## Tests
- 6 tests (mocked LLM): 3 of 4 supported → 0.75, with labels, usage and model ID returned; markers and the disclaimer aren't sentences; malformed JSON retried once then `None` with "judge failed"; a successful retry (fenced JSON) is used; incomplete labels count as malformed; with a real `BedrockLLM` over a fake client, the judge model ID is exactly what gets sent.
- Full suite: 320 passed, 0 failed.

## Out of scope / follow-ups
- `query/validate.py` has the same narrow disclaimer pattern. It's harmless there (the disclaimer has no rule words, so it's never checked) and was left unchanged.

## Review log
- Self-review: passed. All 4 acceptance criteria met. One bug found by a test (the disclaimer was counted as a sentence) was fixed.
