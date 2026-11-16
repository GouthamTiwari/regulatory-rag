"""Keyword retriever against the Docker Postgres (marked db)."""

from datetime import date

import pytest

from regrag.db import repository as repo
from regrag.interfaces import Retriever
from regrag.retrieval.keyword import KeywordRetriever, any_word_query
from regrag.types import Chunk, ManifestRow

pytestmark = pytest.mark.db

TEXTS = {
    "gst-231-25-2024": [
        "Circular No. 231/25/2024-GST clarifies input tax credit on demo vehicles.",
        "Demo vehicles are used by dealers to promote the sale of motor vehicles.",
        "Credit is not blocked under section 17(5) when used for further supply.",
    ],
    "rbi-13141": [
        "Officially valid documents for KYC include the passport and driving licence.",
        "Banks shall carry out customer due diligence before opening an account.",
    ],
}


def store(conn):
    for doc_id, texts in TEXTS.items():
        corpus = doc_id.split("-")[0]
        row = ManifestRow(
            doc_id=doc_id, corpus=corpus, doc_type="x", title=f"T {doc_id}", reference_no="",
            applies_to="", publish_date=date(2024, 1, 1), source_url="https://www.rbi.org.in/x",
            pdf_url="https://www.rbi.org.in/x.pdf",
        )  # fmt: skip
        chunks = [
            Chunk(doc_id, i, f"Para {i + 1}", "", 1, 1, "text", t, len(t) // 4)
            for i, t in enumerate(texts)
        ]
        repo.upsert_document(conn, row, chunks, page_count=1, embedding_model="none")


@pytest.fixture
def kw(db_conn):
    store(db_conn)
    return KeywordRetriever(db_conn)


def test_exact_circular_number_ranks_first(kw):
    results = kw.retrieve("231/25/2024-GST", "both", top_k=5)
    assert results[0].content.startswith("Circular No. 231/25/2024-GST")
    assert results[0].keyword_rank == 1 and results[0].keyword_score > 0


def test_route_gst_never_returns_rbi(kw):
    results = kw.retrieve("documents banks credit vehicles", "gst", top_k=10)
    assert results and all(c.corpus == "gst" for c in results)


def test_no_matching_terms_returns_empty_list(kw):
    assert kw.retrieve("cryptocurrency mining", "both", top_k=5) == []
    assert kw.retrieve("   ", "both", top_k=5) == []


@pytest.mark.parametrize(
    "odd", ['"demo" vehicles!!', "ITC: demo -- vehicles?", "it's (demo) & 'vehicles'"]
)
def test_punctuation_and_quotes_do_not_raise(kw, odd):
    assert isinstance(kw.retrieve(odd, "both", top_k=5), list)


def test_natural_question_falls_back_to_any_word_matching(kw):
    # No chunk contains every word, so the strict search alone would find nothing.
    results = kw.retrieve("Can a dealer claim credit on demo cars?", "gst", top_k=5)
    assert results and "demo vehicles" in results[0].content.lower()


def test_any_word_query():
    assert any_word_query("ITC on demo vehicles?") == "ITC or on or demo or vehicles"


def test_satisfies_the_retriever_protocol(db_conn):
    assert isinstance(KeywordRetriever(db_conn), Retriever)
