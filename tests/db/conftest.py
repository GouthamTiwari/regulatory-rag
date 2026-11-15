"""Database fixtures for tests marked `db` (they need: docker compose up -d).

Each test session gets its own throw-away Postgres schema, created at the start and
dropped at the end. Why: several test runs (or branches) may share one container at the
same time, and none of them may touch the real tables or each other's data.
"""

import uuid

import psycopg
import pytest
from psycopg import sql

from regrag.db.connection import connect
from regrag.db.init import apply_schema


@pytest.fixture(scope="session")
def db_schema():
    name = f"test_{uuid.uuid4().hex[:12]}"
    try:
        admin = connect(register_vector_type=False, autocommit=True)
    except RuntimeError as exc:
        pytest.fail(f"{exc} (db tests need the Docker Postgres)")
    # The extension must exist in "public" before the throw-away schema is used.
    admin.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    try:
        with connect(schema=name, register_vector_type=False) as conn:
            apply_schema(conn)
            conn.commit()
        yield name
    finally:
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))
        admin.close()


@pytest.fixture
def db_conn(db_schema) -> psycopg.Connection:
    """A connection inside the test schema. Everything a test does is rolled back after it."""
    conn = connect(schema=db_schema)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def insert_document(conn: psycopg.Connection, doc_id: str = "gst-231-25-2024", **overrides):
    """Insert one minimal valid document row (test helper)."""
    values = {
        "doc_id": doc_id,
        "corpus": "gst",
        "title": "Test circular",
        "publish_date": "2024-09-11",
        "source_url": "https://gstcouncil.gov.in/cgst-circulars",
        "pdf_url": "https://gstcouncil.gov.in/test.pdf",
    }
    values.update(overrides)
    columns = sql.SQL(", ").join(sql.Identifier(k) for k in values)
    placeholders = sql.SQL(", ").join(sql.Placeholder() * len(values))
    conn.execute(
        sql.SQL("INSERT INTO documents ({}) VALUES ({})").format(columns, placeholders),
        list(values.values()),
    )
