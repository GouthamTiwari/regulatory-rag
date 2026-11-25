"""A small library API for other projects (task 36). Stable from v1.1.0.

    from regrag import api
    hits = api.search("invoice missing from GSTR-2B, can ITC be claimed?", k=4)
    result = api.answer("What does rule 36(4) say?")

- ``search``: retrieval only. Hybrid keyword + vector search with reciprocal-rank fusion and
  the reranker; provisions the query names ("rule 36(4)") come first. No LLM is called; the
  cost is one embedding (and one rerank) call, a fraction of a cent.
- ``answer``: the full pipeline (route, retrieve, rerank, supersession, cited answer,
  validation, abstain). Returns the same ``QueryResult`` the CLI and the web page use.
- ``corpus_version``: changes whenever any stored document changes, so callers can key
  their caches on it.

Needs the project's database running (``docker compose up -d``) and AWS credentials in
``.env``, like the CLI.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from functools import lru_cache

from psycopg.rows import dict_row

from regrag.config import Settings
from regrag.ingest.statute import section_url
from regrag.query.pipeline import Parts, answer_question, build_pipeline
from regrag.query.references import lookup as lookup_references
from regrag.query.references import parse_references
from regrag.types import PipelineConfig, QueryResult, RetrievedChunk

Corpus = str  # "gst", "rbi" or "both"
STATUTES = {"gst-cgst-act-2017", "gst-cgst-rules-2017", "gst-igst-act-2017"}


@dataclass(frozen=True)
class Snippet:
    """One citable passage."""

    snippet_id: str  # "<doc_id>#<chunk_index>": stable while the document is unchanged
    doc_id: str
    title: str
    url: str  # the official page: the section page for the bare law, else the document
    section: str  # "16(2)(aa)", "Para 4", ...
    text: str
    checked_on: dt.date  # the document's "updated as on" date, else its publish date
    score: float | None  # rerank score (1.0 for a provision the query names)


@lru_cache(maxsize=1)
def _parts() -> Parts:
    return build_pipeline(PipelineConfig(name="hybrid_rerank"))


def _details(conn, chunks: list[RetrievedChunk]) -> dict[int, tuple[int, dt.date]]:
    """chunk_id -> (chunk_index, document date) for the given chunks."""
    if not chunks:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT c.chunk_id, c.chunk_index, COALESCE(d.updated_as_on, d.publish_date) AS day "
            "FROM chunks c JOIN documents d USING (doc_id) WHERE c.chunk_id = ANY(%s)",
            ([c.chunk_id for c in chunks],),
        )
        return {r["chunk_id"]: (r["chunk_index"], r["day"]) for r in cur.fetchall()}


def to_snippets(conn, chunks: list[RetrievedChunk]) -> list[Snippet]:
    details = _details(conn, chunks)
    out = []
    for c in chunks:
        index, day = details[c.chunk_id]
        url = section_url(c.doc_id, c.section_path, c.source_url)
        out.append(
            Snippet(
                snippet_id=f"{c.doc_id}#{index}",
                doc_id=c.doc_id,
                title=c.title,
                url=url,
                section=c.section_no or c.section_path,
                text=c.content,
                checked_on=day,
                score=c.rerank_score,
            )
        )
    return out


def search(query: str, k: int = 4, corpus: Corpus = "gst", parts: Parts | None = None):
    """The ``k`` best passages for ``query`` from ``corpus`` ("gst", "rbi" or "both")."""
    if corpus not in ("gst", "rbi", "both"):
        raise ValueError("corpus must be 'gst', 'rbi' or 'both'")
    parts = parts or _parts()
    s = parts.settings
    retrieved = parts.retriever.retrieve(query, corpus, s.fused_top_k)
    ranked = parts.reranker.rerank(query, retrieved, max(k, s.rerank_top_n))
    pinned: list[RetrievedChunk] = []
    references = parse_references(query) if corpus != "rbi" else []
    if references:
        lookup = parts.reference_lookup or (lambda refs: lookup_references(parts.conn, refs))
        pinned = lookup(references)
        for c in pinned:
            c.rerank_score = 1.0
    seen = {c.chunk_id for c in pinned}
    best = (pinned + [c for c in ranked if c.chunk_id not in seen])[:k]
    return to_snippets(parts.conn, best)


def answer(question: str, parts: Parts | None = None) -> QueryResult:
    """A cited answer, or a refusal when the evidence is weak (``result.abstained``)."""
    return answer_question(question, parts=parts or _parts())


def corpus_version(settings: Settings | None = None, conn=None) -> str:
    """A short hash over every stored document's id, hash and embedding model."""
    if conn is None:
        conn = (
            _parts().conn
            if settings is None
            else build_pipeline(PipelineConfig(name="hybrid_rerank", settings=settings)).conn
        )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT d.doc_id, COALESCE(d.sha256, ''), "
            "COALESCE((SELECT MIN(embedding_model) FROM chunks c WHERE c.doc_id = d.doc_id), '') "
            "FROM documents d ORDER BY d.doc_id"
        )
        rows = cur.fetchall()
    h = hashlib.sha256()
    for row in rows:
        h.update("|".join(row).encode() + b"\n")
    return h.hexdigest()[:12]


__all__ = ["Snippet", "answer", "corpus_version", "search"]
