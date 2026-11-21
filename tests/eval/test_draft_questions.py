"""Question drafting, the review sheet and accepting reviewed rows (mocked LLM, no DB)."""

import csv
import json
from collections import Counter

import pytest

from regrag.eval.draft_questions import (
    HANDWRITTEN,
    REVIEW_COLUMNS,
    accept,
    draft_rows,
    existing_rows,
    handwritten_rows,
    parse_draft,
    spread_sample,
    write_review,
)
from regrag.eval.golden import GOLDEN_PATH, load_golden
from regrag.ingest.manifest import load_manifest
from regrag.types import Usage
from tests.fakes import make_chunk


def chunks_from(doc_sizes: dict[str, int]):
    out, cid = [], 0
    for doc, n in doc_sizes.items():
        for _ in range(n):
            cid += 1
            out.append(make_chunk(cid, doc_id=doc))
    return out


def test_sampling_covers_every_document_before_repeating():
    chunks = chunks_from({"rbi-big": 50, "gst-a": 2, "gst-b": 1, "gst-c": 3})
    picked = spread_sample(chunks, 6)
    first_four = Counter(c.doc_id for c in picked[:4])
    assert set(first_four) == {"rbi-big", "gst-a", "gst-b", "gst-c"}  # all four, once each
    assert len(picked) == 6 and len({c.chunk_id for c in picked}) == 6
    assert spread_sample(chunks, 6) == picked  # fixed seed: same sample every time


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)

    def complete(self, system, user, max_tokens=300):
        return self.replies.pop(0), Usage()


def test_drafts_carry_section_level_gold_and_bad_replies_are_skipped():
    chunks = [
        make_chunk(1, doc_id="gst-231-25-2024", corpus="gst", section_no="Para 4", page_start=2),
        make_chunk(2, doc_id="rbi-13141", corpus="rbi"),
    ]
    llm = FakeLLM(
        '{"question": "Can a dealer claim ITC on demo vehicles?", "answer": "Yes."}', "nope"
    )
    rows = draft_rows(chunks, llm, {})
    assert len(rows) == 1
    row = rows[0]
    assert (row["expected_doc_ids"], row["section_no"], row["page"]) == (
        "gst-231-25-2024",
        "Para 4",
        2,
    )
    assert row["source"] == "llm_drafted" and row["keep"] == ""


@pytest.mark.parametrize(
    "reply",
    [
        '{"question": "What does this passage say?", "answer": "x"}',
        '{"question": "Too short?"}',
        "[]",
    ],
)
def test_unusable_drafts_are_rejected(reply):
    assert parse_draft(reply) is None


def test_accept_writes_only_kept_rows_validated_and_reviewed(tmp_path):
    golden = tmp_path / "golden.jsonl"
    seed = {
        "schema_version": 1, "corpus": "rbi", "type": "factual", "expected_sections": [],
        "reference_answer": "TODO", "should_abstain": False, "must_flag_supersession": False,
        "tags": [], "source": "manual", "reviewed": False,
    }  # fmt: skip
    first = {**seed, "id": "g001", "question": "Which documents are OVDs for KYC?",
             "expected_doc_ids": ["rbi-13141"]}  # fmt: skip
    second = {**seed, "id": "g002", "question": "What is the small PPI loading limit?",
              "expected_doc_ids": ["rbi-12156"]}  # fmt: skip
    golden.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
    rows = existing_rows(golden) + handwritten_rows()
    rows += draft_rows(
        [make_chunk(1, doc_id="gst-231-25-2024", corpus="gst", section_no="Para 4", page_start=2)],
        FakeLLM('{"question": "Can a car dealer claim ITC on demo vehicles?", "answer": "Yes."}'),
        {},
    )
    rows[0]["keep"] = "Y"  # an existing seed question
    rows[0]["reference_answer"] = "Passport, driving licence, Aadhaar, voter ID and others."
    rows[-1]["keep"] = "y"  # the drafted one
    rows[2 + 4]["keep"] = "Yes"  # a hand-written abstain question
    review = tmp_path / "review.csv"
    write_review(review, rows)

    kept, total = accept(review, golden)
    assert kept == 3 and total == 4  # 2 seeds + 2 new; the seed was updated, not duplicated
    items = {i.id: i for i in load_golden(golden, include_unreviewed=True)}
    assert items["g001"].reviewed and items["g001"].reference_answer.startswith("Passport")
    new = [i for i in items.values() if i.id in ("g003", "g004")]
    assert all(i.reviewed for i in new)
    drafted = next(i for i in new if i.source == "llm_drafted")
    assert drafted.expected_sections == [
        {"doc_id": "gst-231-25-2024", "section_no": "Para 4", "page": 2}
    ]
    assert sum(i.reviewed for i in items.values()) == 3


def test_review_sheet_has_the_expected_columns(tmp_path):
    path = tmp_path / "r.csv"
    write_review(path, handwritten_rows())
    with open(path, encoding="utf-8-sig", newline="") as f:
        assert next(csv.reader(f)) == REVIEW_COLUMNS


def test_handwritten_questions_point_at_real_documents():
    known = {r.doc_id for r in load_manifest().rows}
    for h in HANDWRITTEN:
        assert set(h.get("expected_doc_ids", [])) <= known
        assert bool(h.get("should_abstain")) == (h["type"] == "abstain")


def test_committed_golden_set_is_reviewed_and_large_enough():
    items = load_golden(GOLDEN_PATH, include_unreviewed=True)
    assert len(items) >= 60 and all(i.reviewed for i in items)
    assert all("llm-reviewed" in i.tags for i in items)  # honest provenance
