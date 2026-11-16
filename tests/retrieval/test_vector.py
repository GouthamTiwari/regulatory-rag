"""Vector retriever against the Docker Postgres, with hand-made vectors (marked db)."""

import math
from datetime import date

import pytest

from regrag.db import repository as repo
from regrag.retrieval.vector import VectorRetriever
from regrag.types import Chunk, EmbedResult, ManifestRow

pytestmark = pytest.mark.db


def unit(angle: float) -> list[float]:
    """A 1024-dim unit vector pointing at `angle` in the first two dimensions."""
    return [math.cos(angle), math.sin(angle)] + [0.0] * 1022


class FixedEmbedder:
    def __init__(self, vector):
        self.vector = vector
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return EmbedResult(vectors=[self.vector for _ in texts], input_tokens=7)


def store(conn, doc_id: str, angles: list[float]):
    corpus = doc_id.split("-")[0]
    row = ManifestRow(
        doc_id=doc_id, corpus=corpus, doc_type="x", title=f"T {doc_id}", reference_no="",
        applies_to="", publish_date=date(2024, 1, 1), source_url="https://www.rbi.org.in/x",
        pdf_url="https://www.rbi.org.in/x.pdf",
    )  # fmt: skip
    chunks = [
        Chunk(doc_id, i, f"Para {i}", "", 1, 1, "text", f"{doc_id} angle {a:.2f}", 3, unit(a))
        for i, a in enumerate(angles)
    ]
    repo.upsert_document(conn, row, chunks, page_count=1, embedding_model="test")


def test_nearest_vector_is_rank_one_and_scores_make_sense(db_conn):
    store(db_conn, "gst-1-1-2025", [0.0, 0.5, 1.0])
    embedder = FixedEmbedder(unit(0.48))
    results = VectorRetriever(db_conn, embedder).retrieve("q", "both", top_k=3)
    assert results[0].content == "gst-1-1-2025 angle 0.50"
    assert results[0].vector_rank == 1
    assert results[0].vector_score == pytest.approx(math.cos(0.02), abs=1e-4)
    assert results[0].vector_score > results[1].vector_score


def test_route_filter_still_fills_top_k(db_conn):
    # 30 RBI chunks sit closer to the question than any GST chunk; with route "gst" the
    # filter removes all of them, yet top_k GST chunks must still come back.
    store(db_conn, "rbi-1", [0.001 * i for i in range(30)])
    store(db_conn, "gst-1-1-2025", [1.0 + 0.01 * i for i in range(6)])
    results = VectorRetriever(db_conn, FixedEmbedder(unit(0.0))).retrieve("q", "gst", top_k=5)
    assert len(results) == 5 and all(c.corpus == "gst" for c in results)


def test_embedder_called_once_and_tokens_recorded(db_conn):
    store(db_conn, "gst-1-1-2025", [0.0])
    embedder = FixedEmbedder(unit(0.0))
    retriever = VectorRetriever(db_conn, embedder)
    retriever.retrieve("q", "both", top_k=5)
    assert embedder.calls == 1 and retriever.last_embed_tokens == 7


def test_empty_question_makes_no_call(db_conn):
    embedder = FixedEmbedder(unit(0.0))
    assert VectorRetriever(db_conn, embedder).retrieve("  ", "both", top_k=5) == []
    assert embedder.calls == 0
