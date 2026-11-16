# Changelog

One line per merged task: date | task | summary.

- 2026-11-16 | 01 repo-setup | uv project (Python 3.12), ruff, pytest with live/db markers, .env.example, README skeleton
- 2026-11-16 | 02 config-types-interfaces | Settings (secrets masked, empty = default), shared dataclasses, 6 Protocols, test fakes
- 2026-11-16 | 03 docker-postgres-schema | pgvector in Docker (127.0.0.1:5433), 4-table schema with HNSW + GIN, connect helper, per-session test schemas
- 2026-11-16 | spec decision 7 | v1 models switched to Amazon first-party (Titan V2, Amazon Rerank 1.0, Nova 2 Lite, Nova Pro judge): AISPL account cannot use Marketplace models; Claude/Cohere kept as upgrade path
- 2026-11-16 | 04 bedrock-client-pricing | bedrock-runtime client (API key or IAM, adaptive retries, empty-token guard), Tokyo price table + cost_usd; live test pending key
- 2026-11-16 | spec decision 8 | main region ap-south-1 (Mumbai); reranker only in ap-northeast-1 (Tokyo) via BEDROCK_RERANK_REGION; Mumbai prices; per-region cached clients
- 2026-11-16 | 05 manifest | 65 documents (25 RBI, 40 GST) copied from official pages, all GST PDFs checked; 7 evidence-backed relations; validator + --check
- 2026-11-16 | 06 downloader | polite httpx downloader (retries, %PDF check, sha256, atomic writes); RBI host shows a CAPTCHA, so it stops and imports hand-saved PDFs via --from-folder
- 2026-11-16 | 07 pdf-parser | pdfplumber parser: Markdown tables with in-text placeholders, header/footer/page-number/ToC cleanup, scanned-page flag; all 65 PDFs parse (1,210 pages, 251 tables)
- 2026-11-16 | 08 chunker | section-aware chunks (400/500 tokens, 60 overlap, never across chapters), tables kept whole with captions; corpus -> 2,265 chunks
- 2026-11-16 | 09 supersession | operative-phrase + reference extraction (boilerplate-proof), repeal/consolidation tables; 61 relations on corpus, 5 of 7 manual links recovered
- 2026-11-16 | 17 rrf-hybrid | rrf_fuse (k=60, rank-based, repeatable ties) and HybridRetriever over any two retrievers
- 2026-11-16 | 21 validator | citation validator (unknown markers, uncited rule sentences), validator chain, abstain decision (weak/insufficient/invalid)
- 2026-11-16 | 23 golden-set | strict JSONL loader (stable schema, extras kept) and 20 unreviewed seed questions across all 5 types
- 2026-11-16 | 24 metrics | recall@k, MRR, citation validity/accuracy, abstention P/R, flag rate, p95 latency (None when undefined)
- 2026-11-16 | 10 embedder | Titan V2 embedder (4 parallel calls, order kept, retries); live: 0.42 s from Mumbai
- 2026-11-16 | 11 reranker | BedrockReranker via InvokeModel (format verified live), NoopReranker; note: Amazon Rerank scores run low (~0.2 for a clear match)
- 2026-11-16 | 12 llm | BedrockLLM over Converse (text blocks only, usage, retries, temperature 0); live: Nova 2 Lite 0.93 s, $0.00015
- 2026-11-16 | 13 repository | transactional document/chunk upsert, relations (both directions, ref -> doc_id), nearest chunk, query logs; fixed db test isolation
- 2026-11-16 | 14 ingest-pipeline | end-to-end ingest (one transaction per document, skip unchanged, dry-run cost); paced Titan calls at 1/s after diagnosing burst throttling
