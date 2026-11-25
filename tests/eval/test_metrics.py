"""Metrics, each checked against a hand-computed value (SPEC 6.3)."""

import pytest

from regrag.eval.golden import GoldenItem
from regrag.eval.metrics import (
    abstention_scores,
    citation_accuracy,
    citation_validity,
    is_relevant,
    latency_summary,
    mean,
    mrr,
    recall_at_k,
    supersession_flag_rate,
)
from regrag.types import ChunkRef


def item(docs=("gst-231-25-2024",), sections=()) -> GoldenItem:
    return GoldenItem(
        id="g1",
        question="q",
        corpus="gst",
        type="factual",
        expected_doc_ids=list(docs),
        expected_sections=list(sections),
        reference_answer="",
        should_abstain=False,
        must_flag_supersession=False,
        tags=[],
        source="manual",
        reviewed=True,
    )


def ref(doc, section="Para 1", cid=0) -> ChunkRef:
    return ChunkRef(chunk_id=cid, doc_id=doc, section_no=section)


RELEVANT = ref("gst-231-25-2024", "Paras 4–5")
OTHER = ref("gst-232-26-2024")


def test_document_level_match_when_no_sections_listed():
    assert is_relevant(RELEVANT, item())
    assert not is_relevant(OTHER, item())


def test_section_level_match_when_sections_listed():
    q = item(sections=[{"doc_id": "gst-231-25-2024", "section_no": "Para 4", "page": 2}])
    assert is_relevant(ref("gst-231-25-2024", "Chapter I, para 4"), q)
    assert not is_relevant(ref("gst-231-25-2024", "Para 9"), q)  # right doc, wrong section


def test_recall_at_k():
    ranked = [OTHER, OTHER, RELEVANT]
    assert recall_at_k(ranked, item(), k=2) == 0
    assert recall_at_k(ranked, item(), k=3) == 1


def test_mrr_uses_first_relevant_rank_and_zero_when_none():
    assert mrr([OTHER, RELEVANT, RELEVANT], item()) == pytest.approx(0.5)
    assert mrr([OTHER, OTHER], item()) == 0.0
    assert mrr([OTHER] * 10 + [RELEVANT], item(), k=10) == 0.0  # beyond the top 10


def test_citation_validity():
    # answer 1: C1, C2 with 2 chunks -> both valid; answer 2: C1, C5 with 3 -> C5 invalid
    assert citation_validity([(["C1", "C2"], 2), (["C1", "C5"], 3)]) == pytest.approx(0.75)
    assert citation_validity([([], 3)]) == 1.0  # nothing cited, nothing invented


def test_citation_accuracy_and_exclusion_when_nothing_cited():
    answers = [(["gst-231-25-2024", "gst-232-26-2024"], ["gst-231-25-2024"])]
    assert citation_accuracy(answers) == pytest.approx(0.5)
    assert citation_accuracy([([], ["gst-231-25-2024"])]) is None


def test_abstention_scores():
    # (abstained, should): TP, FP, FN, TN
    pairs = [(True, True), (True, False), (False, True), (False, False)]
    assert abstention_scores(pairs) == {"accuracy": 0.5, "precision": 0.5, "recall": 0.5}


def test_zero_abstentions_gives_none_precision_not_a_crash():
    scores = abstention_scores([(False, True), (False, False)])
    assert scores["precision"] is None and scores["recall"] == 0.0
    assert scores["accuracy"] == 0.5


def test_supersession_flag_rate():
    rows = [(True, True), (False, True), (True, False)]
    assert supersession_flag_rate(rows) == pytest.approx(0.5)
    assert supersession_flag_rate([(True, False)]) is None


def test_latency_summary_nearest_rank_p95():
    values = [float(v) for v in range(1, 21)]  # 1..20 ms; 95% of 20 = rank 19
    assert latency_summary(values) == {"mean": 10.5, "p95": 19.0}
    assert latency_summary([]) == {"mean": None, "p95": None}


def test_mean_skips_none():
    assert mean([1.0, None, 0.0]) == 0.5
    assert mean([None]) is None


@pytest.mark.parametrize(
    ("wanted", "chunk_section", "relevant"),
    [
        ("37", "37", True),
        ("37", "37(1)", True),
        ("37", "137(2)", False),  # was a false hit with plain containment
        ("37", "37A", False),
        ("16(2)", "16(2)(aa)", True),
        ("16(2)", "16(20)", False),
        ("17(5)", "17(5)(d)", True),
        ("Para 52", "Paras 50-52", False),  # non-statute labels keep containment
        ("Para 52", "Para 52 (cont.)", True),
    ],
)
def test_statute_sections_match_exactly_or_by_sub_part(wanted, chunk_section, relevant):
    doc = "gst-cgst-rules-2017"
    it = item(docs=(doc,), sections=({"doc_id": doc, "section_no": wanted},))
    assert is_relevant(ChunkRef(1, doc, chunk_section), it) is relevant
