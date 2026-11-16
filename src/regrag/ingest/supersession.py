"""Find "this document changes that one" links in the text (SPEC section 3.4, source 2).

Two sources inside a document:
1. Sentences with an operative phrase and a document reference, for example
   "Circular No. 195/07/2023-GST stands withdrawn" or "in supersession of RBI/2019-20/88".
2. Tables listing the circulars a Master Direction repeals or consolidates ("List of
   circulars repealed with the issuance of this Master Direction").

Precision matters more than recall here: a wrong "superseded" flag misleads users. So the
patterns require the *operative* form ("stand repealed", "is hereby withdrawn"), never the
boilerplate that fills real directions ("as amended from time to time", "Notwithstanding
such repeal ..."), and every relation keeps its sentence as evidence. Extracted relations
are never trusted automatically: they are stored with reviewed=False (SPEC 3.4).
"""

import re

from regrag.types import Chunk, Relation, RelationType

# --- Document references ---------------------------------------------------------------------

# GST circular: "195/07/2023-GST", "Circular No. 195/07/2023 - GST", "195/7/2023–GST".
_GST_REF = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,2})\s*/\s*(20\d{2})\s*[-–]+\s*GST\b", re.I)
# RBI circular reference: "RBI/2025-26/79", "RBI/DOR/2025-26/169", "RBI/FIDD/2020-21/72".
_RBI_REF = re.compile(r"\bRBI\s*/\s*(?:[A-Za-z]{2,8}\s*/\s*)?\d{4}\s*-\s*\d{2}\s*/\s*\d{1,4}\b")
# Department reference: "DPSS.CO.PD.No.1810/02.14.008 /2019-20",
# "DOS.CO.FMG.SEC.No.5/23.04.001/2024-25", "DPSS.CO.PD No.1343/02.14.003/2019-20".
_DEPT_REF = re.compile(
    r"\b[A-Z]{2,}(?:\.[A-Z0-9]{2,}){1,6}\.?\s?No\.\s?[A-Z]?\d+\s?/\s?[0-9][0-9.\-]*\s?/\s?\d{4}-\d{2,4}\b"
)
# A reference that only says *how* something was communicated is not a target:
# "stand repealed, as communicated vide circular DOR.XYZ.No.1/..." (that is the repeal notice).
_VIDE_BEFORE = re.compile(
    # Also history, not targets: "(as amended by Circular No. X)",
    # "which was earlier modified vide Para 5 of Circular No. X".
    r"\b(?:vide|as\s+amended\s+by|amended\s+by|modified\s+by)\s+"
    r"(?:para(?:graph)?\s+[\d.]+\s+of\s+)?(?:the\s+)?(?:rbi\s+)?(?:(?:circular|notification)\s+)?"
    r"(?:no\.?\s*)?$",
    re.I,
)


def normalise_ref(text: str) -> str:
    """One spelling per reference, so different spellings compare equal.

    "Circular No. 195/07/2023 - GST", "195/7/2023-GST" -> "195/07/2023-GST";
    "RBI / 2025-26 / 79" -> "RBI/2025-26/79"; department references lose their spaces.
    """
    m = _GST_REF.search(text)
    if m:
        number, serial, year = m.groups()
        return f"{int(number)}/{int(serial):02d}/{year}-GST"
    m = _RBI_REF.search(text) or _DEPT_REF.search(text)
    if m:
        return re.sub(r"\s+", "", m.group(0)).upper()
    return re.sub(r"\s+", " ", text).strip(" .,;:'\"").lower()


def find_refs(sentence: str) -> list[str]:
    """Normalised references in a sentence, in order, skipping "vide ..." mentions."""
    found: list[tuple[int, str]] = []
    for pattern in (_GST_REF, _RBI_REF, _DEPT_REF):
        for m in pattern.finditer(sentence):
            if _VIDE_BEFORE.search(sentence[: m.start()]):
                continue
            found.append((m.start(), normalise_ref(m.group(0))))
    refs: list[str] = []
    for _, ref in sorted(found):
        if ref not in refs:
            refs.append(ref)
    return refs


# --- Operative phrases -----------------------------------------------------------------------

