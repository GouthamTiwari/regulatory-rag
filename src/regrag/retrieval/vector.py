"""Meaning-based search with pgvector (SPEC section 5, "Vector retrieve").

The question is embedded once, then the HNSW index finds the chunks whose vectors are
closest by cosine distance. `vector_score = 1 - distance`, so 1.0 means identical meaning.
"""

import psycopg
from psycopg.rows import dict_row

from regrag.db.repository import RETRIEVED_COLUMNS, row_to_retrieved
from regrag.interfaces import Embedder
from regrag.types import RetrievedChunk, Route

_SQL = f"""
    SELECT {RETRIEVED_COLUMNS}, c.embedding <=> %(vec)s::vector AS distance
    FROM chunks c JOIN documents d USING (doc_id)
    WHERE c.embedding IS NOT NULL AND (%(route)s = 'both' OR d.corpus = %(route)s)
    ORDER BY c.embedding <=> %(vec)s::vector, c.chunk_id
    LIMIT %(limit)s
"""


class VectorRetriever:
    """Implements the Retriever protocol. `last_embed_tokens` feeds the cost log."""

    def __init__(self, conn: psycopg.Connection, embedder: Embedder, *, ef_search: int = 100):
        self.conn = conn
        self.embedder = embedder
        self.ef_search = ef_search
        self.last_embed_tokens = 0

    def retrieve(self, query: str, route: Route, top_k: int) -> list[RetrievedChunk]:
        self.last_embed_tokens = 0
        if not query.strip():
            return []
        embedded = self.embedder.embed([query])
        self.last_embed_tokens = embedded.input_tokens
        vector = embedded.vectors[0]
        with self.conn.transaction(), self.conn.cursor(row_factory=dict_row) as cur:
            # Settings for this transaction only. ef_search above the default 40, and
            # iterative scans, so a corpus filter (route) still returns top_k rows instead
            # of filtering an already-short candidate list. set_config is used because
            # SET does not accept query parameters.
            cur.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(self.ef_search),))
            cur.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)")
            cur.execute(_SQL, {"vec": vector, "route": route, "limit": top_k})
            rows = cur.fetchall()
        results = []
        for rank, row in enumerate(rows, start=1):
            chunk = row_to_retrieved(row)
            chunk.vector_score = 1.0 - float(row["distance"])
            chunk.vector_rank = rank
            results.append(chunk)
        return results
