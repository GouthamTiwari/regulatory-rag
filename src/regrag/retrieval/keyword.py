"""Keyword search with Postgres full-text search: the "BM25-like" leg (SPEC sections 5, 6.4).

`websearch_to_tsquery` turns the question into search terms (it never raises on odd
punctuation or quotes), the GIN index on `chunks.tsv` finds matching chunks, and
`ts_rank_cd` ranks them. Honest label: this is Postgres's ranking, similar in spirit to
BM25 but not the exact formula (SPEC decision 5).
"""

import re

import psycopg
from psycopg.rows import dict_row

from regrag.db.repository import RETRIEVED_COLUMNS, row_to_retrieved
from regrag.types import RetrievedChunk, Route

# Fewer strict (all-words) hits than this, and we also search with any-word matching.
MIN_STRICT_HITS = 5

_SQL = f"""
    SELECT {RETRIEVED_COLUMNS}, ts_rank_cd(c.tsv, q) AS score
    FROM chunks c
    JOIN documents d USING (doc_id),
         websearch_to_tsquery('english', %(query)s) AS q
    WHERE c.tsv @@ q AND (%(route)s = 'both' OR d.corpus = %(route)s)
    ORDER BY score DESC, c.chunk_id
    LIMIT %(limit)s
"""


def any_word_query(question: str) -> str:
    """'ITC on demo vehicles?' -> 'ITC or on or demo or vehicles' (websearch syntax).

    Why: a natural question rarely contains every word of the paragraph that answers it,
    so a strict all-words match often finds nothing. Stop words like "on" are dropped by
    Postgres itself."""
    return " or ".join(re.findall(r"[A-Za-z0-9]+", question))


class KeywordRetriever:
    """Implements the Retriever protocol over Postgres full-text search."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def _search(self, query: str, route: Route, limit: int) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SQL, {"query": query, "route": route, "limit": limit})
            rows = cur.fetchall()
        chunks = []
        for row in rows:
            chunk = row_to_retrieved(row)
            chunk.keyword_score = float(row["score"])
            chunks.append(chunk)
        return chunks

    def retrieve(self, query: str, route: Route, top_k: int) -> list[RetrievedChunk]:
        results = self._search(query, route, top_k)
        if len(results) < MIN_STRICT_HITS:
            seen = {c.chunk_id for c in results}
            for chunk in self._search(any_word_query(query), route, top_k):
                if chunk.chunk_id not in seen and len(results) < top_k:
                    results.append(chunk)
                    seen.add(chunk.chunk_id)
        for rank, chunk in enumerate(results, start=1):
            chunk.keyword_rank = rank
        return results