_BE = r"(?:stands?|is|are|shall\s+stand|has\s+been|have\s+been|hereby)\s+(?:hereby\s+)?"
_TRIGGERS: list[tuple[RelationType, re.Pattern[str]]] = [
    (
        "withdraws",
        re.compile(rf"\b{_BE}withdrawn\b|\bwithdrawn\s+ab\s+initio\b|\brescinded\b", re.I),
    ),
    (
        "supersedes",
        re.compile(
            rf"\bin\s+supersession\s+of\b|\b(?:hereby\s+)?supersedes?\b|\b{_BE}superseded\b"
            rf"|\b{_BE}repealed\b|\bhereby\s+repeals?\b",
            re.I,
        ),
    ),
    ("corrects", re.compile(r"\bcorrigendum\b", re.I)),
    (
        "amends",
        re.compile(
            rf"\bin\s+partial\s+modification\s+of\b|\b{_BE}(?:modified|amended|substituted)\b"
            r"|\bamended\s+as\s+(?:under|follows)\b|\bamendment\s+to\s+(?:the\s+)?(?:circular|master\s+direction|direction)",
            re.I,
        ),
    ),
    ("clarifies", re.compile(r"\bin\s+furtherance\s+(?:of|to)\b", re.I)),
]
# Boilerplate that contains trigger words but changes nothing.
_BOILERPLATE = re.compile(
    r"notwithstanding\s+such\s+repeal|the\s+repeal\s+of\s+these|shall\s+not\s+in\s+any\s+way"
    r"|(?:continue\s+to\s+)?remain\s+repealed|repealed\s+prior\s+to",
    re.I,
)
_NEGATION = re.compile(r"\b(?:not|no|neither|nor|never|without)\b[^.;]{0,30}$", re.I)
# A repeal sentence with no specific reference still matters for RBI's 2025 directions:
# "the existing Directions, instructions and guidelines ... stand repealed".
_GENERIC_TARGET = re.compile(
    r"\b(?:existing|earlier|previous|extant)\b[^.;]{0,60}\b(?:directions?|instructions?|guidelines?|circulars?)\b",
    re.I,
)
GENERIC_REF = "earlier instructions (not named; see evidence)"

# Tables that list what a Master Direction repeals or consolidates.
_LIST_TABLE = re.compile(
    r"circulars?\s+(?:repealed|consolidated|superseded|withdrawn)|list\s+of\s+circulars", re.I
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.;])\s+(?=[A-Z(\d])")
# A full stop after these is not the end of a sentence: "Circular No. 31/05/2018-GST".
_ABBREVIATION_END = re.compile(
    r"\b(?:no|nos|rs|viz|i\.e|e\.g|sl|s|dt|para|paras|cir|ref|sec|art|vol|vs|etc|[a-z])\.$", re.I
)


def sentences(text: str) -> list[str]:
    """Split text into sentences without breaking after "No.", "Rs.", "i.e." and the like."""
    out: list[str] = []
    for piece in _SENTENCE_SPLIT.split(text):
        if out and _ABBREVIATION_END.search(out[-1]):
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return out


def own_refs_for(doc_id: str, reference_no: str = "") -> set[str]:
    """References that point at the document itself (never a relation target).

    A corrigendum has no number of its own: the circular it names ("Corrigendum to
    237/31/2024-GST") is its *target*, so nothing counts as "itself".
    """
    if doc_id.endswith("-corr"):
        return set()
    refs = {normalise_ref(reference_no)} if reference_no else set()
    m = re.fullmatch(r"gst-(\d+)-(\d+)-(\d{4})", doc_id)
    if m:
        refs.add(normalise_ref(f"{m[1]}/{m[2]}/{m[3]}-GST"))
    return refs


def _relation_in(sentence: str) -> RelationType | None:
    """The relation named by the *earliest* operative phrase in the sentence.

    Why earliest: long sentences quote replacement text, and a later word in the quote
    (say "corrigendum") must not override the operative "is substituted" before it.
    """
    if _BOILERPLATE.search(sentence):
        return None
    best: tuple[int, RelationType] | None = None
    for relation, pattern in _TRIGGERS:
        for m in pattern.finditer(sentence):
            if _NEGATION.search(sentence[: m.start()]):
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), relation)
            break
    return best[1] if best else None


def extract_relations(doc_id: str, chunks: list[Chunk], reference_no: str = "") -> list[Relation]:
    """All relations found in one document's chunks, de-duplicated, in reading order."""
    own = own_refs_for(doc_id, reference_no)
    seen: set[tuple[str, str]] = set()
    relations: list[Relation] = []

    def add(relation: RelationType, ref: str, evidence: str, note: str = "") -> None:
        if ref in own or (relation, ref) in seen:
            return
        seen.add((relation, ref))
        relations.append(
            Relation(
                from_doc_id=doc_id,
                relation=relation,
                to_doc_ref=ref,
                scope_note=note,
                evidence=re.sub(r"\s+", " ", evidence).strip()[:500],
                source="extracted",
                reviewed=False,
            )
        )

    for chunk in chunks:
        if chunk.content_type == "table" and _LIST_TABLE.search(
            f"{chunk.section_path} {chunk.content[:300]}"
        ):
            for row in chunk.content.splitlines()[2:]:
                for ref in find_refs(row):
                    add("supersedes", ref, row, "listed as repealed/consolidated")
            continue
        text = chunk.content.replace("\n", " ")
        for sentence in sentences(text):
            relation = _relation_in(sentence)
            if relation is None:
                continue
            refs = [r for r in find_refs(sentence) if r not in own]
            if refs:
                for ref in refs:
                    add(relation, ref, sentence)
            elif relation == "supersedes" and _GENERIC_TARGET.search(sentence):
                add(relation, GENERIC_REF, sentence, "target not named in the sentence")
    return relations
