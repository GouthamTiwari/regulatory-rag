"""Repository tests against the Docker Postgres (marked db)."""

import uuid
from datetime import date

import psycopg
import pytest

from regrag.db import repository as repo
from regrag.types import Chunk, ChunkRef, Citation, ManifestRow, QueryResult, Relation, Usage

pytestmark = pytest.mark.db


def manifest_row(doc_id="gst-231-25-2024", ref="231/25/2024-GST", **overrides) -> ManifestRow:
    values = dict(
        doc_id=doc_id,
        corpus="gst",
        doc_type="circular",
        title=f"Test {doc_id}",
        reference_no=ref,
        applies_to="",
        publish_date=date(2024, 9, 11),
        source_url="https://gstcouncil.gov.in/cgst-circulars",
        pdf_url="https://gstcouncil.gov.in/x.pdf",
        sha256="a" * 64,
    )
    values.update(overrides)
    return ManifestRow(**values)


def vector(seed: float) -> list[float]:
    return [seed] + [0.0] * 1022 + [1.0]


def chunks_for(doc_id: str, n: int, seed: float = 0.1, text="content") -> list[Chunk]:
    return [
        Chunk(
            doc_id=doc_id,
            chunk_index=i,
            section_no=f"Para {i + 1}",
            section_path="",
            page_start=1,
            page_end=1,
            content_type="text",
            content=f"{text} {i}",
            token_count=3,
            embedding=vector(seed + i),
        )
        for i in range(n)
    ]


def save(conn, row, chunks):
    repo.upsert_document(conn, row, chunks, page_count=4, embedding_model="titan-v2")


def contents(conn, doc_id):
    rows = conn.execute(
        "SELECT content FROM chunks WHERE doc_id = %s ORDER BY chunk_index", (doc_id,)
    ).fetchall()
    return [r[0] for r in rows]


def test_reupsert_leaves_exactly_the_new_chunks(db_conn):
    save(db_conn, manifest_row(), chunks_for("gst-231-25-2024", 3, text="old"))
    save(db_conn, manifest_row(), chunks_for("gst-231-25-2024", 2, text="new"))
    assert contents(db_conn, "gst-231-25-2024") == ["new 0", "new 1"]
    assert repo.document_state(db_conn, "gst-231-25-2024") == ("a" * 64, "titan-v2")


def test_failure_midway_keeps_the_old_chunks(db_conn):
    save(db_conn, manifest_row(), chunks_for("gst-231-25-2024", 2, text="old"))
    broken = chunks_for("gst-231-25-2024", 2, text="new")
    broken[1].embedding = [0.0] * 5  # wrong size: the database rejects this row
    with pytest.raises(psycopg.errors.DataException):
        save(db_conn, manifest_row(), broken)
    assert contents(db_conn, "gst-231-25-2024") == ["old 0", "old 1"]


def test_relations_both_directions_and_ref_resolution(db_conn):
    save(
        db_conn,
        manifest_row("gst-195-07-2023", "195/07/2023-GST"),
        chunks_for("gst-195-07-2023", 1),
    )
    save(
        db_conn,
        manifest_row("gst-216-10-2024", "216/10/2024-GST"),
        chunks_for("gst-216-10-2024", 1),
    )
    rel = Relation(
        from_doc_id="gst-216-10-2024",
        relation="clarifies",
        to_doc_ref="Circular No. 195/07/2023 - GST",  # a messy spelling of our own document
        evidence="in furtherance to Circular No. 195/07/2023-GST",
    )
    repo.replace_relations(db_conn, "gst-216-10-2024", [rel])
    for doc_id in ("gst-195-07-2023", "gst-216-10-2024"):  # target side and source side
        (found,) = repo.get_relations_for(db_conn, [doc_id])
        assert found.to_doc_id == "gst-195-07-2023"


