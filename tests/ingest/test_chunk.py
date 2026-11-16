"""Chunker tests on hand-built ParsedDocuments (no PDFs needed)."""

from datetime import date

import pytest

from regrag.config import Settings
from regrag.ingest.chunk import chunk_document, embedding_text, estimate_tokens
from regrag.types import ManifestRow, ParsedDocument, ParsedPage

SETTINGS = Settings()
ROW = ManifestRow(
    doc_id="rbi-test",
    corpus="rbi",
    doc_type="direction",
    title="Test Directions, 2099",
    reference_no="RBI/TEST/1",
    applies_to="",
    publish_date=date(2099, 1, 1),
    source_url="https://www.rbi.org.in/x",
    pdf_url="https://rbidocs.rbi.org.in/x.pdf",
)


def sentence(i: int) -> str:
    return f"Sentence number {i} explains an imaginary rule about imaginary test instruments."


def para(num: str, n_sentences: int, start: int = 0) -> str:
    return f"{num} " + " ".join(sentence(start + k) for k in range(n_sentences))


def doc(*pages: str, tables: dict[int, list[str]] | None = None) -> ParsedDocument:
    tables = tables or {}
    return ParsedDocument(
        doc_id="rbi-test",
        pages=[
            ParsedPage(page_no=i, text=text, tables=tables.get(i, []))
            for i, text in enumerate(pages, start=1)
        ],
    )


def chunks_of(parsed: ParsedDocument):
    return chunk_document(parsed, ROW, SETTINGS)


# A realistic two-chapter document: chapter I is short, chapter II is long enough to need
# several chunks.
TWO_CHAPTERS = doc(
    "Chapter I – Preliminary\nA. Short Title and Commencement.\n"
    + para("1.", 3)
    + "\n"
    + para("2.", 3, 10),
    "Chapter II – Limits\n" + "\n".join(para(f"{n}.", 12, n * 20) for n in range(3, 9)),
)


def test_no_chunk_exceeds_the_maximum():
    for chunk in chunks_of(TWO_CHAPTERS):
        assert chunk.token_count <= SETTINGS.chunk_max_tokens


def test_a_chunk_never_mixes_two_chapters():
    for chunk in chunks_of(TWO_CHAPTERS):
        chapters = {chunk.section_path.split(" > ")[0]}
        assert len(chapters) == 1
        if chunk.section_path.startswith("Chapter I –"):
            assert "Sentence number 60" not in chunk.content  # chapter II text


def test_labels_and_paths():
    chunks = chunks_of(TWO_CHAPTERS)
    first = chunks[0]
    assert first.section_path == "Chapter I – Preliminary > A. Short Title and Commencement"
    assert first.section_no == "Chapter I, paras 1–2"
    assert chunks[-1].section_no.startswith("Chapter II, para")
    assert all(c.content_type == "text" for c in chunks)


def test_paragraph_spanning_two_pages_records_both_pages():
    parsed = doc(
        "Chapter I – Preliminary\n" + para("1.", 3),
        "continues on the next page with the rest of paragraph one.\n" + para("2.", 2),
    )
    first = chunks_of(parsed)[0]
    assert (first.page_start, first.page_end) == (1, 2)


def test_adjacent_chunks_in_a_section_overlap_by_about_60_tokens():
    chunks = [c for c in chunks_of(TWO_CHAPTERS) if c.section_path.startswith("Chapter II")]
    assert len(chunks) >= 3
    for before, after in zip(chunks, chunks[1:], strict=False):
        # Find the longest end of `before` that `after` starts with.
        words = before.content.split()
        shared = next(
            (
                " ".join(words[k:])
                for k in range(len(words))
                if after.content.startswith(" ".join(words[k:]))
            ),
            "",
        )
        assert 40 <= estimate_tokens(shared) <= 80, shared


def test_chunk_index_is_continuous_and_output_is_repeatable():
    first, second = chunks_of(TWO_CHAPTERS), chunks_of(TWO_CHAPTERS)
    assert [c.chunk_index for c in first] == list(range(len(first)))
    assert first == second


def test_long_paragraph_is_split_into_windows():
    parsed = doc("Chapter I – Big\n" + para("1.", 60))  # about 1,200 tokens in one paragraph
    chunks = chunks_of(parsed)
    assert len(chunks) >= 3
    assert all(c.token_count <= SETTINGS.chunk_max_tokens for c in chunks)
    assert all(c.section_no == "Chapter I, para 1" for c in chunks)


SMALL_TABLE = (
    "| Instrument | Limit |\n|---|---|\n| Small wallet | 10,000 |\n| Full wallet | 2,00,000 |"
)


