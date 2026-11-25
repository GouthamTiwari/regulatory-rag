# Task 36: Library API, evaluation and v1.1.0
Branch: task/36-api-eval | Date: 2026-11-26

## What changed
- `src/regrag/api.py` (new), stable from v1.1.0:
  - **`search(query, k=4, corpus="gst")`:** retrieval only (hybrid keyword + vector with RRF, then the reranker), with named provisions first. No LLM call. Returns `Snippet(snippet_id, doc_id, title, url, section, text, checked_on, score)`:
    - `snippet_id` is `<doc_id>#<chunk_index>`;
    - `url` is the section's own CBIC page for the bare law, else the document's page;
    - `checked_on` is the document's "updated as on" date.
  - **`answer(question)`:** the full pipeline; returns the same `QueryResult` the CLI and the web page use.
  - **`corpus_version()`:** a short hash over every stored document's id, hash and embedding model, for callers' cache keys.
- `src/regrag/eval/metrics.py`: section-level relevance for statute provisions is now exact or by sub-part. "37" matches "37" and "37(1)", but not "137(2)" or "37A"; "16(2)" does not match "16(20)". Paragraph labels such as "Para 52" keep v1's containment match, so v1's numbers are unaffected.
- `src/regrag/eval/run.py`: `--tag` runs only the golden questions with that tag.
- `data/golden/golden.jsonl`: 21 new questions, g062 to g082, tagged `statute`, `v1.1` and `llm-reviewed`. 20 have the exact provision as section-level gold (s.16(4), r.36(4), s.16(2), s.17(5) three times, r.37, r.46, r.60(7), r.37A, s.77, IGST s.19(1), s.34, r.36(1), r.47, s.2(62), s.22, s.38, s.17(1), r.39). 1 should be refused (the GST rate on gold jewellery: rate notifications are not in the corpus).
- `docs/eval/v1.1/results.md` and `results.json`: the run below. v1's `docs/eval/results.md` is unchanged.
- `README.md`: the v1.1 corpus, a v1.1 results section (the v1 table unchanged), the library API, known limitations.
- `pyproject.toml`, `uv.lock`: version 1.1.0.

## Evaluation (2026-11-26)
21 questions × hybrid + rerank. Generator Nova 2 Lite, judge Nova Pro (`apac.amazon.nova-pro-v1:0`), 0 errors, **$0.0882** (estimate up to $0.158).

| Recall@5 | Recall@10 | MRR | Citation validity | Citation accuracy | Faithfulness | Abstention accuracy | Abstain P | Abstain R |
|---|---|---|---|---|---|---|---|---|
| 0.95 | 1.00 | 0.85 | 1.00 | 0.68 | 0.99 | 0.86 | 0.25 | 1.00 |

- **Retrieval:** the gold provision was in the top 10 every time, and in the top 5 for 20 of 21. The one miss at 5 (r.60(7), what GSTR-2B contains) ranked it 8th.
- **Wrong refusals (3 of 20 answerable):** g065 (motor vehicles, s.17(5)), g066 (180-day payment rule, r.37) and g078 (s.22 registration). The gold passage was retrieved each time, at ranks 5, 3 and 1, but the top rerank score fell below the abstain threshold of 0.01 that v1 calibrated on circulars. The threshold was **not** re-tuned on these same questions; doing so on a separate set is a follow-up.
- **The should-refuse question was refused.**

## Total cost of tasks 33 to 36
About $0.12: statute embeddings $0.0135 (including two re-ingests with vector reuse), about $0.004 lost in the interrupted first run, new documents $0.0017, about 12 live check questions at about $0.003 each, and this evaluation $0.0882.

## How to verify
- `uv run python -m regrag.eval --configs hybrid_rerank --tag v1.1 --out docs/eval/v1.1` (set `BEDROCK_JUDGE_MODEL_ID=apac.amazon.nova-pro-v1:0` for the judge used here).
- `uv run python -c "from regrag import api; print([h.section for h in api.search('What does rule 36(4) say?')])"` → `['36(4)', ...]`.

## Tests
- `tests/test_api.py` (9): snippets with stable ids and dates; a named provision first, with its section page and score 1.0; RBI searches never pinned to GST law; a bad corpus refused; section-number parsing; `corpus_version` changes with any document.
- `tests/eval/test_metrics.py` (9 new): exact-or-sub-part matching, including the cases that were false hits before.
- `tests/eval/test_golden.py`: the row count is now 82.
- Full suite: 424 passed, 36 live deselected.

## Out of scope / follow-ups
- Re-calibrate the abstain threshold for statute questions on a held-out set.
- A human review of the 21 new golden questions.

## Review log
- Self-review: read the diff line by line. No secrets; `.env` untouched. The judge model was set for this run only through an environment variable; the default in `config.py` stays Nova 2 Lite. v1 results were not changed. Found during the work: the first evaluation launch used `python -m regrag.eval.run`, which has no entry point and so did nothing (no cost); the correct command is `python -m regrag.eval`.
