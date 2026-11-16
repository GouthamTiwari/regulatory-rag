"""Reranker with a fake Bedrock client (unit) and one real call (live)."""

import io
import json

import pytest

from regrag.bedrock.reranker import BedrockReranker, NoopReranker, document_text
from regrag.interfaces import Reranker
from tests.fakes import make_chunk


class FakeRerank:
    """Scores each document by how many query words it contains."""

    def __init__(self):
        self.calls: list[dict] = []

    def invoke_model(self, modelId, body, **kwargs):
        request = json.loads(body)
        self.calls.append({"modelId": modelId, **request})
        words = set(request["query"].lower().split())
        results = [
            {"index": i, "relevance_score": len(words & set(doc.lower().split())) / 10}
            for i, doc in enumerate(request["documents"])
        ]
        results.sort(key=lambda r: -r["relevance_score"])
        return {"body": io.BytesIO(json.dumps({"results": results}).encode())}


def chunks_with(*texts):
    return [make_chunk(i + 1, content=t, title="", section_path="") for i, t in enumerate(texts)]


def test_scores_map_back_to_the_right_chunks():
    chunks = chunks_with("nothing here", "demo vehicles itc", "itc only")
    reranker = BedrockReranker(FakeRerank(), sleep=lambda s: None)
    ranked = reranker.rerank("itc demo vehicles", chunks, top_n=3)
    assert [c.chunk_id for c in ranked] == [2, 3, 1]
    assert ranked[0].rerank_score == pytest.approx(0.3)
    assert chunks[1].rerank_score is None  # inputs untouched


def test_top_n_is_respected():
    chunks = chunks_with("a", "b", "c", "d")
    assert len(BedrockReranker(FakeRerank()).rerank("a", chunks, top_n=2)) == 2


def test_more_than_100_chunks_is_split_and_billed_as_2_queries():
    fake = FakeRerank()
    reranker = BedrockReranker(fake)
    reranker.rerank("q", chunks_with(*[f"doc {i}" for i in range(150)]), top_n=8)
    assert [len(c["documents"]) for c in fake.calls] == [100, 50]
    assert reranker.last_queries == 2 and reranker.total_queries == 2


def test_empty_input_makes_no_call():
    fake = FakeRerank()
    assert BedrockReranker(fake).rerank("q", [], top_n=8) == [] and fake.calls == []


def test_both_adapters_build_the_right_body():
    for model_id, extra in (
        ("amazon.rerank-v1:0", {}),
        ("cohere.rerank-v3-5:0", {"api_version": 2}),
    ):
        fake = FakeRerank()
        BedrockReranker(fake, model_id=model_id).rerank("q", chunks_with("x"), top_n=1)
        call = fake.calls[0]
        assert call["modelId"] == model_id and call["top_n"] == 1
        assert {k: call[k] for k in extra} == extra


def test_unknown_model_is_rejected():
    with pytest.raises(ValueError, match="no rerank adapter"):
        BedrockReranker(FakeRerank(), model_id="some.reranker-v9")


def test_document_text_includes_title_and_path():
    chunk = make_chunk(1, title="KYC Directions", section_path="Chapter VI", content="Body.")
    assert document_text(chunk) == "KYC Directions\nChapter VI\n\nBody."


def test_noop_reranker_keeps_order_and_cuts():
    chunks = chunks_with("a", "b", "c")
    assert [c.chunk_id for c in NoopReranker().rerank("q", chunks, top_n=2)] == [1, 2]


def test_both_satisfy_the_reranker_protocol():
    assert isinstance(BedrockReranker(FakeRerank()), Reranker)
    assert isinstance(NoopReranker(), Reranker)


@pytest.mark.live
def test_live_relevant_passage_ranks_first():
    from regrag.bedrock.client import BedrockAuthError, auth_mode, get_runtime_client
    from regrag.config import get_settings

    settings = get_settings()
    try:
        auth_mode(settings)
    except BedrockAuthError as exc:
        pytest.skip(str(exc))
    client = get_runtime_client(settings, region=settings.bedrock_rerank_region)
    reranker = BedrockReranker(client, model_id=settings.bedrock_rerank_model_id)
    chunks = chunks_with(
        "The KYC directions list officially valid documents such as a passport.",
        "Input tax credit on demo vehicles is not blocked when used for further supply.",
        "The repo rate is set by the monetary policy committee.",
    )
    ranked = reranker.rerank("Can a car dealer claim ITC on demo vehicles?", chunks, top_n=3)
    assert ranked[0].chunk_id == 2
    print(f"\nscores={[round(c.rerank_score, 4) for c in ranked]} queries={reranker.last_queries}")


def test_reranker_is_paced_per_minute():
    waits: list[float] = []
    reranker = BedrockReranker(FakeRerank(), requests_per_minute=2.0, sleep=waits.append)
    reranker.rerank("q", chunks_with("a"), top_n=1)
    reranker.rerank("q", chunks_with("a"), top_n=1)
    assert len(waits) == 1 and 29.0 < waits[0] <= 30.0  # the 2nd call waits ~30 s
