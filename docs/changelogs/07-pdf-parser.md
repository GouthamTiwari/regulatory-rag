# Task 07: PDF parser (tables kept)
Branch: task/07-pdf-parser | Date: 2026-11-16

## What changed
- `src/regrag/ingest/parse.py`: `parse_pdf(path, doc_id) -> ParsedDocument` using `pdfplumber`.
  - **Tables** become Markdown tables, header row first. Line breaks inside cells become spaces, `|` is escaped, empty rows are dropped and short rows are padded. The table's characters are filtered out of the body, so table text is **not repeated**.
  - **Placeholders:** the body text holds a `[[TABLE:n]]` line at the table's position, so the chunker (Task 08) knows which section a table belongs to. `TABLE_PLACEHOLDER` and `TABLE_PLACEHOLDER_RE` are exported for that.
  - **Reading order:** text lines and placeholders are sorted top to bottom.
  - **Headers and footers:** lines in the first or last 2 lines of a page that repeat (digits ignored) on at least half the pages are removed, as are bare page numbers ("7", "Page 7 of 30", "- 7 -") at the page edges. Mid-page lines are never touched.
  - **Glyph garbage:** "(cid:NN)" sequences, which bilingual Hindi/English PDFs produce, are removed.
  - **Scanned pages:** pages with fewer than 50 characters *before* cleanup are flagged `scanned`.
  - **Errors:** an unreadable file raises `ParseError` naming the document.
  - **Two additions beyond the task text, found by parsing the real PDFs:**
    1. Table-of-contents lines ("C. Interpretation ...... 73") are dropped. They would compete with the real sections in search.
    2. A one-column "table" (a box drawn around a paragraph, e.g. 5 in the PPI direction) is kept as normal text, not a broken one-column table.
- `tests/ingest/make_fixture_pdf.py`: generates the synthetic fixture with `fpdf2`. It has a running header, headings, paragraphs, a ruled 3-column table and a "Page N of 3" footer, and contains **no real regulatory text**.
- `tests/fixtures/sample_direction.pdf`: the generated fixture (3,192 bytes), committed.
- `tests/ingest/test_parse.py`: tests (see below).

## How to verify
- `uv run pytest tests/ingest/test_parse.py` → 13 passed
- Whole corpus (manual check, not a test): all 65 PDFs parse with no errors. **1,210 pages, 251 tables, 2 scanned pages** (one each in `rbi-12957` and `gst-210-04-2024`, the latter its last page). About 1.93M characters (≈ 482K tokens), no "(cid:" left, 125 s in total.

## Tests
- 13 tests:
  - On the fixture: 3 pages numbered 1–3; the table appears once as Markdown with its header row and is absent from the body; the placeholder sits between paragraphs 3 and 4; the running header and footer are removed; reading order is kept; the fixture is under 100 KB.
  - Generated PDFs: an empty page is flagged `scanned` without crashing; a contents page is emptied but not flagged scanned; a boxed paragraph stays text; a heading that appears on only one page is kept.
  - Helpers and errors: messy table cells; cid cleanup; page numbers stripped only at the edges; a non-PDF raises `ParseError`.
- Full suite: 130 passed (+ 9 db), 0 failed.

## Out of scope / follow-ups
- Tables that continue across pages are emitted once per page (each part keeps its own header row if the PDF repeats it). Joining them is left to the chunker, if needed.
- Multi-row table headers (e.g. the KYC "FPI Type" table) come out as their first raw row. They're readable, but not a perfect header.
- Corpus size is about 482K tokens, well under SPEC 2.4's 1.5M estimate, so embedding will cost about $0.01.

## Review log
- Self-review: passed. All 3 acceptance criteria met. Checking the real corpus found three issues, all fixed with tests: contents lines, boxed paragraphs, and emptied contents pages wrongly flagged as scanned.
