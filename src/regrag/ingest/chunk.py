"""Split a parsed document into section-aware chunks (SPEC section 5, "Chunk").

How it works:
1. Walk the document line by line and recognise three kinds of structure:
   - top-level headings: "Chapter I – Preliminary", "Part B", "Annex II";
   - titled sub-headings: "A. Short Title and Commencement.", "1. Introduction", "1.4 Purpose";
   - numbered paragraphs: "16. These directions ...", "2.1 Closed System PPIs ...".
   A heading starts a new *section*. A chunk never crosses a section boundary, so a chunk
   never mixes, say, Chapter II with Chapter III.
2. Inside a section, whole paragraphs are packed into chunks of about 400 tokens (hard max
   500). Consecutive chunks of the same section overlap by about 60 tokens, so a sentence
   cut at a boundary is still complete in one of them. A paragraph bigger than the maximum
   is split into overlapping windows.
3. Tables become their own chunks and are only split above 1,000 tokens, repeating the
   header row in every piece.

Every chunk records its section number (e.g. "Chapter VI, paras 16–18") and the pages
its words came from, which is what answers will cite.
"""

import math
import re
from dataclasses import dataclass, field

from regrag.config import Settings
from regrag.ingest.parse import TABLE_PLACEHOLDER_RE
from regrag.types import Chunk, ManifestRow, ParsedDocument

PARA_BREAK = "\n\n"

# "Chapter I – Preliminary", "CHAPTER III", "Part B: Scope". A wrapped sentence such as
# "Chapter VI." ends in a full stop and so does not match.
_TOP_HEADING = re.compile(
    r"^(?P<kind>chapter|part)\s+(?P<num>[IVXLC]+|\d{1,3}|[A-Z])\b\s*(?:[–\-:]\s*(?P<title>.+))?$",
    re.I,
)
# "Annex I", "Annex – II", "Annexure 3", "Appendix", "Schedule A" (only on short lines).
_ANNEX_HEADING = re.compile(
    r"^(?P<kind>annex(?:ure)?|appendix|schedule)\b\s*[–\-:]?\s*(?P<num>[IVXLC]+|\d{1,3}|[A-Z])?\b",
    re.I,
)
# "A. Short Title and Commencement." (letter headings may end with a full stop)
_LETTER_HEADING = re.compile(r"^(?P<num>[A-Z])\.\s+(?P<title>[A-Z][^.;:]{2,80})\.?$")
# "1. Introduction", "1.4 Purpose": short, starts with a capital, no full stop at the end.
# The number must contain a dot, so a footnote like "1 Earlier, PPIs were ..." is not one.
_NUMBER_HEADING = re.compile(
    r"^(?P<num>\d{1,3}\.(?:\d{1,3}(?:\.\d{1,3})*)?)\s+(?P<title>[A-Z][^.;:]{2,70})$"
)
# A numbered paragraph: "16. These ...", "2.1 Closed ...". A whole number needs its dot,
# so a wrapped line like "15 percent of ..." or a footnote "1 Earlier, ..." is not one.
_PARA_START = re.compile(r"^(?P<num>\d{1,3}\.(?:\d{1,3}\.?)*)\s+\S")
_MAX_HEADING_WORDS = 12
# Text shorter than this, right before a table, is treated as the table's caption.
CAPTION_MAX_TOKENS = 40


def estimate_tokens(text: str) -> int:
    """About 4 characters per token: close enough for sizing chunks (SPEC 5)."""
    return math.ceil(len(text) / 4) if text else 0


@dataclass
class _Label:
    prefix: str  # "Chapter I", "Annex II" or "" (no chapter)
    num: str | None  # paragraph number, e.g. "16" or "2.1"


@dataclass
class _Block:
    kind: str  # "text" or "table"
    section: int  # which section it belongs to (increments at every heading)
    path: str
    label: _Label
    words: list[tuple[str, int]] = field(default_factory=list)  # (word, page)
    table: str = ""
    page: int = 0


def _top_heading(line: str) -> tuple[str, str] | None:
    """(short name, full heading) for a top-level heading line, else None."""
    if len(line) > 100:
        return None
    m = _TOP_HEADING.match(line)
    if m:
        short = f"{m['kind'].capitalize()} {m['num'].upper()}"
        return short, line
    m = _ANNEX_HEADING.match(line)
    if m and len(line.split()) <= 8:
        short = m["kind"].capitalize() + (f" {m['num'].upper()}" if m["num"] else "")
        return short, line
    return None