def test_replace_relations_does_not_touch_manual_ones(db_conn):
    save(
        db_conn,
        manifest_row("gst-216-10-2024", "216/10/2024-GST"),
        chunks_for("gst-216-10-2024", 1),
    )
    manual = Relation(
        "gst-216-10-2024",
        "clarifies",
        "195/07/2023-GST",
        evidence="m",
        source="manual",
        reviewed=True,
    )
    repo.load_manual_relations(db_conn, [manual])
    repo.replace_relations(db_conn, "gst-216-10-2024", [])
    assert [r.source for r in repo.get_relations_for(db_conn, ["gst-216-10-2024"])] == ["manual"]


def test_get_chunks_keeps_requested_order(db_conn):
    save(db_conn, manifest_row(), chunks_for("gst-231-25-2024", 3))
    ids = [
        r[0] for r in db_conn.execute("SELECT chunk_id FROM chunks ORDER BY chunk_index").fetchall()
    ]
    got = repo.get_chunks(db_conn, [ids[2], ids[0]])
    assert [c.chunk_id for c in got] == [ids[2], ids[0]]
    assert got[0].title == "Test gst-231-25-2024" and got[0].corpus == "gst"


def test_top_chunk_for_document_is_the_nearest(db_conn):
    save(db_conn, manifest_row(), chunks_for("gst-231-25-2024", 3, seed=0.0))
    best = repo.top_chunk_for_document(db_conn, "gst-231-25-2024", vector(2.0))
    assert best.content == "content 2"
    assert repo.top_chunk_for_document(db_conn, "gst-999-1-2025", vector(1.0)) is None


def test_query_log_round_trips(db_conn):
    result = QueryResult(
        query_id=str(uuid.uuid4()),
        question="Can a dealer claim ITC on demo vehicles?",
        route="gst",
        config_name="hybrid_rerank",
        answer="Yes [C1].",
        citations=[Citation("C1", "gst-231-25-2024", "T", "Para 4", 2, 2, "https://x")],
        retrieved=[
            ChunkRef(11, "gst-231-25-2024", "Para 4"),
            ChunkRef(12, "gst-231-25-2024", "Para 5"),
        ],
        reranked=[ChunkRef(11, "gst-231-25-2024", "Para 4")],
        rerank_top_score=0.42,
        usage=Usage(input_tokens=900, output_tokens=60, embed_tokens=9, rerank_queries=1),
        cost_usd=0.0012,
        latency_ms={"retrieve": 40.0},
        model_ids={"llm": "global.amazon.nova-2-lite-v1:0"},
    )
    repo.insert_query_log(db_conn, result)
    row = db_conn.execute(
        "SELECT retrieved_chunk_ids, reranked_chunk_ids, citations, latency_ms, cost_usd, "
        "rerank_queries FROM query_logs WHERE query_id = %s",
        (result.query_id,),
    ).fetchone()
    assert row[0] == [11, 12] and row[1] == [11]
    assert row[2][0]["doc_id"] == "gst-231-25-2024"
    assert row[3] == {"retrieve": 40.0}
    assert float(row[4]) == pytest.approx(0.0012) and row[5] == 1


def test_chunks_like_finds_the_same_rule_in_another_document(db_conn):
    save(db_conn, manifest_row("rbi-11959", "RBI/OLD/1"), chunks_for("rbi-11959", 1, seed=5.0))
    save(db_conn, manifest_row("rbi-12799", "RBI/NEW/1"), chunks_for("rbi-12799", 4, seed=2.0))
    old_id = db_conn.execute("SELECT chunk_id FROM chunks WHERE doc_id = 'rbi-11959'").fetchone()[0]
    like = repo.chunks_like(db_conn, "rbi-12799", old_id, limit=2)
    # Vectors are [seed+i, 0, ..., 1]; the old one is [5, ..., 1], so the closest new
    # chunks are i=3 (seed 5) and i=2 (seed 4).
    assert [c.content for c in like] == ["content 3", "content 2"]
