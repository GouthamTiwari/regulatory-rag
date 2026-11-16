# Evaluation results

> **Sample, not final.** Run on the 20 seed questions, which Goutham has not reviewed yet.

- Date: 2026-11-16
- Golden questions: 20 (0 reviewed)
- Mode: full answers + LLM judge
- Generator: `global.amazon.nova-2-lite-v1:0`  Judge: `global.amazon.nova-2-lite-v1:0`
- Embeddings: `amazon.titan-embed-text-v2:0`  Reranker: `amazon.rerank-v1:0`
- Regions: ap-south-1 (reranker: ap-northeast-1)
- Prices checked on: 2026-11-16  Total run cost: $0.2637

| Configuration | Recall@5 | Recall@10 | MRR | Citation validity | Citation accuracy | Faithfulness | Abstain acc. | Abstain P | Abstain R | Supersession flag | p95 latency (s) | Mean cost | Errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| keyword (Postgres FTS, BM25-like) | 0.94 | 1.00 | 0.86 | 1.00 | 0.91 | 0.90 | 0.65 | 0.30 | 1.00 | 1.00 | 3.7 | $0.0028 | 0 |
| vector (Titan V2 + pgvector) | 1.00 | 1.00 | 1.00 | 1.00 | 0.96 | 0.96 | 1.00 | 1.00 | 1.00 | 1.00 | 6.1 | $0.0029 | 0 |
| hybrid (keyword + vector, RRF) | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | 0.94 | 0.80 | 0.43 | 1.00 | 1.00 | 5.2 | $0.0032 | 0 |
| hybrid + rerank (Amazon Rerank 1.0) | 1.00 | 1.00 | 1.00 | 1.00 | 0.94 | 0.93 | 0.95 | 0.75 | 1.00 | 1.00 | 38.5 | $0.0043 | 0 |

Definitions: SPEC section 6.3. Retrieval metrics use answerable questions only; "–" means the metric is undefined for this run (e.g. no LLM in retrieval-only mode).