def _is_bare(heading: str) -> bool:
    """True for a heading with no title, e.g. "Chapter IV" or "Annex-1": its title is
    usually printed on the next line."""
    return bool(re.fullmatch(r"[A-Za-z]+\s*[–\-:]?\s*([IVXLC]+|\d{1,3}|[A-Z])?\s*[–\-:]?", heading))


def _is_title_line(line: str) -> bool:
    """A short line that reads like a heading title: "KYC and Due Diligence"."""
    return (
        len(line.split()) <= 10
        and not line.endswith((".", ",", ";"))
        and not _PARA_START.match(line)
        and line[:1].isupper()
        # "Table 1: ..." names the table below it (a caption), not the section.
        and not re.match(r"table\s+\d", line, re.I)
    )


def _sub_heading(line: str) -> tuple[str | None, str] | None:
    """(paragraph number or None, heading) for a titled sub-heading line, else None."""
    if len(line.split()) > _MAX_HEADING_WORDS:
        return None
    m = _LETTER_HEADING.match(line)
    if m:
        return None, line.rstrip(".")
    m = _NUMBER_HEADING.match(line)
    if m:
        return m["num"].rstrip("."), line
    return None


def _blocks(parsed: ParsedDocument) -> list[_Block]:
    """Turn pages into a flat list of paragraph and table blocks, tagged with sections."""
    blocks: list[_Block] = []
    section, top_name, top_path, sub_path = 0, "", "", ""
    label = _Label("", None)
    current: _Block | None = None
    expect_title = False  # the previous line was a bare "Chapter IV" / "Annex-1"

    def path() -> str:
        return " > ".join(p for p in (top_path, sub_path) if p)

    def new_text_block() -> _Block:
        block = _Block("text", section, path(), _Label(label.prefix, label.num))
        blocks.append(block)
        return block

    for page in parsed.pages:
        if page.scanned:
            continue
        for line in page.text.splitlines():
            line = line.strip()
            if not line:
                continue
            if expect_title:
                expect_title = False
                if _is_title_line(line) and not _top_heading(line) and not _sub_heading(line):
                    top_path = f"{top_path} – {line}"
                    continue
            placeholder = TABLE_PLACEHOLDER_RE.match(line)
            if placeholder:
                index = int(placeholder.group(1))
                if index < len(page.tables):
                    blocks.append(
                        _Block(
                            "table",
                            section,
                            path(),
                            _Label(label.prefix, label.num),
                            table=page.tables[index],
                            page=page.page_no,
                        )
                    )
                current = None  # text after a table starts a new paragraph
                continue
            top = _top_heading(line)
            if top and top[0].startswith("Part") and top_name.startswith("Chapter"):
                # "Part I" inside a chapter is a subdivision of it, not a new top level.
                section += 1
                sub_path = line
                current = None
                continue
            if top:
                section += 1
                top_name, top_path, sub_path = top[0], top[1], ""
                label = _Label(top_name, None)
                current = None
                expect_title = _is_bare(line)
                continue
            sub = _sub_heading(line)
            if sub:
                section += 1
                sub_path = sub[1]
                label = _Label(top_name, sub[0] or label.num)
                current = None
                continue
            para = _PARA_START.match(line)
            if para:
                label = _Label(top_name, para["num"].rstrip("."))
                current = new_text_block()
            elif current is None:
                current = new_text_block()
            current.words.extend((word, page.page_no) for word in line.split())
    return [b for b in blocks if b.kind == "table" or b.words]


def _format_section_no(labels: list[_Label]) -> str:
    prefix = labels[0].prefix
    nums: list[str] = []
    for lab in labels:
        if lab.num and lab.num not in nums:
            nums.append(lab.num)
    if not nums:
        return prefix or "Preamble"
    para = f"para {nums[0]}" if len(nums) == 1 else f"paras {nums[0]}–{nums[-1]}"
    return f"{prefix}, {para}" if prefix else para[0].upper() + para[1:]


def _text_of(words: list[tuple[str, int]]) -> str:
    text = " ".join(w for w, _ in words)
    return re.sub(r" ?\n\n ?", PARA_BREAK, text).strip()


def _tail(words: list[tuple[str, int]], tokens: int) -> list[tuple[str, int]]:
    """The last words of a chunk adding up to about `tokens` tokens (the overlap)."""
    out, size = [], 0
    for word, page in reversed(words):
        if word == PARA_BREAK and not out:
            continue
        size += estimate_tokens(word + " ")
        if size > tokens:
            break
        out.append((word, page))
    out.reverse()
    while out and out[0][0] == PARA_BREAK:
        out.pop(0)
    return out


