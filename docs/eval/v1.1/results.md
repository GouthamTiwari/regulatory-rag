# Evaluation results

- Date: 2026-11-26
- Golden questions: 21 (21 reviewed)
- Mode: full answers + LLM judge
- Generator: `global.amazon.nova-2-lite-v1:0`  Judge: `apac.amazon.nova-pro-v1:0`
- Embeddings: `amazon.titan-embed-text-v2:0`  Reranker: `amazon.rerank-v1:0`
- Regions: ap-south-1 (reranker: ap-northeast-1)
- Prices checked on: 2026-11-16  Total run cost: $0.0882

| Configuration | Recall@5 | Recall@10 | MRR | Citation validity | Citation accuracy | Faithfulness | Abstain acc. | Abstain P | Abstain R | Supersession flag | p95 latency (s) | Mean cost | Errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hybrid + rerank (Amazon Rerank 1.0) | 0.95 | 1.00 | 0.85 | 1.00 | 0.68 | 0.99 | 0.86 | 0.25 | 1.00 | – | 30.8 | $0.0042 | 0 |

Definitions: SPEC section 6.3. Retrieval metrics use answerable questions only; "–" means the metric is undefined for this run (e.g. no LLM in retrieval-only mode).
