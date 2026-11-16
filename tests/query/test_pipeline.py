"""answer_question with fake parts: order of stages, cost, citations, retry, abstention."""

import json

import pytest

from regrag.config import Settings
from regrag.query import pipeline
from regrag.query.pipeline import Parts, answer_question, build_pipeline
from regrag.query.validate import CitationValidator
from regrag.types import DraftAnswer, PipelineConfig, Usage
from tests.fakes import FakeReranker, FakeRetriever, FakeRouter, FakeValidator, make_chunk

SETTINGS = Settings()
MODEL_IDS = {
    "llm": "global.amazon.nova-2-lite-v1:0",
    "embed": "amazon.titan-embed-text-v2:0",
    "rerank": "amazon.rerank-v1:0",
}


class ScriptedGenerator:
    """Returns the given drafts in order and records the stage order."""

    def __init__(self, *drafts, log=None):
        self.drafts = list(drafts)
        self.log = log

    def generate(self, question, chunks):
        if self.log is not None:
            self.log.append("generate")
        return self.drafts.pop(0)


class Logged:
    """Wrap a fake part so the order of calls is recorded."""

    def __init__(self, inner, name, log):
        self.inner, self.name, self.log = inner, name, log

    def __getattr__(self, attr):
        target = getattr(self.inner, attr)
        if callable(target):

            def call(*args, **kwargs):
                self.log.append(self.name)
                return target(*args, **kwargs)

            return call
        return target


def parts(generator, *, retry=None, validators=None, log=None, chunks=None):
    log = log if log is not None else []
    chunks = chunks or [
        make_chunk(
            1,
            doc_id="gst-231-25-2024",
            title="Circular 231",
            section_no="Para 4",
            page_start=2,
            page_end=2,
            source_url="https://gstcouncil.gov.in/x.pdf",
        ),
        make_chunk(2),
    ]
    return Parts(
        settings=SETTINGS,
        router=Logged(FakeRouter("gst"), "route", log),
        retriever=Logged(FakeRetriever(chunks), "retrieve", log),
        reranker=Logged(FakeReranker(scores={1: 0.9, 2: 0.5}), "rerank", log),
        generator=generator,
        retry_generator=retry or ScriptedGenerator(),
        validators=validators if validators is not None else [CitationValidator()],
        model_ids=MODEL_IDS,
    )


GOOD = DraftAnswer(
    text="Input tax credit is available on demo vehicles [C1].",
    markers=["C1"],
    usage=Usage(input_tokens=1000, output_tokens=50),
)


def test_stages_run_in_order_with_cost_latency_and_citations():
    log: list[str] = []
    result = answer_question(
        "ITC on demo vehicles?", parts=parts(ScriptedGenerator(GOOD, log=log), log=log), log=False
    )
    assert log == ["route", "retrieve", "rerank", "generate"]
    assert not result.abstained and result.route == "gst"
    (citation,) = result.citations
    assert (citation.doc_id, citation.section_no, citation.page_start) == (
        "gst-231-25-2024",
        "Para 4",
        2,
    )
    assert result.rerank_top_score == pytest.approx(0.9)
    assert set(result.latency_ms) >= {"route", "retrieve", "rerank", "generate", "total"}
    assert result.cost_usd == pytest.approx(1000 * 0.35 / 1e6 + 50 * 2.95 / 1e6)
    assert [c.chunk_id for c in result.reranked] == [1, 2]


def test_failed_validation_regenerates_once_then_abstains():
    bad = DraftAnswer(text="Credit is available on demo vehicles [C9].", markers=["C9"])
    retry = ScriptedGenerator(bad)
    result = answer_question("q", parts=parts(ScriptedGenerator(bad), retry=retry), log=False)
    assert retry.drafts == []  # the retry generator was used exactly once
    assert result.abstained and result.abstain_reason == "unknown_marker"
    assert result.citations == [] and "You may want to read" in result.answer


def test_a_successful_retry_is_used():
    bad = DraftAnswer(text="Credit is available on demo vehicles.")  # no citation
    result = answer_question(
        "q", parts=parts(ScriptedGenerator(bad), retry=ScriptedGenerator(GOOD)), log=False
    )
    assert not result.abstained and result.citations[0].marker == "C1"


def test_weak_rerank_score_abstains():
    p = parts(ScriptedGenerator(GOOD))
    p.reranker.inner.scores = {1: 0.001, 2: 0.0}  # well below the 0.01 threshold
    result = answer_question("q", parts=p, log=False)
    assert result.abstained and result.abstain_reason == "weak_evidence"


def test_extra_validator_can_force_abstention():
    p = parts(
        ScriptedGenerator(GOOD),
        validators=[CitationValidator(), FakeValidator(passed=False, reason="guardrail")],
    )
    p.retry_generator = ScriptedGenerator(GOOD)
    result = answer_question("q", parts=p, log=False)
    assert result.abstained and result.abstain_reason == "guardrail"


def test_prints_nothing_and_result_is_json_serialisable(capsys):
    result = answer_question("q", parts=parts(ScriptedGenerator(GOOD)), log=False)
    assert capsys.readouterr().out == ""
    json.dumps(result.to_dict())


@pytest.mark.parametrize("name", ["bm25", "vector", "hybrid", "hybrid_rerank"])
def test_each_configuration_builds(monkeypatch, name):
    import regrag.bedrock.client as client_module

    monkeypatch.setattr(client_module, "get_runtime_client", lambda s, region=None: object())
    built = build_pipeline(PipelineConfig(name=name), SETTINGS, conn=object())
    kinds = {
        "bm25": "KeywordRetriever",
        "vector": "VectorRetriever",
        "hybrid": "HybridRetriever",
        "hybrid_rerank": "HybridRetriever",
    }
    assert type(built.retriever).__name__ == kinds[name]
    expected_reranker = "BedrockReranker" if name == "hybrid_rerank" else "NoopReranker"
    assert type(built.reranker).__name__ == expected_reranker
    assert ("rerank" in built.model_ids) is (name == "hybrid_rerank")
    assert pipeline.DISCLAIMER  # the CLI prints it
