"""Shared types round-trip through JSON, and the fakes satisfy every Protocol."""

import json

import pytest

from regrag import interfaces
from regrag.types import ChunkRef, Citation, PipelineConfig, QueryResult, Usage
from tests import fakes


def _sample_result() -> QueryResult:
    return QueryResult(
        query_id="0b6c2c1e-7f0a-4a52-9a54-2f4b8f0d9a11",
        question="Can a car dealer claim ITC on demo vehicles?",
        route="gst",
        config_name="hybrid_rerank",
        answer="Yes, if the vehicle is used in the course of business. [C1]",
        citations=[
            Citation(
                marker="C1",
                doc_id="gst-231-25-2024",
                title="Circular 231/25/2024-GST",
                section_no="Para 3",
                page_start=2,
                page_end=2,
                source_url="https://gstcouncil.gov.in/example.pdf",
            )
        ],
        supersession_notes=["Example note."],
        retrieved=[ChunkRef(chunk_id=7, doc_id="gst-231-25-2024", section_no="Para 3")],
        reranked=[ChunkRef(chunk_id=7, doc_id="gst-231-25-2024", section_no="Para 3")],
        rerank_top_score=0.91,
        usage=Usage(input_tokens=1200, output_tokens=180, embed_tokens=12, rerank_queries=1),
        cost_usd=0.00225,
        latency_ms={"retrieve": 41.5, "generate": 950.0},
        model_ids={"llm": "global.amazon.nova-2-lite-v1:0"},
    )


def test_query_result_round_trips_through_json():
    r = _sample_result()
    # Through real JSON text, which proves to_dict() is JSON-safe (a cache will store this).
    restored = QueryResult.from_dict(json.loads(json.dumps(r.to_dict())))
    assert restored == r


def test_query_result_from_dict_ignores_unknown_fields():
    data = _sample_result().to_dict()
    data["field_added_by_a_future_version"] = 123
    assert QueryResult.from_dict(data) == _sample_result()


def test_usage_adds_up():
    total = Usage(input_tokens=10, output_tokens=2) + Usage(embed_tokens=5, rerank_queries=1)
    assert total == Usage(input_tokens=10, output_tokens=2, embed_tokens=5, rerank_queries=1)


@pytest.mark.parametrize(
    ("name", "keyword", "vector", "rerank"),
    [
        ("bm25", True, False, False),
        ("vector", False, True, False),
        ("hybrid", True, True, False),
        ("hybrid_rerank", True, True, True),
    ],
)
def test_pipeline_config_flags(name, keyword, vector, rerank):
    c = PipelineConfig(name=name)
    assert (c.uses_keyword, c.uses_vector, c.uses_rerank) == (keyword, vector, rerank)


def test_pipeline_config_rejects_unknown_name():
    with pytest.raises(ValueError):
        PipelineConfig(name="bm42")


@pytest.mark.parametrize(
    ("fake", "protocol"),
    [
        (fakes.FakeEmbedder(dimensions=4), interfaces.Embedder),
        (fakes.FakeRetriever(), interfaces.Retriever),
        (fakes.FakeReranker(), interfaces.Reranker),
        (fakes.FakeRouter(), interfaces.Router),
        (fakes.FakeGenerator(), interfaces.Generator),
        (fakes.FakeValidator(), interfaces.Validator),
    ],
)
def test_fakes_satisfy_protocols(fake, protocol):
    assert isinstance(fake, protocol)


def test_fake_embedder_is_deterministic_and_unit_length():
    e = fakes.FakeEmbedder(dimensions=16)
    a, b = e.embed(["same text", "same text"]).vectors
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9


def test_fake_retriever_filters_by_route_and_top_k():
    chunks = [fakes.make_chunk(1, corpus="rbi"), fakes.make_chunk(2), fakes.make_chunk(3)]
    r = fakes.FakeRetriever(chunks)
    assert [c.chunk_id for c in r.retrieve("q", "gst", top_k=1)] == [2]
    assert len(r.retrieve("q", "both", top_k=10)) == 3


def test_fake_reranker_orders_by_score():
    chunks = [fakes.make_chunk(1), fakes.make_chunk(2)]
    ranked = fakes.FakeReranker(scores={1: 0.2, 2: 0.8}).rerank("q", chunks, top_n=2)
    assert [c.chunk_id for c in ranked] == [2, 1]
