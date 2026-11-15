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
