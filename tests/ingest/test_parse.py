"""PDF parser tests on the synthetic fixture (tests/fixtures/sample_direction.pdf)."""

from pathlib import Path

import pytest
from fpdf import FPDF

from regrag.ingest.parse import (
    ParseError,
    _clean,
    _strip_edges,
    parse_pdf,
    table_to_markdown,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_direction.pdf"


@pytest.fixture(scope="module")
def doc():
    return parse_pdf(FIXTURE, doc_id="test-fixture")


def test_three_pages_numbered_from_one(doc):
    assert doc.doc_id == "test-fixture"
    assert [p.page_no for p in doc.pages] == [1, 2, 3]
    assert not any(p.scanned for p in doc.pages)


def test_table_appears_once_as_markdown_with_header(doc):
    all_tables = [t for p in doc.pages for t in p.tables]
    assert len(all_tables) == 1
    table = all_tables[0]
    assert table.splitlines()[0] == "| Instrument type | Maximum limit (Rs.) | Verification level |"
    assert table.splitlines()[1] == "|---|---|---|"
    assert "| Full test wallet | 2,00,000 | Full verification |" in table
    # The table's words are not repeated in the body text...
    assert "2,00,000" not in doc.pages[1].text
    # ...but a placeholder marks where it was, between paragraphs 3 and 4.
    lines = doc.pages[1].text.splitlines()
    i = lines.index("[[TABLE:0]]")
    assert lines[i - 1].startswith("3. Limits") and lines[i + 1].startswith("4. Review")


def test_running_header_and_footer_are_removed(doc):
    text = "\n".join(p.text for p in doc.pages)
    assert "SYNTHETIC REGULATOR OF TEST MATTERS" not in text
    assert "Page 1 of 3" not in text and "Test Directions, 2099 -" not in text


def test_body_text_is_kept_in_reading_order(doc):
    page1 = doc.pages[0].text
    assert page1.startswith("Chapter I - Preliminary")
    assert page1.index("1. Short title") < page1.index("2. Definitions")
    assert doc.pages[2].text.startswith("Annex - Test glossary")


def test_fixture_is_small():
    assert FIXTURE.stat().st_size < 100_000


def test_empty_page_is_flagged_scanned_without_crashing(tmp_path):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "A page with enough real text to count as a normal text page. " * 3)
    pdf.add_page()  # deliberately empty, like a scanned image with no text layer
    path = tmp_path / "with_blank.pdf"
    pdf.output(str(path))
    result = parse_pdf(path)
    assert [p.scanned for p in result.pages] == [False, True]
    assert result.pages[1].text == ""


def test_not_a_pdf_raises_parse_error(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_text("<html>this is not a pdf</html>", encoding="utf-8")
    with pytest.raises(ParseError, match="fake.pdf"):
        parse_pdf(path)


# --- Small helpers -------------------------------------------------------------------------


def test_table_to_markdown_handles_messy_cells():
    rows = [
        ["Name", "Limit", None],
        ["Wallet\nsmall", "10|000", None],  # line break inside a cell, a pipe character
        [None, None, None],  # empty row
        ["Short row"],  # fewer cells than the header
    ]
    assert table_to_markdown(rows) == (
        "| Name | Limit |  |\n|---|---|---|\n| Wallet small | 10\\|000 |  |\n| Short row |  |  |"
    )
    assert table_to_markdown([[None, ""]]) == ""


def test_clean_removes_cid_garbage_and_extra_spaces():
    assert _clean("(cid:5)(cid:11)Circular   No.  249 ") == "Circular No. 249"


def test_page_numbers_are_stripped_only_at_the_edges():
    lines = ["7", "Paragraph mentioning", "7", "the middle", "Page 7 of 30"]
    assert _strip_edges(lines, repeated=set()) == ["Paragraph mentioning", "7", "the middle"]


def test_a_line_repeated_only_on_one_page_is_kept(tmp_path):
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    for heading in ("Unique heading one", "Unique heading two", "Unique heading three"):
        pdf.add_page()
        pdf.cell(0, 8, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.multi_cell(0, 6, "Body text that is long enough to be a normal page. " * 3)
    path = tmp_path / "headings.pdf"
    pdf.output(str(path))
    result = parse_pdf(path)
    assert [p.text.splitlines()[0] for p in result.pages] == [
        "Unique heading one",
        "Unique heading two",
        "Unique heading three",
    ]


def test_table_of_contents_lines_are_dropped_but_page_is_not_scanned(tmp_path):
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    pdf.add_page()  # a contents page: only dotted leaders and page numbers
    for entry, page in (("A. Short title", 3), ("B. Definitions", 5), ("C. Interpretation", 73)):
        pdf.cell(0, 8, f"{entry} {'.' * 60} {page}", new_x="LMARGIN", new_y="NEXT")
    pdf.add_page()
    pdf.multi_cell(0, 6, "A. Short title. These synthetic directions apply to test entities. " * 2)
    path = tmp_path / "toc.pdf"
    pdf.output(str(path))
    result = parse_pdf(path)
    assert result.pages[0].text == ""  # contents entries removed
    assert result.pages[0].scanned is False  # ...but it had real text, so it isn't a scan
    assert result.pages[1].text.startswith("A. Short title")


def test_boxed_paragraph_stays_text_not_a_one_column_table(tmp_path):
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    pdf.add_page()
    pdf.multi_cell(0, 6, "Text before the box, long enough to be a normal page. " * 2)
    with pdf.table(col_widths=(170,)) as table:
        table.row().cell("A boxed note: entities must renew their test licence in time.")
    path = tmp_path / "boxed.pdf"
    pdf.output(str(path))
    page = parse_pdf(path).pages[0]
    assert page.tables == []
    assert "A boxed note: entities must renew" in page.text
