"""Evaluation runner with fake pipelines: table shape, errors, retrieval-only, report."""

import json

from regrag.bedrock.reranker import NoopReranker
from regrag.config import Settings
from regrag.eval.golden import GoldenItem
from regrag.eval.run import LABELS, estimate_cost, run_eval, summarize, write_report
from regrag.query.pipeline import Parts
from regrag.query.validate import CitationValidator
from regrag.types import DraftAnswer, Usage
from tests.fakes import FakeReranker, FakeRetriever, FakeRouter, make_chunk

SETTINGS = Settings()
CONFIGS = ["bm25", "vector", "hybrid", "hybrid_rerank"]


def item(i: int, doc="gst-231-25-2024", abstain=False) -> GoldenItem:
    return GoldenItem(
        id=f"g{i:03d}", question=f"Question {i} about ITC?", corpus="gst",
        type="abstain" if abstain else "factual",
        expected_doc_ids=[] if abstain else [doc], expected_sections=[],
        reference_answer="", should_abstain=abstain, must_flag_supersession=False,
        tags=[], source="manual", reviewed=True,
    )  # fmt: skip


class CountingGenerator:
    def __init__(self):
        self.calls = 0

    def generate(self, question, chunks):
        self.calls += 1
        return DraftAnswer(
            text="Input tax credit is available on demo vehicles [C1].",
            markers=["C1"],
            usage=Usage(input_tokens=100, output_tokens=10),
        )


class ExplodingRetriever(FakeRetriever):
    def retrieve(self, query, route, top_k):
        if "Question 2" in query:
            raise RuntimeError("database went away")
        return super().retrieve(query, route, top_k)


def make_parts(name: str, generator: CountingGenerator, reranker_log: list) -> Parts:
    chunks = [make_chunk(1, doc_id="gst-231-25-2024"), make_chunk(2, doc_id="gst-232-26-2024")]
    if name == "hybrid_rerank":
        reranker = FakeReranker(scores={1: 0.9, 2: 0.5})
        reranker_log.append(reranker)
    else:
        reranker = NoopReranker()
    return Parts(
        settings=SETTINGS, router=FakeRouter("gst"), retriever=ExplodingRetriever(chunks),
        reranker=reranker, generator=generator, retry_generator=generator,
        validators=[CitationValidator()],
        model_ids={"llm": SETTINGS.bedrock_llm_model_id, "embed": SETTINGS.bedrock_embed_model_id},
    )  # fmt: skip


class FakeJudge:
    model_id = SETTINGS.bedrock_judge_model_id

    def complete(self, system, user, max_tokens=1500):
        return '[{"n": 1, "label": "supported", "reason": "ok"}]', Usage(
            input_tokens=50, output_tokens=5
        )


def test_four_configs_three_questions_give_a_four_row_table(tmp_path):
    generator, rerankers = CountingGenerator(), []
    rows = run_eval(
        [item(1), item(2), item(3)], CONFIGS, lambda n: make_parts(n, generator, rerankers),
        judge_llm=FakeJudge(), fetch_chunks=lambda ids: [make_chunk(i) for i in ids],
    )  # fmt: skip
    assert len(rows) == 12
    errors = [r for r in rows if r.status == "error"]
    assert len(errors) == 4 and all(r.id == "g002" for r in errors)  # recorded, run continued
    ok = [r for r in rows if r.status == "ok"]
    assert all(r.recall_at_5 == 1 and r.faithfulness == 1.0 for r in ok)
    md, js = write_report(tmp_path, rows, meta(retrieval_only=False))
    table = [line for line in md.read_text(encoding="utf-8").splitlines() if line.startswith("| ")]
    assert len(table) == 1 + 4  # header + one row per configuration
    assert table[0].count("|") == 15  # 14 metric columns
    assert json.loads(js.read_text(encoding="utf-8"))["summary"]["hybrid"]["errors"] == 1


def test_retrieval_only_makes_no_llm_and_no_rerank_calls_without_a_reranker():
    generator, rerankers = CountingGenerator(), []
    rows = run_eval(
        [item(1), item(3)], ["bm25", "vector", "hybrid"],
        lambda n: make_parts(n, generator, rerankers), retrieval_only=True,
    )  # fmt: skip
    assert generator.calls == 0 and rerankers == []
    assert all(r.recall_at_10 == 1 and r.faithfulness is None for r in rows)


def test_report_header_names_date_size_models_region_and_prices(tmp_path):
    rows = run_eval(
        [item(1)], ["hybrid"], lambda n: make_parts(n, CountingGenerator(), []), retrieval_only=True
    )
    text = write_report(tmp_path, rows, meta(retrieval_only=True, sample=True))[0].read_text(
        encoding="utf-8"
    )
    for expected in (
        "2026-11-16",
        "Golden questions: 1",
        SETTINGS.bedrock_llm_model_id,
        SETTINGS.bedrock_judge_model_id,
        "ap-south-1",
        "Prices checked on: 2026-11-16",
        "Sample, not final",
    ):
        assert expected in text


def test_bm25_never_appears_alone_as_a_row_label(tmp_path):
    rows = run_eval(
        [item(1)], ["bm25"], lambda n: make_parts(n, CountingGenerator(), []), retrieval_only=True
    )
    text = write_report(tmp_path, rows, meta(retrieval_only=True))[0].read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| keyword"))
    assert row.startswith(f"| {LABELS['bm25']} |") and "| BM25 |" not in text


def test_abstain_question_counts_in_abstention_not_retrieval():
    generator = CountingGenerator()
    rows = run_eval([item(9, abstain=True)], ["hybrid"], lambda n: make_parts(n, generator, []))
    summary = summarize(rows)
    assert summary["recall_at_5"] is None  # answerable questions only
    assert summary["abstain_accuracy"] == 0.0  # the fake answered when it should have abstained


def test_cost_estimate_uses_the_judge_price():
    lite = estimate_cost(10, ["hybrid"], SETTINGS, retrieval_only=False)
    pro = estimate_cost(
        10,
        ["hybrid"],
        Settings(bedrock_judge_model_id="apac.amazon.nova-pro-v1:0"),
        retrieval_only=False,
    )
    assert pro > lite > estimate_cost(10, ["hybrid"], SETTINGS, retrieval_only=True)


def meta(retrieval_only: bool, sample: bool = False) -> dict:
    return {
        "date": "2026-11-16", "questions": 1, "reviewed": 1, "retrieval_only": retrieval_only,
        "sample": sample, "sample_note": "test", "llm": SETTINGS.bedrock_llm_model_id,
        "judge": SETTINGS.bedrock_judge_model_id, "embed": SETTINGS.bedrock_embed_model_id,
        "rerank": SETTINGS.bedrock_rerank_model_id, "region": SETTINGS.aws_region,
        "rerank_region": SETTINGS.bedrock_rerank_region, "prices_checked_on": "2026-11-16",
        "total_cost": 0.0,
    }  # fmt: skip