def test_table_becomes_its_own_chunk_in_place():
    parsed = doc(
        "Chapter II – Limits\n" + para("3.", 4) + "\n[[TABLE:0]]\n" + para("4.", 2, 5),
        tables={1: [SMALL_TABLE]},
    )
    chunks = chunks_of(parsed)
    kinds = [c.content_type for c in chunks]
    assert kinds == ["text", "table", "text"]
    assert chunks[1].content == SMALL_TABLE
    assert chunks[1].section_no == "Chapter II, para 3"
    assert "Small wallet" not in chunks[0].content


def test_short_text_before_a_table_becomes_its_caption():
    parsed = doc(
        "Annex I\nTable 1: Limits on test wallets\n[[TABLE:0]]",
        tables={1: [SMALL_TABLE]},
    )
    chunks = chunks_of(parsed)
    assert [c.content_type for c in chunks] == ["table"]  # no tiny caption-only chunk
    assert chunks[0].content == f"Table 1: Limits on test wallets\n\n{SMALL_TABLE}"


def test_bare_chapter_heading_takes_its_title_from_the_next_line():
    parsed = doc("Chapter IV\nKYC and Due Diligence\n" + para("20.", 3))
    chunks = chunks_of(parsed)
    assert len(chunks) == 1
    assert chunks[0].section_path == "Chapter IV – KYC and Due Diligence"
    assert chunks[0].content.startswith("20.")


def test_table_under_1000_tokens_is_never_split():
    rows = [f"| Row {i} | {'value ' * 12}|" for i in range(40)]
    table = "| Name | Value |\n|---|---|\n" + "\n".join(rows)
    assert SETTINGS.chunk_max_tokens < estimate_tokens(table) <= SETTINGS.table_max_tokens
    chunks = chunks_of(doc("Chapter I – T\n[[TABLE:0]]", tables={1: [table]}))
    assert len(chunks) == 1 and chunks[0].content == table


def test_big_table_is_split_with_the_header_repeated():
    rows = [f"| Row {i} | {'value ' * 20}|" for i in range(80)]
    table = "| Name | Value |\n|---|---|\n" + "\n".join(rows)
    assert estimate_tokens(table) > SETTINGS.table_max_tokens
    chunks = chunks_of(doc("Chapter I – T\n[[TABLE:0]]", tables={1: [table]}))
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.content.startswith("| Name | Value |\n|---|---|")
        assert chunk.token_count <= SETTINGS.table_max_tokens
    body_rows = [line for c in chunks for line in c.content.splitlines()[2:]]
    assert body_rows == rows  # every row exactly once, in order


@pytest.mark.parametrize(
    ("line", "is_heading"),
    [
        ("Chapter VI.", False),  # a wrapped sentence ending "... in Chapter VI."
        ("Chapter VI – Customer Due Diligence", True),
        ("15 percent of the property or capital of the association", False),
        ("1 Earlier, PPIs were classified under three types", False),  # a footnote
    ],
)
def test_heading_lookalikes(line, is_heading):
    parsed = doc("Chapter I – Preliminary\n" + para("1.", 2) + "\n" + line + "\nmore text here.")
    paths = {c.section_path for c in chunks_of(parsed)}
    assert any(line in p for p in paths) is is_heading


def test_part_inside_a_chapter_keeps_the_chapter():
    parsed = doc("Chapter VI – Due Diligence\nPart I\n" + para("16.", 2))
    chunk = chunks_of(parsed)[0]
    assert chunk.section_path == "Chapter VI – Due Diligence > Part I"
    assert chunk.section_no == "Chapter VI, para 16"


def test_gst_style_circular_without_chapters():
    parsed = doc(
        "Subject: Clarification on a test matter-reg.\n"
        + "Attention is invited to an imaginary earlier circular.\n"
        + para("2.", 2)
        + "\n"
        + para("3.", 2, 5)
    )
    chunks = chunks_of(parsed)
    assert len(chunks) == 1
    assert chunks[0].section_no == "Paras 2–3"
    assert chunks[0].section_path == ""


def test_scanned_pages_are_skipped():
    parsed = doc("Chapter I – A\n" + para("1.", 2), "")
    parsed.pages[1].scanned = True
    assert all(c.page_end == 1 for c in chunks_of(parsed))


def test_embedding_text_prefixes_title_and_path():
    chunk = chunks_of(TWO_CHAPTERS)[0]
    text = embedding_text(chunk, ROW.title)
    assert text.startswith(
        "Test Directions, 2099\nChapter I – Preliminary > A. Short Title and Commencement\n\n1."
    )