def _windows(words, size: int, overlap: int):
    """Split one long word list into windows of about `size` tokens sharing `overlap`."""
    start = 0
    while start < len(words):
        end, used = start, 0
        while end < len(words) and used + estimate_tokens(words[end][0] + " ") <= size:
            used += estimate_tokens(words[end][0] + " ")
            end += 1
        end = max(end, start + 1)  # always make progress, even on a giant "word"
        yield words[start:end]
        if end >= len(words):
            return
        back = len(_tail(words[start:end], overlap))
        start = max(end - back, start + 1)


def _split_table(table: str, max_tokens: int) -> list[str]:
    """Split a big Markdown table into pieces under max_tokens, each with the header rows."""
    lines = table.splitlines()
    header, rows = lines[:2], lines[2:]
    pieces, current = [], []
    for row in rows:
        candidate = "\n".join(header + current + [row])
        if current and estimate_tokens(candidate) > max_tokens:
            pieces.append("\n".join(header + current))
            current = []
        current.append(row)
    if current or not pieces:
        pieces.append("\n".join(header + current))
    return pieces


def chunk_document(parsed: ParsedDocument, row: ManifestRow, settings: Settings) -> list[Chunk]:
    target, hard_max = settings.chunk_target_tokens, settings.chunk_max_tokens
    overlap, table_max = settings.chunk_overlap_tokens, settings.table_max_tokens
    drafts: list[tuple[str, str, list[_Label], str, int, int]] = []

    def emit_text(words, labels, path):
        if words and labels:
            pages = [p for w, p in words if w != PARA_BREAK]
            drafts.append(("text", path, labels, _text_of(words), min(pages), max(pages)))

    blocks = _blocks(parsed)
    i = 0
    while i < len(blocks):
        section = blocks[i].section
        current: list[tuple[str, int]] = []  # words of the chunk being filled
        labels: list[_Label] = []  # labels of the blocks that started in this chunk
        fresh_from = 0  # where this chunk's own words start (before: overlap carried over)
        path = blocks[i].path
        while i < len(blocks) and blocks[i].section == section:
            block = blocks[i]
            i += 1
            if block.kind == "table":
                # A short text right before a table ("Table 1: List of circulars") is its
                # caption: it goes with the table instead of becoming a tiny chunk alone.
                fresh = [w for w in current[fresh_from:] if w[0] != PARA_BREAK]
                caption, page_start = "", block.page
                if labels and estimate_tokens(_text_of(fresh)) < CAPTION_MAX_TOKENS:
                    caption = _text_of(fresh)
                    page_start = min(p for _, p in fresh)
                    current = []
                else:
                    emit_text(current, labels, path)
                    current = _tail(current, overlap) if current else []
                labels, fresh_from = [], len(current)
                if estimate_tokens(block.table) <= table_max:
                    pieces = [block.table]
                else:
                    pieces = _split_table(block.table, table_max)
                for piece in pieces:
                    content = f"{caption}{PARA_BREAK}{piece}" if caption else piece
                    drafts.append(
                        ("table", block.path, [block.label], content, page_start, block.page)
                    )
                continue
            words = block.words
            size = estimate_tokens(_text_of(words))
            if size > hard_max:
                # One paragraph bigger than a chunk: overlapping windows over it alone.
                emit_text(current, labels, path)
                for window in _windows(words, target, overlap):
                    emit_text(window, [block.label], block.path)
                current, labels, fresh_from = [], [], 0
                continue
            separator = [(PARA_BREAK, words[0][1])] if current else []
            if labels and estimate_tokens(_text_of(current + separator + words)) > target:
                emit_text(current, labels, path)
                carry = _tail(current, overlap)
                # Keep the overlap only if the next chunk still fits under the hard max.
                if estimate_tokens(_text_of(carry + separator + words)) > hard_max:
                    carry = []
                current, labels, fresh_from = carry, [], len(carry)
                separator = [(PARA_BREAK, words[0][1])] if current else []
            if not labels:
                path = block.path
            current = current + separator + words
            labels.append(block.label)
        emit_text(current, labels, path)

    return [
        Chunk(
            doc_id=row.doc_id,
            chunk_index=index,
            section_no=_format_section_no(labels),
            section_path=path,
            page_start=page_start,
            page_end=page_end,
            content_type=kind,
            content=content,
            token_count=estimate_tokens(content),
        )
        for index, (kind, path, labels, content, page_start, page_end) in enumerate(drafts)
    ]


def embedding_text(chunk: Chunk, title: str) -> str:
    """What gets embedded: document title and section path, then the chunk text.

    Why: a bare paragraph such as "The limit shall be Rs. 10,000" means nothing without
    knowing which document and section it comes from.
    """
    header = "\n".join(part for part in (title, chunk.section_path) if part)
    return f"{header}\n\n{chunk.content}" if header else chunk.content
