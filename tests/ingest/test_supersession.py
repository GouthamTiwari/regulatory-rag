"""Supersession extraction. Sentences are written for the tests, in the style of real
RBI directions and CBIC circulars (no real document text)."""

import pytest

from regrag.ingest.supersession import (
    GENERIC_REF,
    extract_relations,
    find_refs,
    normalise_ref,
)
from regrag.types import Chunk


def chunk(content: str, content_type: str = "text", path: str = "", index: int = 0) -> Chunk:
    return Chunk(
        doc_id="doc-under-test",
        chunk_index=index,
        section_no="Para 1",
        section_path=path,
        page_start=1,
        page_end=1,
        content_type=content_type,
        content=content,
        token_count=len(content) // 4,
    )


def relations_of(sentence: str, doc_id: str = "gst-999-99-2099", reference_no: str = ""):
    rels = extract_relations(doc_id, [chunk(sentence)], reference_no)
    return [(r.relation, r.to_doc_ref) for r in rels]


POSITIVE = [
    # supersedes
    (
        "This circular is issued in supersession of Circular No. 31/05/2018-GST dated the 9th "
        "February, 2018.",
        [("supersedes", "31/05/2018-GST")],
    ),
    (
        "These Directions supersede the instructions contained in RBI/2019-20/88 on the same "
        "subject.",
        [("supersedes", "RBI/2019-20/88")],
    ),
    (
        "Circular No. 12/04/2017-GST stands superseded with immediate effect.",
        [("supersedes", "12/04/2017-GST")],
    ),
    (
        "The circular DPSS.CO.PD.No.1810/02.14.008 /2019-20 dated March 17, 2020 stands "
        "repealed with the issue of these Directions.",
        [("supersedes", "DPSS.CO.PD.NO.1810/02.14.008/2019-20")],
    ),
    (
        "The Master Direction RBI/DPSS/2017-18/58 is hereby repealed.",
        [("supersedes", "RBI/DPSS/2017-18/58")],
    ),
    # withdraws
    (
        "Circular No. 160/16/2021-GST stands withdrawn ab initio.",
        [("withdraws", "160/16/2021-GST")],
    ),
    (
        "Accordingly, Circular No. 45/19/2018-GST dated 30th May, 2018 is hereby withdrawn.",
        [("withdraws", "45/19/2018-GST")],
    ),
    (
        "The instructions in RBI/2021-22/12 have been rescinded.",
        [("withdraws", "RBI/2021-22/12")],
    ),
    # amends: two targets in one sentence give two relations
    (
        "To the above extent, Circular No. 122/41/2019- GST dated 05th November 2019 and "
        "128/47/2019-GST dated 23.12.2019 stands modified.",
        [("amends", "122/41/2019-GST"), ("amends", "128/47/2019-GST")],
    ),
    (
        "In partial modification of Circular No. 199/11/2023-GST, para 3 shall be read as follows.",
        [("amends", "199/11/2023-GST")],
    ),
    (
        "Amendment to Circular No. 31/05/2018-GST, dated 9th February, 2018 on proper officer.",
        [("amends", "31/05/2018-GST")],
    ),
    (
        "Paragraph 4 of RBI/2022-23/101 is amended as under.",
        [("amends", "RBI/2022-23/101")],
    ),
    # corrects
    (
        "Corrigendum to Circular No. 237/31/2024-GST dated 15th October, 2024.",
        [("corrects", "237/31/2024-GST")],
    ),
    # clarifies
    (
        "Clarification on warranty, in furtherance to Circular No. 195/07/2023-GST dated "
        "17.07.2023.",
        [("clarifies", "195/07/2023-GST")],
    ),
]


@pytest.mark.parametrize(("sentence", "expected"), POSITIVE)
def test_operative_sentences_are_extracted(sentence, expected):
    assert relations_of(sentence) == expected


NEGATIVE = [
    # explicit negation
    "This circular does not supersede Circular No. 195/07/2023-GST.",
    "Circular No. 45/19/2018-GST is not withdrawn and continues to apply.",
    # a bare mention of another circular
    "Attention is invited to Circular No. 204/16/2023-GST dated 27th October, 2023.",
    # boilerplate found throughout the real RBI directions
    "Banks shall follow RBI/2020-21/15 as amended from time to time.",
    "Notwithstanding such repeal, any action taken under RBI/2019-20/88 shall continue.",
    "Further, the repeal of these directions shall not in any way affect any right acquired.",
    "The directions repealed prior to the issuance of these Directions shall continue to "
    "remain repealed.",
    # an operative word but nothing it applies to
    "The amended list of nodal officers stands modified every July.",
]


@pytest.mark.parametrize("sentence", NEGATIVE)
def test_non_operative_sentences_give_nothing(sentence):
    assert relations_of(sentence) == []


