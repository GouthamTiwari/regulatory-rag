"""Database reads and writes (SPEC section 4). All SQL lives here or in the retrievers.

Conventions:
- Every value goes in through query parameters (%s), never string formatting, so text
  from documents or questions can never become SQL (no SQL injection).
- Functions that write several rows use `conn.transaction()`: all of it happens or none
  of it does. On an autocommit connection that is a real transaction; inside an open
  transaction (as in tests) it becomes a savepoint.
"""

import json
from dataclasses import asdict

import psycopg
from psycopg.rows import dict_row

from regrag.ingest.supersession import normalise_ref
from regrag.types import Chunk, ManifestRow, QueryResult, Relation, RetrievedChunk

# The columns every retriever selects, so all of them build RetrievedChunk the same way.
RETRIEVED_COLUMNS = """
    c.chunk_id, c.doc_id, d.corpus, d.title, c.section_no, c.section_path,
    c.page_start, c.page_end, c.content_type, c.content, d.source_url, d.status
"""


def row_to_retrieved(row: dict) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row["chunk_id"],
        doc_id=row["doc_id"],
        corpus=row["corpus"],
        title=row["title"],
        section_no=row["section_no"] or "",
        section_path=row["section_path"] or "",
        page_start=row["page_start"],
        page_end=row["page_end"],
        content_type=row["content_type"],
        content=row["content"],
        source_url=row["source_url"],
        status=row["status"],
    )


# --- Documents and chunks --------------------------------------------------------------------


def document_state(conn: psycopg.Connection, doc_id: str) -> tuple[str, str] | None:
    """(sha256, embedding_model of its chunks) for a stored document, or None if absent.
    The ingest pipeline uses this to skip documents that have not changed."""
    row = conn.execute(
        """
        SELECT d.sha256, (SELECT min(embedding_model) FROM chunks c WHERE c.doc_id = d.doc_id)
        FROM documents d WHERE d.doc_id = %s
        """,
        (doc_id,),
    ).fetchone()
    return (row[0] or "", row[1] or "") if row else None


def upsert_document(
    conn: psycopg.Connection,
    row: ManifestRow,
    chunks: list[Chunk],
    *,
    page_count: int,
    embedding_model: str,
) -> None:
    """Insert or update a document and replace all its chunks, in one transaction."""
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO documents (doc_id, corpus, doc_type, title, reference_no, applies_to,
                publish_date, updated_as_on, source_url, pdf_url, sha256, page_count, status,
                ingested_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (doc_id) DO UPDATE SET
                corpus = EXCLUDED.corpus, doc_type = EXCLUDED.doc_type, title = EXCLUDED.title,
                reference_no = EXCLUDED.reference_no, applies_to = EXCLUDED.applies_to,
                publish_date = EXCLUDED.publish_date, updated_as_on = EXCLUDED.updated_as_on,
                source_url = EXCLUDED.source_url, pdf_url = EXCLUDED.pdf_url,
                sha256 = EXCLUDED.sha256, page_count = EXCLUDED.page_count,
                status = EXCLUDED.status, ingested_at = now()
            """,
            (
                row.doc_id, row.corpus, row.doc_type, row.title, row.reference_no,
                row.applies_to, row.publish_date, row.updated_as_on, row.source_url,
                row.pdf_url, row.sha256 or None, page_count, row.status,
            ),
        )  # fmt: skip
        conn.execute("DELETE FROM chunks WHERE doc_id = %s", (row.doc_id,))
        insert_chunks(conn, chunks, embedding_model=embedding_model)


def insert_chunks(conn: psycopg.Connection, chunks: list[Chunk], *, embedding_model: str) -> None:
    """Insert chunks (with their vectors) in one batch."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO chunks (doc_id, chunk_index, section_no, section_path, page_start,
                page_end, content_type, content, token_count, embedding, embedding_model)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    c.doc_id, c.chunk_index, c.section_no, c.section_path, c.page_start,
                    c.page_end, c.content_type, c.content, c.token_count, c.embedding,
                    embedding_model,
                )
                for c in chunks
            ],
        )  # fmt: skip


