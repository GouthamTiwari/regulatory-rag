"""Find provisions a question names, such as "rule 36(4)" or "IGST section 19" (task 34).

A question that names a provision should get that provision's text first; ordinary search
then adds context. This module only parses text; ``lookup`` reads the matching chunks of the
statute documents from the database (no Bedrock call).

Which statute:
- "rule ..." / "r. ..."            -> CGST Rules
- "section ..." / "s. ..." / "sec." -> CGST Act, or the IGST Act if the question says IGST
- "Schedule I" ... "Schedule IV"    -> CGST Act schedules
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from psycopg.rows import dict_row

from regrag.db.repository import RETRIEVED_COLUMNS, row_to_retrieved
from regrag.types import RetrievedChunk

CGST_ACT = "gst-cgst-act-2017"
CGST_RULES = "gst-cgst-rules-2017"
IGST_ACT = "gst-igst-act-2017"
PREFIX = {CGST_ACT: "s.", CGST_RULES: "r.", IGST_ACT: "s."}
LABEL = {CGST_ACT: "CGST Act", CGST_RULES: "CGST Rules", IGST_ACT: "IGST Act"}

_PART = r"(?:\s*\(\s*[0-9a-zA-Z]{1,5}\s*\))*"
_SECTION = re.compile(
    r"\b(?P<igst>IGST\s+(?:Act\s*,?\s*(?:2017\s*,?\s*)?)?)?"
    r"(?P<kind>sections?|sec\.|s\.|rules?|r\.)\s*(?P<num>\d{1,3}[A-Za-z]{0,2})"
    r"(?P<parts>" + _PART + r")"
    r"(?P<tail>\s+of\s+(?:the\s+)?(?P<act>IGST|CGST)\b)?",
    re.IGNORECASE,
)
_OTHER_ACT = re.compile(
    r"\s+of\s+(?:the\s+)?([A-Z][\w()]*\s+(?:(?:[A-Z][\w()]*|of|and|the|&)\s+){0,7}Act)\b"
)
_SCHEDULE = re.compile(r"\bSchedule\s+(?P<num>IV|III|II|I)\b(?!\w)")
MAX_PER_REFERENCE = 3


@dataclass(frozen=True)
class Reference:
    doc_id: str
    ref: str  # "16(2)(aa)", "36(4)", "Schedule II"

    @property
    def label(self) -> str:
        if self.ref.startswith("Schedule"):
            return f"{LABEL[self.doc_id]} {self.ref}"
        return f"{LABEL[self.doc_id]} {PREFIX[self.doc_id]}{self.ref}"


def parse_references(question: str) -> list[Reference]:
    """Every provision the question names, in order, without duplicates."""
    says_igst = re.search(r"\bIGST\b|integrated\s+goods", question, re.IGNORECASE) is not None
    out: list[Reference] = []
    for m in _SECTION.finditer(question):
        other = _OTHER_ACT.match(question, m.end())
        if other and not re.search(r"\b(C|I)?GST\b|Goods\s+and\s+Services", other.group(1), re.I):
            continue  # "section 35A of the Banking Regulation Act": not GST law
        kind = m.group("kind").lower()
        number = m.group("num").upper()
        parts = "".join(
            f"({p.lower()})" for p in re.findall(r"\(\s*(\w{1,5})\s*\)", m.group("parts") or "")
        )
        # Sub-sections are numbers (4) and stay as written; clauses are lowercase (aa).
        parts = re.sub(r"\((\d+)([a-z]?)\)", lambda x: f"({x.group(1)}{x.group(2).upper()})", parts)
        if kind.startswith("r"):
            doc = CGST_RULES
        elif (
            m.group("igst")
            or (m.group("act") or "").upper() == "IGST"
            or (says_igst and not re.search(r"\bCGST\b", question, re.IGNORECASE))
        ):
            doc = IGST_ACT
        else:
            doc = CGST_ACT
        out.append(Reference(doc, f"{number}{parts}"))
    for m in _SCHEDULE.finditer(question):
        out.append(Reference(CGST_ACT, f"Schedule {m.group('num')}"))
    return list(dict.fromkeys(out))


def _covers(section_path: str) -> list[str]:
    """The provisions a statute chunk covers: the part after the last ' > '."""
    return [c.strip() for c in section_path.rsplit(" > ", 1)[-1].split(",")]


def matches(reference: Reference, section_path: str) -> bool:
    """True when a chunk covers the provision or one of its parts ('16(2)' covers
    '16(2)(aa)'; '16' covers '16(4)'; '16(2)' does not cover '16(20)')."""
    ref = reference.ref
    for item in _covers(section_path):
        base = item.removesuffix(" amendment notes")
        if base == ref or base.startswith(ref + "("):
            return True
    return False


def lookup(conn, references: list[Reference]) -> list[RetrievedChunk]:
    """The statute chunks for each reference, in the law's order, at most 3 per reference."""
    found: list[RetrievedChunk] = []
    seen: set[int] = set()
    for ref in references:
        number = ref.ref.split("(")[0]
        heading = ref.ref if ref.ref.startswith("Schedule") else f"{PREFIX[ref.doc_id]}{number}"
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {RETRIEVED_COLUMNS} FROM chunks c JOIN documents d USING (doc_id) "
                "WHERE c.doc_id = %s AND c.section_path LIKE %s "
                "ORDER BY c.chunk_index",
                (ref.doc_id, f"% > {heading} %"),
            )
            rows = cur.fetchall()
        hits = [row_to_retrieved(r) for r in rows if matches(ref, r["section_path"])]
        notes = [h for h in hits if h.section_path.endswith("amendment notes")]
        body = [h for h in hits if h not in notes]
        for chunk in (body or notes)[:MAX_PER_REFERENCE]:
            if chunk.chunk_id not in seen:
                seen.add(chunk.chunk_id)
                found.append(chunk)
    return found
