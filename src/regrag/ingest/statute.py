"""The bare law: CGST Act, CGST Rules and IGST Act from the official CBIC tax portal (task 33).

Why not one consolidated file: the portal's consolidated Act and Rules pages were last updated
in September and December 2022 and miss later amendments (for example s.16(5) and (6), added in
2024). Its per-section "active" pages are current. The portal lists them through the same
public JSON endpoints its own pages use; we read that list, then fetch each section page once,
politely (``download_delay_s`` between requests), and keep the text.

Each statute is ONE document in the manifest (``doc_type`` ``act`` or ``rules``; ``pdf_url`` is
the portal's section-list endpoint). It is saved as ``data/raw/<doc_id>.json`` with every
section's number, title, official URL and plain text. The file's sha256 plays the role of a
PDF hash: unchanged law, nothing re-embedded.

Parsing makes one ``ParsedPage`` per section (``page_no`` = position in the statute, not a
printed page). Chunking is section-aware: one chunk per sub-section or clause, with a citable
label such as ``16(2)(aa)``; very short clauses are merged with their neighbours inside the
same sub-section, and long ones are split with overlap.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import truststore

from regrag.config import Settings, get_settings
from regrag.ingest.chunk import estimate_tokens
from regrag.ingest.download import RAW_DIR, USER_AGENT
from regrag.ingest.manifest import is_allowed_host, load_manifest
from regrag.types import Chunk, ManifestRow, ParsedDocument, ParsedPage

PORTAL = "https://taxinformation.cbic.gov.in"
STATUTE_TYPES = {"act", "rules"}
# doc_id -> (label used in citations, citation prefix for a section)
LABELS: dict[str, tuple[str, str]] = {
    "gst-cgst-act-2017": ("CGST Act", "s."),
    "gst-cgst-rules-2017": ("CGST Rules", "r."),
    "gst-igst-act-2017": ("IGST Act", "s."),
}
PARA = "\n\n"  # paragraph separator in the saved section text
SECTION_NO = re.compile(r"^(Section|Rule|Schedule)\s+([0-9A-Z]+)$", re.I)


class StatuteError(RuntimeError):
    pass


def is_statute(row: ManifestRow) -> bool:
    return row.doc_type in STATUTE_TYPES


def raw_path(row: ManifestRow, raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / f"{row.doc_id}.json"


# --- HTML to text -----------------------------------------------------------------------------

_BLOCK = re.compile(r"</?(p|div|br|tr|li|h[1-6]|table|ul|ol)\b[^>]*>", re.I)
_SPACED_MARKER = re.compile(r"\(\s*(\w{1,5})\s*\)")


def tidy_markers(text: str) -> str:
    """'( 1 )' and '( iv )' as printed on some pages become '(1)' and '(iv)'."""
    return _SPACED_MARKER.sub(r"(\1)", text)


def html_to_text(raw: str) -> str:
    """Plain text with one blank line between paragraphs (the portal puts each clause marker
    such as ``(1)`` or ``(aa)`` at the start of a paragraph)."""
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    text = _BLOCK.sub("\n\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    paras = []
    for para in re.split(r"\n\s*\n", text):
        joined = tidy_markers(" ".join(para.split()))
        if joined:
            paras.append(joined)
    out: list[str] = []
    for para in paras:
        # A lone marker "(1)" or "1[(aa)" belongs to the paragraph after it.
        if out and re.fullmatch(r"(\d+\[)?\(\w{1,4}\)", out[-1]):
            out[-1] = f"{out[-1]} {para}"
        else:
            out.append(para)
    return "\n\n".join(out)


# --- fetching ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionEntry:
    number: str  # "16", "37A", "Schedule I"
    title: str
    url: str


def list_sections(row: ManifestRow, client: httpx.Client) -> list[SectionEntry]:
    """The active sections of one statute, in the portal's order."""
    resp = client.get(row.pdf_url)
    resp.raise_for_status()
    entries = []
    for item in resp.json():
        if item.get("isActive") != "Y" or not item.get("contentFilePath"):
            continue
        m = SECTION_NO.match((item.get("sectionNo") or "").strip())
        if not m:
            continue  # headers and chapter introductions carry no law text of their own
        kind, num = m.group(1).lower(), m.group(2).upper()
        number = f"Schedule {num}" if kind == "schedule" else num
        path = item["contentFilePath"].replace("\\", "/")
        entries.append(
            SectionEntry(
                number, (item.get("sectionName") or "").strip(), f"{PORTAL}/content/html/{path}"
            )
        )
    if not entries:
        raise StatuteError(f"{row.doc_id}: the section list was empty")
    return entries


