"""HybridRetriever wiring, using fake retrievers only (no database)."""

from regrag.interfaces import Retriever
from regrag.retrieval.hybrid import HybridRetriever
from tests.fakes import FakeRetriever, make_chunk


def test_hybrid_calls_both_retrievers_and_fuses():
    keyword = FakeRetriever([make_chunk(1), make_chunk(2)])
    vector = FakeRetriever([make_chunk(2), make_chunk(3)])
    hybrid = HybridRetriever(keyword, vector, keyword_top_k=30, vector_top_k=25)
    result = hybrid.retrieve("ITC on demo vehicles", "gst", top_k=10)
    assert [c.chunk_id for c in result] == [2, 1, 3]  # 2 is in both lists
    assert keyword.calls == [("ITC on demo vehicles", "gst", 30)]
    assert vector.calls == [("ITC on demo vehicles", "gst", 25)]


def test_hybrid_respects_route_and_top_k():
    chunks = [make_chunk(i, corpus="rbi" if i % 2 else "gst") for i in range(1, 9)]
    hybrid = HybridRetriever(FakeRetriever(chunks), FakeRetriever(chunks))
    result = hybrid.retrieve("q", "rbi", top_k=3)
    assert len(result) == 3 and all(c.corpus == "rbi" for c in result)


def test_hybrid_satisfies_the_retriever_protocol():
    assert isinstance(HybridRetriever(FakeRetriever(), FakeRetriever()), Retriever)
