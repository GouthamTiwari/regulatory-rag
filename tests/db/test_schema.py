"""Schema checks against the Docker Postgres (marked `db`), plus two no-database checks."""

import psycopg
import pytest

from regrag.config import Settings
from regrag.db.connection import connect
from regrag.db.init import apply_schema
from tests.db.conftest import insert_document

EXPECTED_TABLES = {"documents", "chunks", "document_relations", "query_logs"}
EXPECTED_INDEXES = {
    "chunks_embedding_hnsw",
    "chunks_tsv_gin",
    "documents_corpus_status_idx",
    "relations_from_doc_idx",
    "relations_to_doc_idx",
    "query_logs_created_at_idx",
}


def _insert_chunk(conn, doc_id="gst-231-25-2024", index=0, embedding=None, **overrides):
    values = {
        "section_path": "Para 3 > Demo vehicles",
        "page_start": 1,
        "page_end": 1,
        "content": "Input tax credit is available on demo vehicles used for business.",
    }
    values.update(overrides)
    return conn.execute(
        """
        INSERT INTO chunks (doc_id, chunk_index, section_path, page_start, page_end,
                            content, embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING chunk_id
        """,
        (
            doc_id,
            index,
            values["section_path"],
            values["page_start"],
            values["page_end"],
            values["content"],
            embedding,
        ),
    ).fetchone()[0]


# --- No database needed ------------------------------------------------------------------


def test_invalid_schema_name_is_rejected():
    with pytest.raises(ValueError):
        connect(Settings(), schema="x; DROP TABLE documents")


def test_unreachable_database_error_hides_password(monkeypatch):
    # Simulate the failure instead of connecting for real: on Windows a refused
    # connection takes ~5 s, and this test should be instant and need no Docker.
    def refuse(*args, **kwargs):
        raise psycopg.OperationalError("connection to 127.0.0.1 failed: pw-must-not-leak")

    monkeypatch.setattr(psycopg, "connect", refuse)
    s = Settings(postgres_port=5433, postgres_password="pw-must-not-leak")
    with pytest.raises(RuntimeError) as info:
        connect(s)
    assert "pw-must-not-leak" not in str(info.value)
    assert "docker compose up -d" in str(info.value)


# --- Docker Postgres ---------------------------------------------------------------------


@pytest.mark.db
def test_tables_exist(db_conn):
    rows = db_conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
    ).fetchall()
    assert EXPECTED_TABLES <= {r[0] for r in rows}


@pytest.mark.db
def test_indexes_exist_and_vector_index_is_hnsw(db_conn):
    rows = db_conn.execute(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()"
    ).fetchall()
    defs = dict(rows)
    assert EXPECTED_INDEXES <= set(defs)
    assert "USING hnsw" in defs["chunks_embedding_hnsw"]
    assert "vector_cosine_ops" in defs["chunks_embedding_hnsw"]
    assert "USING gin" in defs["chunks_tsv_gin"]


@pytest.mark.db
def test_schema_can_be_applied_twice(db_conn):
    apply_schema(db_conn)  # the fixture already applied it once


@pytest.mark.db
def test_tsv_is_filled_automatically(db_conn):
    insert_document(db_conn)
    chunk_id = _insert_chunk(db_conn)
    matched = db_conn.execute(
        "SELECT tsv @@ to_tsquery('english', 'vehicle & credit') FROM chunks WHERE chunk_id = %s",
        (chunk_id,),
    ).fetchone()[0]
    assert matched is True  # "vehicles" matched "vehicle": the English stemmer is working


@pytest.mark.db
def test_1024_vector_round_trips(db_conn):
    insert_document(db_conn)
    vec = [i / 1024 for i in range(1024)]
    chunk_id = _insert_chunk(db_conn, embedding=vec)
    stored = db_conn.execute(
        "SELECT embedding FROM chunks WHERE chunk_id = %s", (chunk_id,)
    ).fetchone()[0]
    # pgvector stores 32-bit floats, so compare with a small tolerance.
    assert len(stored.to_list()) == 1024
    assert all(abs(a - b) < 1e-6 for a, b in zip(stored.to_list(), vec, strict=True))


@pytest.mark.db
def test_wrong_size_vector_is_rejected(db_conn):
    insert_document(db_conn)
    with pytest.raises(psycopg.errors.DataException):
        _insert_chunk(db_conn, embedding=[0.0] * 1023)


@pytest.mark.db
def test_deleting_document_deletes_its_chunks(db_conn):
    insert_document(db_conn)
    _insert_chunk(db_conn, index=0)
    _insert_chunk(db_conn, index=1)
    db_conn.execute("DELETE FROM documents WHERE doc_id = %s", ("gst-231-25-2024",))
    count = db_conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    assert count == 0


@pytest.mark.db
def test_check_constraints_reject_bad_values(db_conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_document(db_conn, doc_id="sebi-1", corpus="sebi")  # only rbi / gst


@pytest.mark.db
def test_duplicate_chunk_index_is_rejected(db_conn):
    insert_document(db_conn)
    _insert_chunk(db_conn, index=0)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_chunk(db_conn, index=0)
