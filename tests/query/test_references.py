"""Provision references in questions (task 34): parsing and chunk matching, no database."""

import pytest

from regrag.query.references import (
    CGST_ACT,
    CGST_RULES,
    IGST_ACT,
    Reference,
    matches,
    parse_references,
)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What does rule 36(4) say?", [(CGST_RULES, "36(4)")]),
        ("Explain section 16(2)(aa) of the CGST Act", [(CGST_ACT, "16(2)(aa)")]),
        ("s.16(4) time limit", [(CGST_ACT, "16(4)")]),
        ("Is ITC under sec. 17(5)(d) blocked?", [(CGST_ACT, "17(5)(d)")]),
        ("IGST section 19 refund", [(IGST_ACT, "19")]),
        ("section 19 of the IGST Act", [(IGST_ACT, "19")]),
        ("rule 37A and rule 88D", [(CGST_RULES, "37A"), (CGST_RULES, "88D")]),
        ("Section 54 ( 3 ) refund", [(CGST_ACT, "54(3)")]),
        ("What is in Schedule II?", [(CGST_ACT, "Schedule II")]),
        ("section 16 of the Central Goods and Services Tax Act", [(CGST_ACT, "16")]),
        ("What is the 2B?", []),
        ("How do I claim ITC on a missing invoice?", []),
    ],
)
def test_parse_references(question, expected):
    assert [(r.doc_id, r.ref) for r in parse_references(question)] == expected


@pytest.mark.parametrize(
    "question",
    [
        "section 35A of the Banking Regulation Act",
        "Section 45L of the Reserve Bank of India Act",
        "section 8 of the Foreign Exchange Management Act, 1999",
    ],
)
def test_sections_of_other_acts_are_ignored(question):
    assert parse_references(question) == []


def test_labels():
    assert Reference(CGST_RULES, "36(4)").label == "CGST Rules r.36(4)"
    assert Reference(IGST_ACT, "19").label == "IGST Act s.19"
    assert Reference(CGST_ACT, "Schedule II").label == "CGST Act Schedule II"


@pytest.mark.parametrize(
    ("ref", "path", "hit"),
    [
        ("16(2)(aa)", "CGST Act > s.16 Eligibility > 16(2)(a), 16(2)(aa)", True),
        ("16(2)", "CGST Act > s.16 Eligibility > 16(2)(a), 16(2)(aa)", True),
        ("16", "CGST Act > s.16 Eligibility > 16(4)", True),
        ("16(2)", "CGST Act > s.16 Eligibility > 16(20)", False),
        ("16(4)", "CGST Act > s.16 Eligibility > 16(2)(a), 16(2)(aa)", False),
        ("16", "CGST Act > s.16 Eligibility > 16 amendment notes", True),
        ("Schedule II", "CGST Act > Schedule II Activities > Schedule II", True),
    ],
)
def test_chunk_matching(ref, path, hit):
    assert matches(Reference(CGST_ACT, ref), path) is hit
