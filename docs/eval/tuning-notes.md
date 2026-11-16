# Tuning notes (Task 28)

Final run: 2026-11-16, 61 golden questions (assistant-reviewed, 33 with section-level gold) × 4 configurations, generator Nova 2 Lite, judge **Nova Pro** (`apac.amazon.nova-pro-v1:0`), 0 errors, total cost **$0.94**.

## Settings changed
| Setting | Old | New | Evidence |
|---|---|---|---|
| `abstain_threshold` | 0.30 (starting guess for Cohere) | **0.01** | Calibrated in Task 22 on the 20 seed questions with Amazon Rerank. Answerable top scores were 0.058–0.997 and out-of-corpus 0.0003–0.0007; at 0.30, good answers would have been refused. In this final run, abstention recall is 1.00 (all 7 should-refuse questions refused) in every configuration. |
| `embed_requests_per_second` | (none) | 1.0 | Account quota for Titan V2: 60 requests/min. |
| `rerank_requests_per_minute` | (none) | 2.0 | Account quota for Amazon Rerank 1.0: 2 requests/min. |

No other setting was changed. Why: each full 4-way run takes about an hour, because of the 2/min rerank quota, so the "at most two more experiments" budget of SPEC Task 28 was not used. Candidates are listed below.

## What the final table shows
- **Reranking improves retrieval clearly once section-level gold exists.** Recall@5 0.98 vs 0.94 (vector) and 0.89 (hybrid); MRR 0.93 vs 0.83. The 20-question sample (document-level gold only) could not show this.
- **Hybrid without reranking was slightly worse than vector alone** on this corpus (MRR 0.81 vs 0.83). Keyword search adds many partially matching passages that RRF lets in; the reranker then filters them out.
- **Wrong refusals are the main remaining error.** Answerable questions refused: keyword 18, hybrid 8, hybrid + rerank 6, vector 5. Most of them are cross-corpus questions (an answer needs passages from both corpora within the top 8) and some specific factual questions.
- Faithfulness (Nova Pro judge) is 0.96–0.97 for every configuration, and citation validity is 1.00 everywhere (enforced by the validator).
- Latency: hybrid + rerank p95 is 32 s, almost all of it waiting for the 2/min rerank quota, not model time.

## Faithfulness: judge comparison (hybrid + rerank)
| Judge | Questions | Faithfulness |
|---|---|---|
| Nova 2 Lite (sample run, 20 seed questions) | 20 | 0.93 |
| Nova Pro (final run, 61 questions) | 61 | 0.96 |

The two runs use different question sets, so this is indicative only: the stronger judge did not mark answers down.

## Next experiments (not run)
1. `rerank_top_n` 8 → 12 for cross-corpus questions: more room for passages from both corpora.
2. Route-aware retrieval for `both`: take the top k from each corpus separately before fusing.
3. Store `rerank_top_score` and `abstain_reason` per row in `results.json`, so a threshold sweep can reuse stored scores at no cost.