def fetch_statute(
    row: ManifestRow,
    client: httpx.Client,
    settings: Settings,
    raw_dir: Path = RAW_DIR,
    sleep=time.sleep,
    progress=None,
) -> Path:
    """Download every section of ``row`` and write ``data/raw/<doc_id>.json``."""
    if not is_allowed_host(row.pdf_url, settings.allowed_download_hosts):
        raise StatuteError(f"{row.doc_id}: section list is not on an official host")
    entries = list_sections(row, client)
    sections = []
    for i, entry in enumerate(entries, start=1):
        if not is_allowed_host(entry.url, settings.allowed_download_hosts):
            raise StatuteError(f"{entry.url} is not on an official host")
        for attempt in range(settings.download_retries + 1):
            try:
                resp = client.get(entry.url)
                resp.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == settings.download_retries:
                    raise
                sleep(2.0 * (attempt + 1))
        text = html_to_text(resp.text)
        if len(text) < 20:
            raise StatuteError(f"{entry.url}: page has no text")
        sections.append(
            {"number": entry.number, "title": entry.title, "url": entry.url, "text": text}
        )
        if progress:
            progress(i, len(entries), entry.number)
        sleep(settings.download_delay_s)
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_path(row, raw_dir)
    data = {"doc_id": row.doc_id, "section_list": row.pdf_url, "sections": sections}
    partial = target.with_suffix(".json.part")
    with open(partial, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    partial.replace(target)
    return target


# --- parsing and chunking ---------------------------------------------------------------------


def load_statute(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("sections"):
        raise StatuteError(f"{path}: no sections")
    return data


def parse_statute(path: Path, doc_id: str) -> ParsedDocument:
    """One page per section, so a citation's page number is the section's position."""
    data = load_statute(path)
    pages = []
    for i, s in enumerate(data["sections"], start=1):
        pages.append(ParsedPage(page_no=i, text=s["text"]))
    return ParsedDocument(doc_id=doc_id, pages=pages)


# An optional amendment-note number in front, written "3[" or "3 [" on the portal.
_MARKER = re.compile(r"^(?:\d+\s*\[\s*)?\((\d+[A-Z]?|[a-z]{1,3})\)\s*")
_ROMAN = re.compile(r"^(?=[ivx])x{0,3}(ix|iv|v?i{0,3})a?$")  # i .. xxxix, plus "iia"
_FOOTNOTE = re.compile(
    r"^\d+\.\s*(Inserted|Substituted|Omitted|Added|Renumbered|Words|Clause|Sub-section|"
    r"The words|Proviso|Explanation|Rule|Section|Brought|Vide|Amended|For the words|"
    r"Re-numbered|Ins\.|Subs\.)",
    re.I,
)


@dataclass
class _Unit:
    label: str  # "", "(1)", "(2)(aa)", "(xiv)"
    text: str
    sub: str = ""  # the numbered sub-section the unit belongs to ("" if none)
    footnotes: bool = False


def _is_roman(token: str, last_letter: str) -> bool:
    """A roman numeral, unless it is simply the next letter (clause (i) after clause (h))."""
    if not _ROMAN.match(token):
        return False
    return not (last_letter and len(token) == 1 and ord(token) == ord(last_letter) + 1)


def _units(text: str) -> list[_Unit]:
    """Split a section's text into sub-section / clause units, following the law's own
    numbering. Provisos, explanations and roman items inside a lettered clause stay with that
    clause; a roman list at the top level (as in IGST s.20) is a list of clauses itself."""
    units: list[_Unit] = []
    sub, clause, last_letter, clause_is_roman = "", "", "", False
    in_notes = False
    for para in tidy_markers(text).split(PARA):
        # The portal puts amendment notes at the end of a page, and a note can quote the
        # OLD wording of a provision ('Substituted ... for "(4) Input tax credit ..."').
        # So once the notes start, every later paragraph is part of them, not law text.
        if in_notes or _FOOTNOTE.match(para):
            in_notes = True
            if units and units[-1].footnotes:
                units[-1].text += PARA + para
            else:
                units.append(_Unit("amendment notes", para, footnotes=True))
            continue
        m = _MARKER.match(para)
        if m:
            token = m.group(1)
            if token[0].isdigit():
                sub, clause, last_letter, clause_is_roman = token, "", "", False
            elif _is_roman(token, last_letter) and clause and not clause_is_roman:
                pass  # a roman item inside the current lettered clause
            else:
                clause_is_roman = _is_roman(token, last_letter)
                clause = token
                if len(token) == 1 and not clause_is_roman:
                    last_letter = token
        label = (f"({sub})" if sub else "") + (f"({clause})" if clause else "")
        if units and not units[-1].footnotes and units[-1].label == label:
            units[-1].text += PARA + para
        else:
            units.append(_Unit(label, para, sub=sub))
    return units


def chunk_statute(path: Path, row: ManifestRow, settings: Settings) -> list[Chunk]:
    data = load_statute(path)
    act, prefix = LABELS.get(row.doc_id, (row.title, "s."))
    min_tokens = 60
    chunks: list[Chunk] = []

    def emit(number: str, title: str, page: int, labels: list[str], body: str) -> None:
        notes = labels == ["(amendment notes)"]
        first = next((lab for lab in labels if lab), "")
        is_schedule = number.startswith("Schedule")
        cite = number if (is_schedule or notes) else f"{number}{first}"
        if notes:
            covers = f"{number} amendment notes"
        else:
            covers = ", ".join(f"{number}{lab}" for lab in labels if lab) or number
        heading = f"{act} {'' if is_schedule else prefix}{cite}".replace("  ", " ")
        section_path = f"{act} > {'' if is_schedule else prefix}{number} {title} > {covers}"
        if notes:
            # Amendment notes often quote the OLD wording of a provision. Say so in the text
            # the model reads, so repealed words are never presented as the current law.
            cite = f"{number} (amendment history)"
            heading = f"{heading} amendment history"
            title = f"{title}; HISTORY ONLY: any wording quoted below is earlier text, NOT in force"
        for piece in _split(body, settings):
            chunks.append(
                Chunk(
                    doc_id=row.doc_id,
                    chunk_index=len(chunks),
                    section_no=cite,
                    section_path=section_path,
                    page_start=page,
                    page_end=page,
                    content_type="text",
                    content=f"{heading} ({title})\n\n{piece}",
                    token_count=estimate_tokens(piece),
                )
            )

    for page, s in enumerate(data["sections"], start=1):
        for labels, body in _groups(_units(s["text"]), settings, min_tokens):
            emit(s["number"], s["title"], page, labels, body)
    return chunks


def _groups(units: list[_Unit], settings: Settings, min_tokens: int) -> list[tuple[list[str], str]]:
    """Merge short clauses within one sub-section; amendment notes always stand alone."""
    groups: list[tuple[list[str], str]] = []
    labels: list[str] = []
    texts: list[str] = []
    group_sub: str | None = None

    def close() -> None:
        if texts:
            groups.append((list(labels), PARA.join(texts)))
        labels.clear()
        texts.clear()

    for unit in units:
        if unit.footnotes:
            close()
            groups.append((["(amendment notes)"], unit.text))
            group_sub = None
            continue
        sub = unit.sub
        current = estimate_tokens(PARA.join(texts)) if texts else 0
        heading_only = labels == [""] and current < min_tokens  # "Section 19. Title.-"
        if (
            texts
            and not heading_only
            and (
                sub != group_sub
                or current >= min_tokens
                or current + estimate_tokens(unit.text) > settings.chunk_target_tokens
            )
        ):
            close()
        group_sub = sub
        labels.append(unit.label)
        texts.append(unit.text)
    close()
    return groups


def _split(text: str, settings: Settings) -> list[str]:
    """Split a long unit into overlapping windows of words; short units stay whole."""
    if estimate_tokens(text) <= settings.chunk_max_tokens:
        return [text]
    words = text.split()
    ratio = max(1.0, estimate_tokens(text) / max(1, len(words)))
    size = int(settings.chunk_target_tokens / ratio)
    overlap = int(settings.chunk_overlap_tokens / ratio)
    out, start = [], 0
    while start < len(words):
        out.append(" ".join(words[start : start + size]))
        if start + size >= len(words):
            break
        start += size - overlap
    return out


def make_client(settings: Settings) -> httpx.Client:
    """HTTPS client that verifies certificates against the operating system's trust store.

    Why: the portal serves an incomplete certificate chain. Windows (and macOS) fetch the
    missing intermediate certificate themselves, Python's bundled list does not. Verification
    stays ON; we only change which trust store does it (the ``truststore`` package).
    """
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=settings.download_timeout_s,
        follow_redirects=False,
        verify=ctx,
    )


# --- command line -----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch the bare GST law from the CBIC portal")
    parser.add_argument("--only", action="append", help="only this doc_id (repeatable)")
    parser.add_argument("--force", action="store_true", help="fetch again even if saved")
    args = parser.parse_args(argv)
    settings = get_settings()
    rows = [r for r in load_manifest(settings=settings).rows if is_statute(r)]
    if args.only:
        rows = [r for r in rows if r.doc_id in args.only]
    client = make_client(settings)
    for row in rows:
        if raw_path(row).exists() and not args.force:
            print(f"{row.doc_id}: already saved ({raw_path(row).name}); use --force to refresh")
            continue
        print(f"{row.doc_id}: fetching the section list ...", flush=True)

        def show(i: int, n: int, number: str) -> None:
            if i == n or i % 25 == 0:
                print(f"  {i}/{n} (last: {number})", flush=True)

        path = fetch_statute(row, client, settings, progress=show)
        data = load_statute(path)
        print(f"{row.doc_id}: {len(data['sections'])} sections -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# --- citation links ---------------------------------------------------------------------------

_URL_CACHE: dict[str, dict[str, str]] = {}


def section_number(section_path: str) -> str:
    """'CGST Rules > r.36 Documentary ... > 36(4)' -> '36'; schedules -> 'Schedule II'."""
    heading = section_path.split(" > ")[1] if " > " in section_path else ""
    if heading.startswith("Schedule"):
        return " ".join(heading.split()[:2])
    return heading.split(" ")[0].removeprefix("s.").removeprefix("r.")


def section_url(doc_id: str, section_path: str, default: str, raw_dir: Path = RAW_DIR) -> str:
    """The official page of the section a statute chunk comes from (``default`` if unknown).

    Read from the saved statute file, which holds every section's portal URL."""
    if doc_id not in LABELS:
        return default
    if doc_id not in _URL_CACHE:
        path = raw_dir / f"{doc_id}.json"
        sections = json.loads(path.read_text("utf-8"))["sections"] if path.exists() else []
        _URL_CACHE[doc_id] = {s["number"]: s["url"] for s in sections}
    return _URL_CACHE[doc_id].get(section_number(section_path), default)
