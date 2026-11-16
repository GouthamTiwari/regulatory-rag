"""Supersession filter and flags at question time (SPEC section 5).

Given the reranked chunks, their documents and the links between documents:
- a chunk from a superseded or withdrawn document is kept (the user may be asking about
  the old rule on purpose) but marked, at most one such chunk per old document is kept, and
  the best chunk of the newer document is brought in;
- a chunk from a document that was later amended, clarified or corrected is kept, with a
  note naming the later document;
- chunks from active documents pass through unchanged.

Only *reviewed* links are used (the hand-curated file). Why: a wrong "superseded" warning
misleads users, and automatically extracted links are not trusted until a human checks
them (SPEC 3.4). Database lookups are passed in, so this module is pure logic.
"""

from collections.abc import Callable
from dataclasses import replace

from regrag.types import Relation, RetrievedChunk

_REPLACES = {"supersedes", "withdraws"}
_CHANGES = {"amends": "amended", "clarifies": "clarified", "corrects": "corrected"}


def _name(doc_id: str, documents: dict[str, dict]) -> str:
    doc = documents.get(doc_id, {})
    return doc.get("reference_no") or doc.get("title") or doc_id


def apply_supersession(
    chunks: list[RetrievedChunk],
    documents: dict[str, dict],
    relations: list[Relation],
    fetch_replacement: Callable[[str, RetrievedChunk], list[RetrievedChunk]],
) -> tuple[list[RetrievedChunk], list[str]]:
    """Return (chunks to show, notes). `documents` maps doc_id to at least
    {"status", "reference_no", "title"}; `fetch_replacement(newer_doc_id, old_chunk)`
    returns the newer document's chunks covering the same rule as `old_chunk` (best
    first), or an empty list."""
    reviewed = [r for r in relations if r.reviewed]
    out: list[RetrievedChunk] = []
    notes: list[str] = []
    seen_old: set[str] = set()
    present = {c.chunk_id for c in chunks}

    def note(text: str) -> None:
        if text not in notes:
            notes.append(text)

    for chunk in chunks:
        status = documents.get(chunk.doc_id, {}).get("status", "active")
        if status in ("superseded", "withdrawn"):
            if chunk.doc_id in seen_old:
                continue  # at most one chunk of an outdated document
            seen_old.add(chunk.doc_id)
            newer = next(
                (r for r in reviewed if r.to_doc_id == chunk.doc_id and r.relation in _REPLACES),
                None,
            )
            old_name = _name(chunk.doc_id, documents)
            if newer is not None:
                new_name = _name(newer.from_doc_id, documents)
                out.append(replace(chunk, supersession_mark=f"SUPERSEDED BY {new_name}"))
                note(f"{old_name} was {status} by {new_name}; the current rule is in {new_name}.")
                for replacement in fetch_replacement(newer.from_doc_id, chunk):
                    if replacement.chunk_id not in present:
                        out.append(replacement)
                        present.add(replacement.chunk_id)
            else:
                out.append(replace(chunk, supersession_mark=status.upper()))
                note(f"{old_name} is marked {status}; check for a newer document.")
            continue

        changes = [r for r in reviewed if r.to_doc_id == chunk.doc_id and r.relation in _CHANGES]
        for change in changes:
            note(
                f"{_name(chunk.doc_id, documents)} was {_CHANGES[change.relation]} by "
                f"{_name(change.from_doc_id, documents)}."
            )
        out.append(chunk)
    return out, notes
