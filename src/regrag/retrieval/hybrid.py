"""Hybrid retriever: run a keyword and a vector retriever, then fuse with RRF."""

from regrag.interfaces import Retriever
from regrag.retrieval.fusion import rrf_fuse
from regrag.types import RetrievedChunk, Route


class HybridRetriever:
    """Implements the Retriever protocol on top of any two Retrievers.

    Why two searches: keyword search nails exact terms ("231/25/2024-GST", "PPI-MTS"),
    vector search finds the same idea in different words ("demo cars" ~ "demonstration
    vehicles"). Fusing them gets both kinds of hit.
    """

    def __init__(
        self,
        keyword: Retriever,
        vector: Retriever,
        *,
        keyword_top_k: int = 30,
        vector_top_k: int = 30,
        rrf_k: int = 60,
    ):
        self.keyword = keyword
        self.vector = vector
        self.keyword_top_k = keyword_top_k
        self.vector_top_k = vector_top_k
        self.rrf_k = rrf_k

    def retrieve(self, query: str, route: Route, top_k: int) -> list[RetrievedChunk]:
        keyword_hits = self.keyword.retrieve(query, route, self.keyword_top_k)
        vector_hits = self.vector.retrieve(query, route, self.vector_top_k)
        return rrf_fuse([keyword_hits, vector_hits], k=self.rrf_k, top_k=top_k)
