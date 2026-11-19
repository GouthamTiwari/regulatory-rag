# Regulatory RAG: Task breakdown v1

Status: APPROVED 2026-11-16. Read `docs/SPEC.md` first; section numbers below refer to it.

## How to read this file

- Each task is sized for one builder session, on its own branch `task/<NN>-<slug>` in its own worktree.
- **Files** lists every file the task may create (C) or edit (E). A builder must not touch any other file, except its own changelog `docs/changelogs/<NN>-<slug>.md`.
- **Parallel** says which tasks it may run alongside. Two tasks that touch the same file are never parallel.
- Unit tests never call AWS (Bedrock is mocked). Tests marked `live` call real Bedrock; tests marked `db` need the Docker Postgres. Plain `uv run pytest` skips both.
- Every task also ends with: `uv run ruff check .` and `uv run ruff format --check .` pass, and `uv run pytest` passes.

## Parallel groups

Run the groups in order. Inside a group, all tasks can run at the same time.

| Group | Tasks | Needs |
|---|---|---|
| G1 | 01 | nothing |
| G2 | 02 | 01 |
| G3 | 03, 04, 05, 07, 08, 09, 17, 21, 23, 24 | 02 |
| G4 | 06, 10, 11, 12, 13, 15, 16 | G3 (see each task) |
| G5 | 14, 18, 19, 20, 25 | G4 (see each task) |
| G6 | 22, 27 | G5 |
| G7 | 26 | 22, 23, 24, 25 |
| G8 | 28 | 26, 27 |
| G9 | 29 | 28 |

29 tasks in 9 groups.

The groups say what is **safe** to run at the same time, not what must run at once. The orchestrator may run a large group (G3 has 10 tasks, G4 has 7) in waves of 3 to 4 builders. *Why:* each finished branch still needs a changelog check and a review, and smaller waves keep that manageable.

### Shared files and who owns them

These rules are what make the parallel groups safe.

| File | Only these tasks may touch it | Why |
|---|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | 01 | Task 01 installs every dependency the project will need, so no later task edits it |
| `.gitignore`, `.env.example` | 01 | All variables are listed up front |
| `README.md` | 01 (skeleton), 29 (final) | |
| `src/regrag/config.py` | 02 (all settings), 28 (tuned values) | All parameters from SPEC section 5 are defined up front |
| `src/regrag/types.py`, `src/regrag/interfaces.py` | 02 | The contract between tasks |
| Every `__init__.py` under `src/regrag/` and `tests/` | 02 | Stops two tasks creating the same empty file |
| `data/golden/golden.jsonl` | 23, then 27 | |
| `data/manifest.csv`, `data/relations.csv` | 05, then 14 (sha256 and reviewed relations only) | |
| `docs/eval/results.md`, `docs/eval/results.json` | 26 (sample), 28 (real) | |
| `docs/CHANGELOG.md` | orchestrator only | |

If a builder finds it needs a new dependency, a new setting or a change to a type, it stops and reports under "Out of scope / follow-ups". The orchestrator then schedules a small sequential fix task. *Why:* a quiet edit to a shared file is how parallel branches end up in merge conflicts.

---

## Task 01: Repo setup

