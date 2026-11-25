"""The library API (task 36) with fake parts: no AWS, no database."""

import datetime as dt

import pytest

from regrag import api
from regrag.config import Settings
from regrag.query.pipeline import Parts
from tests.fakes import FakeReranker, FakeRetriever, FakeRouter, make_chunk

DAY = dt.date(2026, 11, 25)


def statute_chunk(chunk_id=99):
    return make_chunk(
        chunk_id,
        doc_id="gst-cgst-rules-2017",
        title="Central Goods and Services Tax Rules, 2017 (as amended)",
        section_no="36(4)",
        section_path="CGST Rules > r.36 Documentary requirements > 36(4)",
        source_url="https://taxinformation.cbic.gov.in/header.html",
    )


@pytest.fixture
def parts(monkeypatch):
    chunks = [make_chunk(1, doc_id="gst-231-25-2024"), make_chunk(2), make_chunk(3)]
    p = Parts(
        settings=Settings(),
        router=FakeRouter("gst"),
        retriever=FakeRetriever(chunks),
        reranker=FakeReranker(),
        generator=None,
        retry_generator=None,
        conn=object(),
        reference_lookup=lambda refs: [statute_chunk()],
    )
    monkeypatch.setattr(
        api, "_details", lambda conn, cs: {c.chunk_id: (c.chunk_id + 100, DAY) for c in cs}
    )
    monkeypatch.setattr(
        api,
        "section_url",
        lambda doc_id, path, default: (
            "https://taxinformation.cbic.gov.in/r36.html"
            if doc_id.startswith("gst-cgst")
            else default
        ),
    )
    return p


def test_search_returns_citable_snippets(parts):
    hits = api.search("ITC on demo vehicles", k=2, parts=parts)
    assert [h.snippet_id for h in hits] == ["gst-231-25-2024#101", "doc-2#102"]
    assert hits[0].checked_on == DAY and hits[0].text.startswith("Synthetic test content")


def test_named_provision_comes_first_with_its_section_page(parts):
    hits = api.search("What does rule 36(4) say?", k=3, parts=parts)
    first = hits[0]
    assert first.snippet_id == "gst-cgst-rules-2017#199" and first.section == "36(4)"
    assert first.url == "https://taxinformation.cbic.gov.in/r36.html" and first.score == 1.0
    assert len(hits) == 3


def test_rbi_search_never_pins_gst_law(parts):
    parts.reference_lookup = lambda refs: pytest.fail("must not look up GST law")
    parts.retriever = FakeRetriever([make_chunk(5, corpus="rbi")])
    hits = api.search("What does rule 36(4) say?", k=2, corpus="rbi", parts=parts)
    assert [h.doc_id for h in hits] == ["doc-5"]


def test_bad_corpus_is_refused(parts):
    with pytest.raises(ValueError):
        api.search("x", corpus="customs", parts=parts)


@pytest.mark.parametrize(
    ("path", "number"),
    [
        ("CGST Rules > r.36 Documentary requirements > 36(4)", "36"),
        ("CGST Act > s.16 Eligibility and conditions > 16(2)(aa)", "16"),
        ("CGST Act > Schedule II Activities > Schedule II", "Schedule II"),
        ("Para 4", ""),
    ],
)
def test_section_number(path, number):
    from regrag.ingest.statute import section_number

    assert section_number(path) == number


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self, **kw):
        return FakeCursor(self.rows)


def test_corpus_version_changes_with_any_document():
    a = api.corpus_version(conn=FakeConn([("gst-1", "aa", "titan"), ("rbi-2", "bb", "titan")]))
    b = api.corpus_version(conn=FakeConn([("gst-1", "aa", "titan"), ("rbi-2", "bc", "titan")]))
    assert a != b and len(a) == 12
    assert a == api.corpus_version(
        conn=FakeConn([("gst-1", "aa", "titan"), ("rbi-2", "bb", "titan")])
    )
