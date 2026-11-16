"""Supersession filter: pure logic with data and callables, no database."""

from regrag.query.supersession import apply_supersession
from regrag.types import Relation
from tests.fakes import make_chunk

DOCS = {
    "rbi-12799": {"status": "active", "reference_no": "RBI/FIDD/2024-25/128", "title": "PSL 2025"},
    "rbi-11959": {
        "status": "superseded",
        "reference_no": "RBI/FIDD/2020-21/72",
        "title": "PSL 2020",
    },
    "gst-195-07-2023": {"status": "active", "reference_no": "195/07/2023-GST", "title": "Warranty"},
    "gst-216-10-2024": {
        "status": "active",
        "reference_no": "216/10/2024-GST",
        "title": "Warranty 2",
    },
    "rbi-9": {"status": "withdrawn", "reference_no": "RBI/OLD/9", "title": "Old"},
}
SUPERSEDES = Relation(
    "rbi-12799",
    "supersedes",
    "RBI/FIDD/2020-21/72",
    "rbi-11959",
    evidence="e",
    source="manual",
    reviewed=True,
)
CLARIFIES = Relation(
    "gst-216-10-2024",
    "clarifies",
    "195/07/2023-GST",
    "gst-195-07-2023",
    evidence="e",
    source="manual",
    reviewed=True,
)
NEW_PSL = make_chunk(50, doc_id="rbi-12799", corpus="rbi")


def run(chunks, relations, replacement=NEW_PSL):
    return apply_supersession(chunks, DOCS, relations, lambda doc_id: replacement)


def test_superseded_with_replacement_in_corpus():
    old = [make_chunk(1, doc_id="rbi-11959"), make_chunk(2, doc_id="rbi-11959")]
    chunks, notes = run(old, [SUPERSEDES])
    assert [c.chunk_id for c in chunks] == [1, 50]  # one old chunk kept, the new one added
    assert chunks[0].supersession_mark == "SUPERSEDED BY RBI/FIDD/2024-25/128"
    assert notes == [
        "RBI/FIDD/2020-21/72 was superseded by RBI/FIDD/2024-25/128; the current rule is in "
        "RBI/FIDD/2024-25/128."
    ]


def test_replacement_already_present_is_not_duplicated():
    chunks, _ = run([make_chunk(1, doc_id="rbi-11959"), NEW_PSL], [SUPERSEDES])
    assert [c.chunk_id for c in chunks] == [1, 50]


def test_superseded_without_replacement_in_corpus_is_kept_and_marked():
    chunks, notes = run([make_chunk(3, doc_id="rbi-9")], [], replacement=None)
    assert chunks[0].supersession_mark == "WITHDRAWN"
    assert notes == ["RBI/OLD/9 is marked withdrawn; check for a newer document."]


def test_amended_document_keeps_its_chunk_with_a_note():
    chunks, notes = run([make_chunk(4, doc_id="gst-195-07-2023")], [CLARIFIES])
    assert [c.chunk_id for c in chunks] == [4] and chunks[0].supersession_mark is None
    assert notes == ["195/07/2023-GST was clarified by 216/10/2024-GST."]


def test_active_documents_pass_through_unchanged():
    original = [make_chunk(5, doc_id="gst-216-10-2024"), make_chunk(6, doc_id="rbi-12799")]
    chunks, notes = run(original, [SUPERSEDES, CLARIFIES])
    assert chunks == original and notes == []


def test_unreviewed_links_are_ignored():
    unreviewed = Relation(
        "gst-216-10-2024", "clarifies", "195/07/2023-GST", "gst-195-07-2023", evidence="e"
    )
    chunks, notes = run([make_chunk(4, doc_id="gst-195-07-2023")], [unreviewed])
    assert notes == []
