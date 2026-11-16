# Evaluation results

- Date: 2026-11-16
- Golden questions: 61 (61 reviewed)
- Mode: full answers + LLM judge
- Generator: `global.amazon.nova-2-lite-v1:0`  Judge: `apac.amazon.nova-pro-v1:0`
- Embeddings: `amazon.titan-embed-text-v2:0`  Reranker: `amazon.rerank-v1:0`
- Regions: ap-south-1 (reranker: ap-northeast-1)
- Prices checked on: 2026-11-16  Total run cost: $0.9410

| Configuration | Recall@5 | Recall@10 | MRR | Citation validity | Citation accuracy | Faithfulness | Abstain acc. | Abstain P | Abstain R | Supersession flag | p95 latency (s) | Mean cost | Errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| keyword (Postgres FTS, BM25-like) | 0.74 | 0.81 | 0.62 | 1.00 | 0.93 | 0.97 | 0.70 | 0.28 | 1.00 | 1.00 | 3.6 | $0.0033 | 0 |
| vector (Titan V2 + pgvector) | 0.94 | 0.96 | 0.83 | 1.00 | 0.97 | 0.97 | 0.92 | 0.58 | 1.00 | 1.00 | 6.4 | $0.0036 | 0 |
| hybrid (keyword + vector, RRF) | 0.89 | 0.94 | 0.81 | 1.00 | 0.96 | 0.96 | 0.87 | 0.47 | 1.00 | 1.00 | 6.4 | $0.0037 | 0 |
| hybrid + rerank (Amazon Rerank 1.0) | 0.98 | 0.98 | 0.93 | 1.00 | 0.97 | 0.96 | 0.90 | 0.54 | 1.00 | 1.00 | 32.4 | $0.0047 | 0 |

Definitions: SPEC section 6.3. Retrieval metrics use answerable questions only; "–" means the metric is undefined for this run (e.g. no LLM in retrieval-only mode).
