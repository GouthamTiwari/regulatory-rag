"""Reciprocal Rank Fusion (RRF): merge several ranked lists into one (SPEC section 5).

Each chunk scores sum(1 / (k + rank)) over the lists it appears in, with rank counted
from 1. Only positions matter, never the raw scores, so a keyword score (ts_rank_cd) and
a cosine similarity can be combined without calibrating one against the other. k = 60
(from the original RRF paper) damps the advantage of being first in a single list, so a
chunk that both searches rank well tends to beat one that only one search loves.
"""

from dataclasses import fields, replace

from regrag.types import RetrievedChunk

# Per-stage fields that one list may have filled and another not (e.g. keyword_rank).
_STAGE_FIELDS = [f.name for f in fields(RetrievedChunk) if f.name.endswith(("_rank", "_score"))]


def _merge(first: RetrievedChunk, other: RetrievedChunk) -> RetrievedChunk:
    """Keep every rank/score either list knew about (useful for logs and debugging)."""
    updates = {
        name: getattr(other, name)
        for name in _STAGE_FIELDS
        if getattr(first, name) is None and getattr(other, name) is not None
    }
    return replace(first, **updates) if updates else first


def rrf_fuse(
    lists: list[list[RetrievedChunk]], k: int = 60, top_k: int = 30
) -> list[RetrievedChunk]:
    """Fuse ranked lists. Inputs are not modified; results carry `fused_score`."""
    scores: dict[int, float] = {}
    chunks: dict[int, RetrievedChunk] = {}
    for ranked in lists:
        for rank, chunk in enumerate(ranked, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            seen = chunks.get(chunk.chunk_id)
            chunks[chunk.chunk_id] = chunk if seen is None else _merge(seen, chunk)
    # Highest score first; ties broken by chunk_id so the order is always the same.
    order = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [replace(chunks[cid], fused_score=scores[cid]) for cid in order[:top_k]]