def test_reference_to_the_document_itself_is_ignored():
    # A circular mentioning its own number in a sentence with "corrigendum".
    sentence = "A corrigendum to Circular No. 237/31/2024-GST is issued separately."
    assert relations_of(sentence, doc_id="gst-237-31-2024") == []


def test_vide_reference_is_not_the_target_but_generic_repeal_is_recorded():
    sentence = (
        "With the issue of these Directions, the existing Directions, instructions and "
        "guidelines relating to outsourcing stand repealed, as communicated vide circular "
        "DOR.ORG.REC.No.11/21.04.158/2025-26 dated November 28, 2025."
    )
    assert relations_of(sentence, doc_id="rbi-13139") == [("supersedes", GENERIC_REF)]


def test_repeal_list_table_marks_every_listed_circular():
    table = (
        "List of circulars repealed with the issuance of this Master Direction\n\n"
        "| S.No. | Circular No. | Date |\n|---|---|---|\n"
        "| 1. | DPSS.CO.PD.No.1810/02.14.008 /2019-20 | March 17, 2020 |\n"
        "| 2. | RBI/2021-22/22 | April 1, 2021 |"
    )
    rels = extract_relations("rbi-12896", [chunk(table, content_type="table")])
    assert [(r.relation, r.to_doc_ref) for r in rels] == [
        ("supersedes", "DPSS.CO.PD.NO.1810/02.14.008/2019-20"),
        ("supersedes", "RBI/2021-22/22"),
    ]
    assert rels[0].evidence.startswith("| 1. |")


def test_ordinary_table_with_a_circular_number_is_ignored():
    table = "| Topic | Reference |\n|---|---|\n| Cards | RBI/2021-22/22 |"
    assert extract_relations("rbi-1", [chunk(table, content_type="table")]) == []


def test_relations_carry_evidence_and_are_unreviewed_and_deduplicated():
    text = (
        "Circular No. 45/19/2018-GST is hereby withdrawn. "
        "For clarity, Circular No. 45/19/2018-GST stands withdrawn."
    )
    rels = extract_relations("gst-1-1-2099", [chunk(text)])
    assert len(rels) == 1
    rel = rels[0]
    assert (rel.source, rel.reviewed, rel.to_doc_id) == ("extracted", False, None)
    assert rel.evidence == "Circular No. 45/19/2018-GST is hereby withdrawn."


@pytest.mark.parametrize(
    "spelling",
    [
        "Circular No. 195/07/2023 - GST",
        "195/07/2023-GST",
        "195/7/2023-GST",
        "circular no.195/07/2023-gst",
        "195 / 07 / 2023 – GST",
    ],
)
def test_normalise_ref_makes_spellings_equal(spelling):
    assert normalise_ref(spelling) == "195/07/2023-GST"


def test_normalise_rbi_and_department_refs():
    assert normalise_ref("RBI / 2025-26 / 79") == "RBI/2025-26/79"
    assert normalise_ref("DPSS.CO.PD No.1343/02.14.003/2019-20") == (
        "DPSS.CO.PD NO.1343/02.14.003/2019-20".replace(" ", "")
    )


def test_find_refs_returns_each_reference_once_in_order():
    sentence = "See RBI/2020-21/1, then 31/05/2018-GST, then RBI/2020-21/1 again."
    assert find_refs(sentence) == ["RBI/2020-21/1", "31/05/2018-GST"]


def test_sentences_do_not_break_after_abbreviations():
    from regrag.ingest.supersession import sentences

    text = "See Circular No. 31/05/2018-GST and Rs. 500 limit. Next sentence i.e. this one."
    assert sentences(text) == [
        "See Circular No. 31/05/2018-GST and Rs. 500 limit.",
        "Next sentence i.e. this one.",
    ]


def test_corrigendum_targets_its_base_circular():
    rels = extract_relations(
        "gst-237-31-2024-corr",
        [chunk("Corrigendum to Circular No. 237/31/2024-GST dated 15th October, 2024.")],
        reference_no="Corrigendum to 237/31/2024-GST",
    )
    assert [(r.relation, r.to_doc_ref) for r in rels] == [("corrects", "237/31/2024-GST")]


def test_historical_mentions_are_not_targets():
    sentence = (
        "Further para 7.3 of the Circular No. 31/05/2018-GST dated 9th February, 2018 (as "
        "amended by Circular No. 169/01/2022-GST dated 12th March, 2022) is substituted as "
        "below, and any corrigendum issued earlier is not relevant."
    )
    # Earliest operative phrase wins ("is substituted" -> amends, not "corrigendum"),
    # and the "(as amended by ...)" circular is history, not a target.
    assert relations_of(sentence) == [("amends", "31/05/2018-GST")]


def test_earlier_modification_vide_para_is_not_a_target():
    sentence = (
        "Accordingly, para 36 of Circular No. 125/44/2019-GST, which was earlier modified vide "
        "Para 5 of Circular No. 135/05/2020-GST, stands modified to that extent."
    )
    assert relations_of(sentence) == [("amends", "125/44/2019-GST")]
