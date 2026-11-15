-- regrag database schema (docs/SPEC.md section 4).
-- Safe to run repeatedly: every statement uses IF NOT EXISTS.
-- Table names are unqualified on purpose, so tests can apply this file inside a
-- throw-away schema (via search_path) without touching the real tables.

-- pgvector lives in "public" so every schema on the search_path can use the vector type.
CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;

CREATE TABLE IF NOT EXISTS documents (
    doc_id        text PRIMARY KEY,                 -- stable slug, e.g. rbi-13141
    corpus        text NOT NULL CHECK (corpus IN ('rbi', 'gst')),
    doc_type      text,
    title         text NOT NULL,
    reference_no  text,
    applies_to    text,
    publish_date  date NOT NULL,
    updated_as_on date,
    source_url    text NOT NULL,
    pdf_url       text NOT NULL,
    sha256        text,                             -- detects silently replaced PDFs
    page_count    integer,
    status        text NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'superseded', 'withdrawn')),
    ingested_at   timestamptz
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_id          text NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
    chunk_index     integer NOT NULL,
    section_no      text,
    section_path    text,
    page_start      integer,
    page_end        integer,
    content_type    text NOT NULL DEFAULT 'text' CHECK (content_type IN ('text', 'table')),
    content         text NOT NULL,
    token_count     integer,
    embedding       vector(1024),                   -- Titan V2 output size
    embedding_model text,                           -- tells us which rows are stale after a model change
    -- Filled by Postgres itself on every insert/update, so it can never drift from content.
    tsv             tsvector GENERATED ALWAYS AS (
                        to_tsvector('english', coalesce(section_path, '') || ' ' || content)
                    ) STORED,
    -- The unique index also serves lookups by doc_id (its leading column).
    UNIQUE (doc_id, chunk_index),
    CHECK (page_end >= page_start)
);

CREATE TABLE IF NOT EXISTS document_relations (
    relation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_doc_id text NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
    relation    text NOT NULL
                CHECK (relation IN ('supersedes', 'amends', 'withdraws', 'clarifies', 'corrects')),
    to_doc_ref  text NOT NULL,                      -- always filled, e.g. 195/07/2023-GST
    -- Only set when the target is in our corpus; cleared (not deleted) if it is removed.
    to_doc_id   text REFERENCES documents (doc_id) ON DELETE SET NULL,
    scope_note  text NOT NULL DEFAULT '',
    evidence    text NOT NULL DEFAULT '',
    source      text NOT NULL CHECK (source IN ('manual', 'extracted')),
    reviewed    boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS query_logs (
    query_id            uuid PRIMARY KEY,
    created_at          timestamptz NOT NULL DEFAULT now(),
    question            text NOT NULL,
    route               text,
    config_name         text,
    retrieved_chunk_ids bigint[],
    reranked_chunk_ids  bigint[],
    rerank_top_score    real,
    abstained           boolean NOT NULL DEFAULT false,
    abstain_reason      text,
    answer              text,
    citations           jsonb,
    latency_ms          jsonb,                      -- per stage
    input_tokens        integer,
    output_tokens       integer,
    embed_tokens        integer,
    rerank_queries      integer,
    cost_usd            numeric(10, 6),
    model_ids           jsonb
);

-- HNSW: good recall with no tuning, and unlike IVFFlat it doesn't need data loaded first.
-- Cosine, because Titan vectors are normalised and cosine is the usual choice for text.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
-- GIN makes full-text (keyword) search fast.
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS documents_corpus_status_idx ON documents (corpus, status);
CREATE INDEX IF NOT EXISTS relations_from_doc_idx ON document_relations (from_doc_id);
CREATE INDEX IF NOT EXISTS relations_to_doc_idx ON document_relations (to_doc_id);
CREATE INDEX IF NOT EXISTS query_logs_created_at_idx ON query_logs (created_at);