- **Files:** C `pyproject.toml`, C `uv.lock`, C `.python-version`, E `.gitignore`, C `.env.example`, C `README.md`, C `src/regrag/__init__.py`, C `tests/__init__.py`, C `tests/test_smoke.py`
- **Depends on:** none. **Parallel:** no (first task).
- **Do:**
  - `uv init`-style project named `regrag`, Python 3.12, `src/` layout.
  - Runtime dependencies (all of them, now): `boto3`, `python-dotenv`, `pydantic`, `pydantic-settings`, `psycopg[binary]`, `pgvector`, `pdfplumber`, `httpx`. Dev group: `ruff`, `pytest`, `fpdf2`. *Why `fpdf2`:* Task 07 needs it to generate its small synthetic test PDF; it is pure Python with a permissive licence, and it must be added here because later tasks may not edit `pyproject.toml`.
  - Ruff config in `pyproject.toml` (line length 100, rules E, F, I, UP, B).
  - Pytest config: markers `live` ("calls real Amazon Bedrock, costs money") and `db` ("needs the Docker Postgres"); default options `-m "not live and not db"`.
  - `.gitignore` already exists from the first commit: **extend it, do not replace it**. It must contain `.env`, `.venv/`, `__pycache__/`, `data/raw/`, plus `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`.
  - `.env.example` with **empty values** and a comment per variable: `AWS_REGION`, `AWS_BEARER_TOKEN_BEDROCK`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `BEDROCK_EMBED_MODEL_ID`, `BEDROCK_RERANK_MODEL_ID`, `BEDROCK_LLM_MODEL_ID`, `BEDROCK_JUDGE_MODEL_ID`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`, `DATABASE_URL`. Comments give the recommended values from SPEC section 2 and say "set only one auth option". The comment on `BEDROCK_JUDGE_MODEL_ID` says: leave empty to use the default (Claude Haiku 5.5, for development runs); set it to `global.anthropic.claude-sonnet-5-5` only for the final reported eval run (Task 28).
  - README skeleton with headings only: What this is, Architecture, Setup, Usage, Evaluation results, Design decisions, Disclaimer.
- **Acceptance:**
  - `uv sync` succeeds on Windows; `uv run python -c "import regrag"` and `uv run python -c "import fpdf"` both work.
  - `uv run pytest` passes (one smoke test). `uv run pytest -m live` and `-m db` collect zero tests without error.
  - `uv run ruff check .` and `uv run ruff format --check .` pass.
  - `git check-ignore .env data/raw/x.pdf .venv` prints all three paths.
  - `.env.example` has no value after any `=`.

## Task 02: Config, shared types, interfaces

- **Files:** C `src/regrag/config.py`, C `src/regrag/types.py`, C `src/regrag/interfaces.py`, C `src/regrag/{bedrock,db,ingest,retrieval,query,eval}/__init__.py`, C `tests/{bedrock,db,ingest,retrieval,query,eval}/__init__.py`, C `tests/test_config.py`, C `tests/test_types.py`, C `tests/fakes.py`
- **Depends on:** 01. **Parallel:** no (everything else imports it).
- **Do:**
  - `config.py`: calls `load_dotenv()` then exposes one `Settings` object (pydantic-settings). Contains every parameter in SPEC section 5 with its start value (chunk target 400, max 500, overlap 60, table max 1000, keyword top-k 30, vector top-k 30, RRF k 60, fused 30, rerank top-n 8, abstain threshold 0.30, ef_search 100, max tokens 1500, download delay 2 s, embed concurrency 4), the model IDs and region from SPEC section 2 (the judge model defaults to the Haiku profile when `BEDROCK_JUDGE_MODEL_ID` is empty), and the allowed download hosts. Each has a one-line "why" comment.
  - `types.py`: dataclasses `ManifestRow`, `ParsedPage`, `ParsedDocument`, `Chunk`, `Relation`, `RetrievedChunk`, `EmbedResult`, `Usage`, `Citation`, `DraftAnswer`, `ValidationResult`, `QueryResult`, `PipelineConfig`, and `Route = Literal["rbi","gst","both"]`. `QueryResult` has `to_dict()` / `from_dict()` (JSON-safe).
  - `interfaces.py`: the six Protocols from SPEC section 7, exactly as written there.
  - `tests/fakes.py`: tiny fake implementations of each Protocol for other tasks' tests.
- **Acceptance:**
  - Importing `regrag.config` with no `.env` present does not crash; secrets default to empty.
  - `Settings` never appears in `repr`/logs with secret values (test asserts the bearer token is masked).
  - `QueryResult.from_dict(r.to_dict()) == r` in a test.
  - Fakes satisfy the Protocols (checked with `isinstance` on `runtime_checkable` Protocols).

## Task 03: Docker Postgres + schema

- **Files:** C `docker-compose.yml`, C `src/regrag/db/schema.sql`, C `src/regrag/db/connection.py`, C `src/regrag/db/init.py`, C `tests/db/conftest.py`, C `tests/db/test_schema.py`
- **Depends on:** 02. **Parallel:** G3.
- **Do:** Compose service `db` using `pgvector/pgvector:pg17`, host port from `POSTGRES_PORT` (default 5433), credentials from `.env`, named volume, healthcheck. `schema.sql` per SPEC section 4 (extension, four tables, indexes), safe to run twice. `connection.py` gives a `connect()` helper that registers the pgvector type. `python -m regrag.db.init` applies the schema. `tests/db/conftest.py` provides a fixture that creates a throw-away Postgres schema per test session and drops it afterwards. *Why:* several builders may run `db` tests against the same container at once.
- **Acceptance:**
  - `docker compose up -d` then `uv run python -m regrag.db.init` succeeds twice in a row.
  - `uv run pytest -m db tests/db/test_schema.py` passes: tables and indexes exist; inserting a chunk fills `tsv` automatically; a 1024-length vector round-trips; a 1023-length vector is rejected; deleting a document deletes its chunks.
  - No password is written in `docker-compose.yml`.

## Task 04: Bedrock client + pricing

- **Files:** C `src/regrag/bedrock/client.py`, C `src/regrag/bedrock/pricing.py`, C `tests/bedrock/test_client.py`, C `tests/bedrock/test_pricing.py`, C `tests/bedrock/test_live_auth.py`
- **Depends on:** 02. **Parallel:** G3.
- **Do:** `get_runtime_client(settings)` returns a cached `boto3` `bedrock-runtime` client for the configured region with adaptive retries; raises a clear error naming the missing env vars if neither auth option is set. `pricing.py`: price table from SPEC section 2.4 keyed by model ID (the Amazon v1 models plus the upgrade-path Claude and Cohere IDs), `PRICES_CHECKED_ON`, and `cost_usd(model_id, input_tokens=0, output_tokens=0, rerank_queries=0)`. `rerank_queries` counts Amazon Rerank search units or Cohere queries, whichever the model bills. Unknown model ID raises.
- **Acceptance:**
  - Unit tests: missing credentials give the clear error; cost of 1M Nova 2 Lite input tokens on the global profile is 0.35 and 1M output tokens is 2.95 (Mumbai); 1 Amazon Rerank search unit is 0.001 (Tokyo); 1M Titan tokens is 0.024 (Mumbai).
  - No secret value appears in any exception message or log line (test).
  - Unit test: 1M Nova Pro input tokens cost 0.94 and 1M output tokens cost 3.76; upgrade-path IDs (Haiku 5.5, Sonnet 5.5, Cohere Rerank 3.5) are priced too.
  - `live` test: one minimal `Converse` call to the configured LLM (`global.amazon.nova-2-lite-v1:0`) returns text and a `usage` block. **This is the first proof that the account has Bedrock access from Tokyo.** If it fails with an access or subscription error, the builder stops and reports the exact error (no workarounds). Changelog records which auth option was used (not the key) and confirms or corrects the IAM ARNs in SPEC section 2.3.
  - Before the live test, Goutham has done the two console steps in SPEC section 2.3 (credits confirmed by AWS Support; budget alarm created with "Credits" excluded). The changelog records "done" or "not done", nothing more.

## Task 05: Manifest and relations files

- **Files:** C `data/manifest.csv`, C `data/relations.csv`, C `src/regrag/ingest/manifest.py`, C `tests/ingest/test_manifest.py`
- **Depends on:** 02. **Parallel:** G3.
- **Do:** Loader/validator per SPEC section 5 (required columns, date formats, unique `doc_id`, allowed hosts, allowed `status`). Fill `manifest.csv` with the 25 RBI and 40 GST rows from SPEC section 3: for each RBI row open the page and copy the **exact title, reference number, date and PDF link**; for GST use the verified paths. Any row whose URL cannot be confirmed gets `status=to_verify` and is skipped by the loader with a warning. Seed `relations.csv` with the known links listed in SPEC section 3.4.
- **Acceptance:**
  - `uv run python -m regrag.ingest.manifest --check` prints counts per corpus and exits 0.
  - Tests: a row with a non-official host is rejected; duplicate `doc_id` is rejected; `to_verify` rows are skipped, not fatal.
  - No URL was invented: the changelog lists every row left as `to_verify` and why.
  - `relations.csv` has at least 6 rows, each with an `evidence` note.

## Task 06: Downloader

- **Files:** C `src/regrag/ingest/download.py`, C `tests/ingest/test_download.py`
- **Depends on:** 05. **Parallel:** G4.
- **Do:** Download each manifest PDF to `data/raw/<doc_id>.pdf` with `httpx`: 2 s delay, 60 s timeout, 3 retries, a plain generic User-Agent, TLS verification on. Compute sha256. Skip existing files whose hash matches. Reject responses that are not PDFs (check the `%PDF` header). `--limit N` and `--only <doc_id>` flags. Print a summary table of ok / skipped / failed.
- **Acceptance:**
  - Unit tests with `httpx.MockTransport`: success, retry then success, HTML returned instead of PDF is a failure, hash mismatch is reported, existing file is skipped.
  - No test touches the network.
  - A failed document does not stop the run; exit code is non-zero if any failed.
  - `git status` shows nothing under `data/raw/` after a run.

## Task 07: PDF parser (tables kept)

- **Files:** C `src/regrag/ingest/parse.py`, C `tests/ingest/test_parse.py`, C `tests/ingest/make_fixture_pdf.py`, C `tests/fixtures/sample_direction.pdf`
- **Depends on:** 02. **Parallel:** G3.
- **Do:** `parse_pdf(path) -> ParsedDocument` with `pdfplumber`: per page, text in reading order and tables converted to Markdown tables (table text is not repeated in the body text). Strip repeated headers/footers and bare page numbers. Flag pages with under 50 characters as `scanned`. The fixture PDF is a small synthetic 3-page document written for the test (headings, paragraphs, one table, a footer); it is generated by `make_fixture_pdf.py` using `fpdf2` (already installed as a dev dependency by Task 01; do not edit `pyproject.toml`) and contains no real regulatory text. Both the script and the generated PDF are committed, so tests do not need to regenerate it.
- **Acceptance:**
  - Fixture test: 3 pages returned, page numbers are 1-based, the table appears once as Markdown with its header row, the footer text is absent.
  - A deliberately empty page is flagged `scanned` and does not crash.
  - The fixture PDF is under 100 KB.

## Task 08: Section-aware chunker

- **Files:** C `src/regrag/ingest/chunk.py`, C `tests/ingest/test_chunk.py`
- **Depends on:** 02. **Parallel:** G3.
- **Do:** `chunk_document(parsed, manifest_row, settings) -> list[Chunk]` per SPEC section 5: heading detection for RBI style (Chapter, Part, numbered paragraphs, Annex) and GST circular style ("2.", "3.1", "Issue / Clarification" tables); pack to target 400 / max 500 tokens with 60 overlap inside a section; never split a table under 1,000 tokens; repeat the header row when a big table is split; fill `section_no`, `section_path`, `page_start`, `page_end`, `content_type`, `token_count`. Provide `embedding_text(chunk, title)` that prefixes title and section path. Token estimate = characters / 4.
- **Acceptance (all on hand-built `ParsedDocument` objects, no PDFs needed):**
  - No chunk exceeds 500 tokens, except single tables up to 1,000.
  - A chunk never mixes two top-level sections.
  - A paragraph spanning pages 2 to 3 yields `page_start=2, page_end=3`.
  - Adjacent chunks in the same section share about 60 tokens.
  - `chunk_index` is 0..n-1 with no gaps; running twice gives identical output.

## Task 09: Supersession extraction

- **Files:** C `src/regrag/ingest/supersession.py`, C `tests/ingest/test_supersession.py`
- **Depends on:** 02. **Parallel:** G3.
- **Do:** `extract_relations(doc_id, chunks) -> list[Relation]` using the phrase list in SPEC section 3.4. Recognise GST circular numbers (`NNN/NN/YYYY-GST`), RBI reference numbers (`RBI/YYYY-YY/NNN`, department-style references) and "Master Direction ... dated ...". Each relation carries the sentence as `evidence`, `source='extracted'`, `reviewed=False`. Also `normalise_ref(text)` so "Circular No. 195/07/2023 - GST" and "195/07/2023-GST" compare equal.
- **Acceptance:**
  - At least 12 test sentences (written for the test, in the style of real circulars) covering supersedes / amends / withdraws / corrects, with the right relation and target reference extracted.
  - At least 4 negative sentences (for example "this does not supersede ...", a bare mention of another circular) produce no relation.
  - `normalise_ref` test with 5 spelling variants.

## Task 10: Embedder (Titan V2)

- **Files:** C `src/regrag/bedrock/embedder.py`, C `tests/bedrock/test_embedder.py`
- **Depends on:** 04. **Parallel:** G4.
- **Do:** `TitanEmbedder` implementing `Embedder`: one `InvokeModel` call per text with `{"inputText", "dimensions": 1024, "normalize": true}`, up to 4 concurrent calls, order preserved, token counts summed from `inputTextTokenCount`. Texts over about 7,500 estimated tokens are truncated with a warning.
- **Acceptance:**
  - Mocked tests: order preserved with concurrency; throttling error is retried; token total is correct; empty list returns empty result without calling AWS.
  - `live` test: two sentences give two 1024-length vectors with length about 1.0; the changelog records observed latency from the configured region.

## Task 11: Reranker (Amazon Rerank 1.0, Cohere adapter)

- **Files:** C `src/regrag/bedrock/reranker.py`, C `tests/bedrock/test_reranker.py`
- **Depends on:** 04. **Parallel:** G4.
- **Do:** `BedrockReranker` implementing `Reranker` via `InvokeModel` on `bedrock-runtime` (not the `bedrock-agent-runtime` Rerank API: that one does not accept Bedrock API keys). It gets its client with `get_runtime_client(settings, region=settings.bedrock_rerank_region)` (Tokyo; Mumbai has no reranker, SPEC decision 8). It picks a small request/response adapter from the model ID: `amazon.rerank-v1:0` (the v1 default) and `cohere.rerank-v3-5:0` (upgrade path); an unknown ID raises. Sends at most 100 documents per call. Returns chunks sorted by score with `rerank_score` set; records `rerank_queries` for cost. Also `NoopReranker` that returns the first `top_n` unchanged (used by the non-rerank eval configurations).
- **Acceptance:**
  - Mocked tests: response indexes map back to the right chunks; `top_n` respected; more than 100 chunks is split and billed as 2 queries; empty input makes no call; both adapters build the right request body.
  - `live` test (Amazon Rerank only; Cohere is not accessible on this account): 3 short passages, the obviously relevant one ranks first. **The changelog confirms the exact request/response field names and what one billed search unit covers** (SPEC marks them "to verify").

## Task 12: LLM wrapper (Converse; Nova 2 Lite by default)

- **Files:** C `src/regrag/bedrock/llm.py`, C `tests/bedrock/test_llm.py`
- **Depends on:** 04. **Parallel:** G4.
- **Do:** `BedrockLLM.complete(system, user, max_tokens) -> (text, Usage)` using `Converse` with the configured model or inference profile ID; it works for Nova and Claude alike, with no model-specific code. Sends `temperature=0`. Extracts only text blocks (ignores reasoning/thinking blocks), returns input/output tokens from `usage`, raises a clear error on `stopReason == "max_tokens"` with empty text.
- **Acceptance:**
  - Mocked tests: text extracted when the response also contains a non-text block; usage mapped; throttling retried.
  - `live` test: a one-line prompt to Nova 2 Lite returns text; the changelog records latency from Tokyo and the output-token count for a short answer.

## Task 13: Repository (database reads and writes)

- **Files:** C `src/regrag/db/repository.py`, C `tests/db/test_repository.py`
- **Depends on:** 03. **Parallel:** G4.
- **Do:** Functions: `upsert_document` (replaces the document's chunks in one transaction), `insert_chunks` (batched, with vectors), `replace_relations(doc_id, relations)`, `load_manual_relations(csv rows)`, `get_documents(doc_ids)`, `get_relations_for(doc_ids)` (both directions), `get_chunks(chunk_ids)`, `top_chunk_for_document(doc_id, query_embedding)`, `insert_query_log(QueryResult, extras)`. Also resolves `to_doc_ref` to `to_doc_id` when the referenced document is in the corpus (using `normalise_ref` logic duplicated as a tiny local helper if Task 09 is not merged yet; note it in the changelog).
- **Acceptance (`db` tests):**
  - Re-upserting a document leaves exactly the new chunk set.
  - A failure midway through `insert_chunks` leaves the old chunks intact.
  - Relations are returned for a document whether it is the `from` or the `to` side.
  - A query log row round-trips, including arrays and JSON.

## Task 14: Ingest pipeline (end to end)

- **Files:** C `src/regrag/ingest/pipeline.py`, C `tests/ingest/test_pipeline.py`, E `data/manifest.csv` (sha256 column only), E `data/relations.csv` (append reviewed rows only)
- **Depends on:** 06, 07, 08, 09, 10, 13. **Parallel:** G5.
- **Do:** `python -m regrag.ingest.pipeline [--only doc_id] [--limit N] [--skip-download] [--dry-run]`: manifest → download → parse → chunk → extract relations → embed → store, per document, with a progress line and a final summary (documents, chunks, tables, scanned pages, embed tokens, cost). One failing document is reported and skipped. `--dry-run` does everything except Bedrock and database writes, and prints the estimated embedding cost. Then run it for real on the full manifest and commit the updated sha256 values. Print extracted relations for Goutham to review; only reviewed ones are appended to `relations.csv`.
- **Acceptance:**
  - Unit test with fakes: 2 documents in, expected calls made in order; a parse failure in one does not stop the other.
  - Real run: at least 60 of 65 documents ingested; the changelog reports chunk count, table-chunk count, scanned pages, total embed tokens and cost, and lists any failed documents with reasons.
  - Running the pipeline a second time creates no duplicate chunks and costs nothing for unchanged documents (skips documents whose sha256 and `embedding_model` are unchanged).

## Task 15: Keyword retriever ("BM25" leg)

- **Files:** C `src/regrag/retrieval/keyword.py`, C `tests/retrieval/test_keyword.py`
- **Depends on:** 03. **Parallel:** G4.
- **Do:** `KeywordRetriever` implementing `Retriever`: `websearch_to_tsquery('english', q)` against `chunks.tsv`, ranked by `ts_rank_cd`, filtered by route through a join on `documents.corpus`. If the strict query returns fewer than 5 rows, retry with the terms OR-ed together. *Why:* natural-language questions rarely contain every word of the right paragraph.
- **Acceptance (`db` tests with a handful of inserted chunks):**
  - A query for an exact circular number finds the chunk containing it at rank 1.
  - Route `gst` never returns an RBI chunk.
  - A question with no matching terms returns an empty list, not an error.
  - Punctuation and quotes in the question do not raise a SQL error.

## Task 16: Vector retriever

- **Files:** C `src/regrag/retrieval/vector.py`, C `tests/retrieval/test_vector.py`
- **Depends on:** 03. **Parallel:** G4.
- **Do:** `VectorRetriever` implementing `Retriever`, constructed with an `Embedder`: embed the question, set `hnsw.ef_search` for the transaction, order by cosine distance, filter by route, return `vector_score = 1 - distance`. Exposes the embed token count for cost logging.
- **Acceptance (`db` tests using the fake embedder with hand-made vectors):**
  - Nearest vector is rank 1; route filter respected; `top_k` respected even when the filter removes many rows.
  - The embedder is called exactly once per query.

## Task 17: RRF fusion + hybrid retriever

- **Files:** C `src/regrag/retrieval/fusion.py`, C `src/regrag/retrieval/hybrid.py`, C `tests/retrieval/test_fusion.py`, C `tests/retrieval/test_hybrid.py`
- **Depends on:** 02. **Parallel:** G3.
- **Do:** `rrf_fuse(lists, k=60, top_k=30)`: pure function, score = sum over lists of `1/(k+rank)`, ties broken by `chunk_id` for repeatable output. `HybridRetriever` implementing `Retriever`, built from any two `Retriever`s. Keeps each chunk's original ranks for logging.
- **Acceptance:**
  - Hand-computed example in a test (3 chunks, 2 lists) matches to 6 decimal places.
  - A chunk present in both lists outranks one that is rank 1 in only one list when the arithmetic says so.
  - Works when one list is empty. Uses fake retrievers only; no database.

## Task 18: Router

- **Files:** C `src/regrag/query/router.py`, C `tests/query/test_router.py`
- **Depends on:** 12. **Parallel:** G5.
- **Do:** `RuleThenLLMRouter` implementing `Router` per SPEC section 5: keyword rules first, LLM fallback constrained to one word, anything unparseable becomes `both`. Records which path decided (for the log) and any LLM usage.
- **Acceptance:**
  - Table-driven test of at least 20 questions (8 RBI, 8 GST, 4 both) decided by rules alone with no LLM call.
  - Ambiguous question triggers exactly one LLM call (mocked); garbage LLM output gives `both`.

## Task 19: Supersession filter/flag

- **Files:** C `src/regrag/query/supersession.py`, C `tests/query/test_supersession_filter.py`
- **Depends on:** 13. **Parallel:** G5.
- **Do:** `apply_supersession(chunks, documents, relations, fetch_replacement) -> (chunks, notes)` implementing the rules in SPEC section 5. Pure logic: the database lookups are passed in as data/callables so unit tests need no database. Notes are plain sentences such as "Circular 195/07/2023-GST was updated by Circular 216/10/2024-GST."
- **Acceptance:**
  - Superseded document with replacement in corpus: at most one old chunk kept, it is marked, the replacement's chunk is present, a note is produced.
  - Superseded document with replacement not in corpus: chunk kept and marked, note names the reference.
  - Amended document: nothing removed, note produced.
  - Active documents: output identical to input, no notes.

## Task 20: Generator with citations

- **Files:** C `src/regrag/query/prompts.py`, C `src/regrag/query/generate.py`, C `tests/query/test_generate.py`
- **Depends on:** 12. **Parallel:** G5.
- **Do:** `CitedGenerator` implementing `Generator`: builds the context block (`[C1] title | section | pages | status` then the text), the system prompt (answer only from the context; `[C#]` after every claim; mention supersession marks; reply exactly `INSUFFICIENT_EVIDENCE` when the context does not answer; no legal advice), calls the LLM, parses markers into `DraftAnswer`.
- **Acceptance (mocked LLM):**
  - Prompt contains every chunk exactly once with a unique marker, and superseded chunks carry their mark.
  - Markers `[C1]`, `[C2][C3]` and `[C1, C2]` are all parsed.
  - `INSUFFICIENT_EVIDENCE` sets `draft.insufficient = True` with no citations.
  - Chunk text containing instructions (for example "ignore previous instructions") is still placed inside the delimited context block, and the system prompt says context is data, not instructions.

## Task 21: Validator and abstention

- **Files:** C `src/regrag/query/validate.py`, C `tests/query/test_validate.py`
- **Depends on:** 02. **Parallel:** G3.
- **Do:** `CitationValidator` implementing `Validator` (checks a, b from SPEC section 5) and `decide_abstain(top_rerank_score, draft, validation, threshold)` returning `(abstained, reason)`. Also `run_validators(validators, ...)` that runs a list in order and stops at the first failure. *Why a list:* this is the plug-in point for the future guardrails project.
- **Acceptance:**
  - Unknown marker fails; rule sentence without a marker fails; a clean answer passes.
  - Score 0.29 with threshold 0.30 abstains with reason `weak_evidence`; score `None` (no reranker) does not trigger the threshold rule.
  - A second, fake validator in the list can force abstention.

## Task 22: Query pipeline, logging, command line

- **Files:** C `src/regrag/query/pipeline.py`, C `src/regrag/query/querylog.py`, C `src/regrag/query/__main__.py`, C `tests/query/test_pipeline.py`, C `tests/query/test_pipeline_live.py`
- **Depends on:** 11, 13, 15, 16, 17, 18, 19, 20, 21. **Parallel:** G6 (with 27).
- **Do:** `answer_question(question, *, config=None) -> QueryResult`: the single entry point (SPEC section 7). `build_pipeline(config_name)` wires the real parts for `bm25`, `vector`, `hybrid`, `hybrid_rerank`. Times each stage, sums usage, computes cost with `pricing.py`, writes `query_logs` and one JSON log line. On abstention the answer is a fixed polite message plus the reason, with the closest documents listed as "you may want to read". `uv run python -m regrag.query "question" [--config NAME] [--json]` prints the answer, citations (document, section, page, URL), supersession notes, cost and the disclaimer.
- **Acceptance:**
  - Unit test with all fakes: stages run in the order in SPEC section 5; result has cost, per-stage latency and citations; a failing validator leads to one regeneration then abstention.
  - Each of the four configurations builds without error.
  - `answer_question` prints nothing itself and returns a JSON-serialisable result.
  - `live` + `db` test on the ingested corpus: example question 4 (demo vehicles) returns a non-abstained answer citing `gst-231-25-2024`; example question 10 (income tax) abstains.

## Task 23: Golden set schema, loader, seed questions

- **Files:** C `data/golden/golden.jsonl`, C `src/regrag/eval/golden.py`, C `tests/eval/test_golden.py`
- **Depends on:** 02. **Parallel:** G3.
- **Do:** Loader/validator for the schema in SPEC section 6.1 (required fields, allowed values, unique ids, unknown extra fields tolerated, `reviewed=false` rows excluded unless `--include-unreviewed`). Seed 20 hand-written rows: the 10 example questions from SPEC section 1 plus 10 more (at least 3 `superseded`, 3 `abstain`, 2 `cross_corpus`). Reference answers may be left as `"TODO: Goutham to confirm"` with `reviewed=false` where the builder cannot read the source document.
- **Acceptance:**
  - `uv run python -m regrag.eval.golden --check` prints counts by type and corpus and exits 0.
  - Tests: bad `type` rejected; duplicate id rejected; extra field accepted; abstain rows must have empty `expected_doc_ids`.
  - Every `expected_doc_ids` value exists in the manifest (checked only if `data/manifest.csv` is present).

## Task 24: Metrics

- **Files:** C `src/regrag/eval/metrics.py`, C `tests/eval/test_metrics.py`
- **Depends on:** 02. **Parallel:** G3.
- **Do:** Pure functions for every metric in SPEC section 6.3: `is_relevant`, `recall_at_k`, `mrr`, `citation_validity`, `citation_accuracy`, `abstention_scores` (accuracy, precision, recall), `supersession_flag_rate`, `latency_summary` (mean, p95). Inputs are plain dataclasses/dicts; no database, no AWS.
- **Acceptance:**
  - Each metric has a hand-computed test, including the edge cases: no relevant chunk (MRR 0), no citations (validity defined as 1.0, accuracy excluded), zero abstentions (precision reported as `None`, not a crash).
  - Section-level match falls back to document-level when `expected_sections` is empty.

## Task 25: Faithfulness judge

- **Files:** C `src/regrag/eval/judge.py`, C `tests/eval/test_judge.py`
- **Depends on:** 12. **Parallel:** G5.
- **Do:** `judge_faithfulness(answer, cited_chunks, llm) -> (score, per_sentence, usage)`: splits the answer into sentences, asks the judge model for a JSON list of `supported`/`unsupported` with a short reason, parses it strictly, retries once on bad JSON, returns `None` (not 0) if it still fails. The judge model comes from settings (`BEDROCK_JUDGE_MODEL_ID`; default Nova 2 Lite for development, Nova Pro for the final run in Task 28, Claude Sonnet 5.5 on the upgrade path). The code must not assume which model it is: no model name in the prompt, and it reads only text blocks from the reply, because some models (Claude Sonnet) also return thinking blocks. Returns the judge model ID alongside the usage so the report can show it.
- **Acceptance (mocked LLM):**
  - 3 of 4 sentences supported gives 0.75.
  - Malformed JSON is retried once, then yields `None` and is counted as "judge failed".
  - Citation markers and the disclaimer line are not counted as sentences.
  - Changing the judge model ID in settings changes the `modelId` sent (asserted on the mock) with no other code change.

## Task 26: Eval runner and report

- **Files:** C `src/regrag/eval/run.py`, C `src/regrag/eval/__main__.py`, C `tests/eval/test_run.py`, C `docs/eval/results.md`, C `docs/eval/results.json`
- **Depends on:** 22, 23, 24, 25. **Parallel:** no (G7).
- **Do:** `uv run python -m regrag.eval [--configs bm25,vector,hybrid,hybrid_rerank] [--retrieval-only] [--limit N] [--out docs/eval]`: for each configuration and each reviewed golden question, call `answer_question` (or only the retriever in `--retrieval-only`), compute all metrics, write a Markdown comparison table and raw JSON (per-question rows included), and print total cost. Before starting it prints the estimated cost, the question count and the judge model ID. The table uses the honest labels from SPEC section 6.4 (the `bm25` config is shown as "keyword (Postgres FTS, BM25-like)"). Commit a **sample** result from the 20 seed questions, run with the default Nova 2 Lite judge and clearly labelled "sample, not final".
- **Acceptance:**
  - Unit test with a fake pipeline: 4 configurations x 3 questions produce a table with 4 rows and all metric columns; a question that raises is recorded as an error row and the run continues.
  - `--retrieval-only` makes zero LLM and zero rerank calls for `bm25`, `vector`, `hybrid` (asserted with fakes).
  - `results.md` states date, golden-set size, model IDs (generator and judge separately), region and `PRICES_CHECKED_ON`.
  - The cost estimate uses the judge model's own price (test: switching the judge to the Nova Pro ID raises the estimate).
  - The string "BM25" never appears alone as a row label in `results.md`.

## Task 27: Grow the golden set to ~120

- **Files:** C `src/regrag/eval/draft_questions.py`, C `tests/eval/test_draft_questions.py`, E `data/golden/golden.jsonl`
- **Depends on:** 14, 23. **Parallel:** G6 (with 22).
- **Do:** `python -m regrag.eval.draft_questions --per-corpus 60 --out data/golden/drafts.jsonl`: samples chunks spread across documents (and a set of table chunks), asks the default LLM (Nova 2 Lite) for candidate question + answer + the section it came from, writes drafts with `source="llm_drafted", reviewed=false`. `drafts.jsonl` is a scratch file and is **not** committed (the builder adds nothing to `.gitignore`; it simply does not stage it, and says so in the changelog). Goutham reviews; accepted rows are appended to `golden.jsonl` with `reviewed=true`. Hand-write the `superseded`, `cross_corpus` and `abstain` rows to reach the counts in SPEC section 6.2.
- **Acceptance:**
  - Mocked test: sampling covers every document at least once before repeating; output rows validate against the loader.
  - `golden.jsonl` has at least 110 reviewed rows with counts per type within 3 of the plan in SPEC section 6.2. **Fallback, only if Goutham says review time has run short: at least 60 reviewed rows** with the halved mix in SPEC section 6.2 (18 RBI, 18 GST, 5 table, 5 cross-corpus, 7 superseded, 7 abstain; each within 2). The changelog states which target was used and the final counts per type.
  - Every reviewed row was confirmed by Goutham (recorded in the changelog as a count, not as names of files outside the repo).

## Task 28: Full evaluation and tuning

- **Files:** E `src/regrag/config.py` (tuned values only), E `docs/eval/results.md`, E `docs/eval/results.json`, C `docs/eval/tuning-notes.md`
- **Depends on:** 26, 27. **Parallel:** no (G8).
- **Do:** Two phases. **Phase 1, tuning (Nova 2 Lite judge, the default):** run the full four-way evaluation and tune as described below. **Phase 2, final reported run (Nova Pro judge):** with the tuned settings frozen, run the four-way evaluation once more with `BEDROCK_JUDGE_MODEL_ID=apac.amazon.nova-pro-v1:0` set in the local `.env` (or the shell) for this run only; expected cost about $2.50. This run produces the committed `results.md` / `results.json`. The default in `config.py` stays Nova 2 Lite. Do one single Nova Pro call first to confirm access before starting the full run; if it is not accessible, stop and report rather than publishing self-judged numbers as final. Tuning details: Choose the abstain threshold by sweeping 0.05 to 0.60 on the `hybrid_rerank` results and picking the value with the best abstention accuracy (the sweep reuses stored rerank scores, so it costs nothing). Try at most two further changes (for example rerank top-n 6 vs 8) and keep only what improves the numbers. Write what was tried and why in `tuning-notes.md`.
- **Acceptance:**
  - `results.md` has the final table for all four configurations on the full reviewed set, with total cost of the run, the number of questions used, and the judge model shown as Amazon Nova Pro (`apac.amazon.nova-pro-v1:0`).
  - `tuning-notes.md` also shows faithfulness from the Nova-2-Lite-judged run next to the Nova-Pro-judged run for `hybrid_rerank`, so the reader can see how much the judge matters.
  - `git diff` shows `BEDROCK_JUDGE_MODEL_ID` default unchanged (Nova 2 Lite) and no `.env` committed.
  - Citation validity is 100% for every configuration (if not, that is a bug to send back, not a number to report).
  - `tuning-notes.md` lists each changed setting: old value, new value, metric before and after.
  - All tests still pass with the new defaults.

## Task 29: Final README

- **Files:** E `README.md`
- **Depends on:** 28. **Parallel:** no (G9).
- **Do:** Complete the README: what the project is and is not (disclaimer); a Mermaid architecture diagram of both the ingest and query flows from `CLAUDE.md`; setup steps for Windows PowerShell (clone, `uv sync`, copy `.env.example` to `.env`, choose one auth option, `docker compose up -d`, init schema, ingest, ask a question, run the eval); the eval results table copied from `docs/eval/results.md` with a two-line reading of it; "Design decisions" (region choice and why not Mumbai, why hybrid + RRF, why rerank via `InvokeModel`, why Postgres for both searches and why the keyword leg is labelled "keyword (Postgres FTS, BM25-like)" rather than BM25, how supersession is handled, why abstain, why the final judge is Sonnet while development uses Haiku); cost notes including the credits and budget-alarm advice from SPEC section 2.3; "Extension points" summary linking to SPEC section 10; known limitations (GST circulars 251 and above are not included; golden-set size actually used).
- **Acceptance:**
  - A fresh clone can go from nothing to a first answer by following only the README (reviewer walks through the commands).
  - The Mermaid block renders on GitHub.
  - The numbers in the README table equal those in `docs/eval/results.md`, and the keyword row uses the label "keyword (Postgres FTS, BM25-like)".
  - No secret, account ID, employer name or personal detail appears anywhere in the file.

## Task 30: Web page (added after v1)

- **Files:** N `src/regrag/ui/__init__.py`, `src/regrag/ui/view.py`, `src/regrag/ui/app.py`, `tests/ui/`; E `pyproject.toml`, `uv.lock`, `.gitignore`, `README.md`, `docs/SPEC.md` (non-goal line).
- **Depends on:** 22. **Scope change:** agreed by the owner on 2026-11-16 ("Web UI is something that we can add later on").
- **Do:** A Streamlit page that calls `answer_question()`: question box, example questions, search-setup dropdown (the four eval configs), the answer, a refusal warning with a plain reason, supersession notes, source cards (title, section, pages, official link, "superseded" badge), and time/cost. Display logic lives in a Streamlit-free module so it can be unit-tested.
- **Acceptance:**
  - `uv run streamlit run src/regrag/ui/app.py` answers a real question with sources.
  - Unit tests cover the display helpers and run the page with the pipeline mocked (no AWS, no Docker).

## Task 31: Spell out abbreviations (added after v1)

- **Files:** N `src/regrag/query/abbreviations.py`, `tests/query/test_abbreviations.py`; E `src/regrag/query/pipeline.py`, `README.md`.
- **Why:** "What is RCM?" was refused (top rerank score 0.0051 < 0.01, routed to both) although 5 GST circulars cover reverse charge.
- **Acceptance:** "What is RCM?" routes to GST and gets a cited answer; the result keeps the question as typed; unit tests need no AWS or Docker.
