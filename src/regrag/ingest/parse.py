"""Turn a PDF into pages of clean text plus Markdown tables (SPEC section 5, "Parse").

For every page we produce:
- `text`: the body text in reading order (top to bottom). Where a table sat on the page,
  the text holds a placeholder line such as `[[TABLE:0]]`. Why a placeholder: the table's
  words are not repeated in the body, yet the chunker still knows *where* the table was,
  so it can keep the table inside the right section.
- `tables`: each table as a Markdown table, header row first.

Cleaned away: running headers and footers that repeat on most pages, bare page numbers,
and "(cid:NN)" glyph garbage that some bilingual (Hindi/English) PDFs produce. A page with
almost no text is flagged `scanned` (OCR is a non-goal for v1).
"""

import re
from collections import Counter
from pathlib import Path

import pdfplumber

from regrag.types import ParsedDocument, ParsedPage

TABLE_PLACEHOLDER = "[[TABLE:{index}]]"
TABLE_PLACEHOLDER_RE = re.compile(r"^\[\[TABLE:(\d+)\]\]$")
# Fewer characters than this (text + tables) and the page is treated as a scanned image.
MIN_PAGE_CHARS = 50
# Only the first and last few lines of a page can be a running header or footer.
EDGE_LINES = 2

_CID_GARBAGE = re.compile(r"\(cid:\d+\)")
# Table-of-contents entries: "C. Interpretation ........ 73". They only point elsewhere in
# the document, and as search results they would push out the real sections.
_TOC_LINE = re.compile(r"(\.\s?){5,}\s*\d{1,4}\s*$")
# "7", "- 7 -", "Page 7", "Page 7 of 30", "7/30"
_PAGE_NUMBER = re.compile(r"^\s*[-–]?\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*[-–]?\s*$", re.I)


class ParseError(RuntimeError):
    """The file could not be read as a PDF."""


def _clean(text: str) -> str:
    text = _CID_GARBAGE.sub("", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def table_to_markdown(rows: list[list[str | None]]) -> str:
    """Rows from pdfplumber (cells may be None or contain line breaks) to a Markdown table."""
    cleaned = [
        [_clean((cell or "").replace("\n", " ")).replace("|", r"\|") for cell in row]
        for row in rows
        if any(cell and cell.strip() for cell in row)
    ]
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    header, body = cleaned[0], cleaned[1:]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def _outside(bboxes: list[tuple[float, float, float, float]]):
    """A pdfplumber filter that drops characters lying inside any table."""

    def keep(obj) -> bool:
        if obj.get("object_type") != "char":
            return True
        x = (obj["x0"] + obj["x1"]) / 2
        y = (obj["top"] + obj["bottom"]) / 2
        return not any(x0 <= x <= x1 and top <= y <= bottom for x0, top, x1, bottom in bboxes)

    return keep


def _is_real_table(rows: list[list[str | None]]) -> bool:
    """False for a box drawn around a paragraph, which pdfplumber also reports as a table.

    Why: a one-column "table" is just boxed text. Turning it into a Markdown table splits
    the paragraph into one row per line, which reads worse than plain text.
    """
    widest = max((sum(1 for cell in row if cell and cell.strip()) for row in rows), default=0)
    return widest >= 2


def _page_items(page) -> tuple[list[tuple[float, str]], list[str], int]:
    """Text lines and table placeholders with their vertical position, the tables, and the
    page's character count *before* cleanup (used to spot scanned pages)."""
    tables, bboxes, items = [], [], []
    raw_chars = 0
    for table in page.find_tables():
        rows = table.extract()
        markdown = table_to_markdown(rows) if _is_real_table(rows) else ""
        if not markdown:
            continue  # its text stays in the body, read as normal lines
        items.append((table.bbox[1], TABLE_PLACEHOLDER.format(index=len(tables))))
        tables.append(markdown)
        bboxes.append(table.bbox)
        raw_chars += len(markdown)
    body = page.filter(_outside(bboxes)) if bboxes else page
    for line in body.extract_text_lines():
        text = _clean(line["text"])
        raw_chars += len(text)
        # Why count before dropping: a contents page that ends up empty is not a scanned page.
        if text and not _TOC_LINE.search(text):
            items.append((line["top"], text))
    items.sort(key=lambda item: item[0])  # top of the page first
    return items, tables, raw_chars


def _normalise(line: str) -> str:
    """Make "Page 3 of 30" and "Page 4 of 30" compare equal when finding repeats."""
    return re.sub(r"\d+", "#", line.lower()).strip()


def _repeated_edge_lines(pages_lines: list[list[str]]) -> set[str]:
    """Normalised lines that appear at the top or bottom of at least half the pages."""
    if len(pages_lines) < 2:
        return set()
    counts: Counter[str] = Counter()
    for lines in pages_lines:
        edges = lines[:EDGE_LINES] + lines[-EDGE_LINES:]
        counts.update({_normalise(line) for line in edges})
    threshold = max(2, len(pages_lines) / 2)
    return {line for line, n in counts.items() if n >= threshold}


def _strip_edges(lines: list[str], repeated: set[str]) -> list[str]:
    def is_noise(line: str) -> bool:
        if TABLE_PLACEHOLDER_RE.match(line):
            return False
        return _normalise(line) in repeated or bool(_PAGE_NUMBER.match(line))

    # Only look at the edges: a sentence in the middle of the page is never a footer.
    start, end = 0, len(lines)
    while start < min(EDGE_LINES, end) and is_noise(lines[start]):
        start += 1
    while end > start and end > len(lines) - EDGE_LINES and is_noise(lines[end - 1]):
        end -= 1
    return lines[start:end]


def parse_pdf(path: Path, doc_id: str | None = None) -> ParsedDocument:
    doc_id = doc_id or Path(path).stem
    try:
        with pdfplumber.open(path) as pdf:
            raw = [_page_items(page) for page in pdf.pages]
    except Exception as exc:  # pdfplumber raises several unrelated types for broken files
        raise ParseError(f"{doc_id}: cannot read {Path(path).name} as a PDF ({exc})") from exc

    pages_lines = [[text for _, text in items] for items, _, _ in raw]
    repeated = _repeated_edge_lines(pages_lines)

    pages = []
    for number, (lines, (_, tables, raw_chars)) in enumerate(
        zip(pages_lines, raw, strict=True), start=1
    ):
        text = "\n".join(_strip_edges(lines, repeated))
        scanned = raw_chars < MIN_PAGE_CHARS
        pages.append(ParsedPage(page_no=number, text=text, tables=tables, scanned=scanned))
    return ParsedDocument(doc_id=doc_id, pages=pages)