def get_documents(conn: psycopg.Connection, doc_ids: list[str]) -> dict[str, dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM documents WHERE doc_id = ANY(%s)", (list(doc_ids),))
        return {r["doc_id"]: r for r in cur.fetchall()}


def get_chunks(conn: psycopg.Connection, chunk_ids: list[int]) -> list[RetrievedChunk]:
    """Chunks by id, returned in the order the ids were given."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {RETRIEVED_COLUMNS} FROM chunks c JOIN documents d USING (doc_id) "
            "WHERE c.chunk_id = ANY(%s)",
            (list(chunk_ids),),
        )
        by_id = {r["chunk_id"]: row_to_retrieved(r) for r in cur.fetchall()}
    return [by_id[i] for i in chunk_ids if i in by_id]


def top_chunk_for_document(
    conn: psycopg.Connection, doc_id: str, query_embedding: list[float]
) -> RetrievedChunk | None:
    """The chunk of `doc_id` closest in meaning to the question (used to bring in the
    superseding document when an old one was retrieved)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {RETRIEVED_COLUMNS}, 1 - (c.embedding <=> %s::vector) AS score "
            "FROM chunks c JOIN documents d USING (doc_id) "
            "WHERE c.doc_id = %s AND c.embedding IS NOT NULL "
            "ORDER BY c.embedding <=> %s::vector LIMIT 1",
            (query_embedding, doc_id, query_embedding),
        )
        row = cur.fetchone()
    if row is None:
        return None
    chunk = row_to_retrieved(row)
    chunk.vector_score = float(row["score"])
    return chunk


# --- Relations -------------------------------------------------------------------------------


def _ref_index(conn: psycopg.Connection) -> dict[str, str]:
    """normalised reference number -> doc_id, for documents in the corpus."""
    rows = conn.execute("SELECT doc_id, reference_no FROM documents").fetchall()
    return {normalise_ref(ref): doc_id for doc_id, ref in rows if ref}


def _insert_relations(conn: psycopg.Connection, relations: list[Relation]) -> None:
    index = _ref_index(conn)
    with conn.cursor() as cur:
        for rel in relations:
            # Link to a document in our corpus when the reference is one of ours.
            to_doc_id = rel.to_doc_id or index.get(normalise_ref(rel.to_doc_ref))
            cur.execute(
                """
                INSERT INTO document_relations (from_doc_id, relation, to_doc_ref, to_doc_id,
                    scope_note, evidence, source, reviewed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    rel.from_doc_id, rel.relation, rel.to_doc_ref, to_doc_id, rel.scope_note,
                    rel.evidence, rel.source, rel.reviewed,
                ),
            )  # fmt: skip


def replace_relations(
    conn: psycopg.Connection, doc_id: str, relations: list[Relation], *, source: str = "extracted"
) -> None:
    """Replace the `source` relations that start at `doc_id` (re-ingesting a document)."""
    with conn.transaction():
        conn.execute(
            "DELETE FROM document_relations WHERE from_doc_id = %s AND source = %s",
            (doc_id, source),
        )
        _insert_relations(conn, relations)


def load_manual_relations(conn: psycopg.Connection, relations: list[Relation]) -> None:
    """Replace every hand-curated relation with the contents of data/relations.csv."""
    with conn.transaction():
        conn.execute("DELETE FROM document_relations WHERE source = 'manual'")
        _insert_relations(conn, relations)


def get_relations_for(conn: psycopg.Connection, doc_ids: list[str]) -> list[Relation]:
    """Relations where any of `doc_ids` is the source or the target."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT from_doc_id, relation, to_doc_ref, to_doc_id, scope_note, evidence,
                   source, reviewed
            FROM document_relations
            WHERE from_doc_id = ANY(%s) OR to_doc_id = ANY(%s)
            ORDER BY relation_id
            """,
            (list(doc_ids), list(doc_ids)),
        )
        return [Relation(**r) for r in cur.fetchall()]


# --- Query logs ------------------------------------------------------------------------------


def insert_query_log(conn: psycopg.Connection, result: QueryResult) -> None:
    conn.execute(
        """
        INSERT INTO query_logs (query_id, question, route, config_name, retrieved_chunk_ids,
            reranked_chunk_ids, rerank_top_score, abstained, abstain_reason, answer, citations,
            latency_ms, input_tokens, output_tokens, embed_tokens, rerank_queries, cost_usd,
            model_ids)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            result.query_id, result.question, result.route, result.config_name,
            [c.chunk_id for c in result.retrieved], [c.chunk_id for c in result.reranked],
            result.rerank_top_score, result.abstained, result.abstain_reason, result.answer,
            json.dumps([asdict(c) for c in result.citations]), json.dumps(result.latency_ms),
            result.usage.input_tokens, result.usage.output_tokens, result.usage.embed_tokens,
            result.usage.rerank_queries, result.cost_usd, json.dumps(result.model_ids),
        ),
    )  # fmt: skip
