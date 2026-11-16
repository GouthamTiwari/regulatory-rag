"""Rerankers (SPEC section 5, "Rerank").

`BedrockReranker` calls a Bedrock rerank model with InvokeModel on `bedrock-runtime`. Why
not the agent-runtime Rerank API: it does not accept Bedrock API keys, which is how this
project authenticates (SPEC 2.3). The request format differs per model, so a small adapter
per model ID builds the body; both return {"results": [{"index", "relevance_score"}]}.

Verified live on 2026-11-16 (Tokyo) for amazon.rerank-v1:0:
  request  {"query": str, "documents": [str, ...], "top_n": int}
  response {"results": [{"index": int, "relevance_score": float}, ...]}
"""

import json
import time
from collections.abc import Callable
from dataclasses import replace

from regrag.bedrock.retry import with_retries
from regrag.types import RetrievedChunk

# One request may carry at most 100 documents; each request is one billed unit.
MAX_DOCS_PER_CALL = 100


def _amazon_body(query: str, documents: list[str], top_n: int) -> dict:
    return {"query": query, "documents": documents, "top_n": top_n}


def _cohere_body(query: str, documents: list[str], top_n: int) -> dict:
    return {"api_version": 2, "query": query, "documents": documents, "top_n": top_n}


ADAPTERS: dict[str, Callable[[str, list[str], int], dict]] = {
    "amazon.rerank-v1:0": _amazon_body,
    "cohere.rerank-v3-5:0": _cohere_body,  # upgrade path (needs AWS Marketplace)
}


def document_text(chunk: RetrievedChunk) -> str:
    """What the reranker reads: title and section path give the passage its context."""
    header = "\n".join(p for p in (chunk.title, chunk.section_path) if p)
    return f"{header}\n\n{chunk.content}" if header else chunk.content


class BedrockReranker:
    """Implements the Reranker protocol. `last_queries` / `total_queries` count billed units."""

    def __init__(
        self,
        client,
        *,
        model_id: str = "amazon.rerank-v1:0",
        sleep: Callable[[float], None] = time.sleep,
    ):
        if model_id not in ADAPTERS:
            raise ValueError(f"no rerank adapter for {model_id!r}; known: {sorted(ADAPTERS)}")
        self.client = client
        self.model_id = model_id
        self.build_body = ADAPTERS[model_id]
        self.sleep = sleep
        self.last_queries = 0
        self.total_queries = 0

    def _scores(self, query: str, documents: list[str]) -> dict[int, float]:
        body = json.dumps(self.build_body(query, documents, len(documents)))

        def call():
            return self.client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )

        payload = json.loads(with_retries(call, sleep=self.sleep)["body"].read())
        return {r["index"]: float(r["relevance_score"]) for r in payload["results"]}

    def rerank(self, query: str, chunks: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
        self.last_queries = 0
        if not chunks:
            return []
        scored: list[RetrievedChunk] = []
        for start in range(0, len(chunks), MAX_DOCS_PER_CALL):
            batch = chunks[start : start + MAX_DOCS_PER_CALL]
            scores = self._scores(query, [document_text(c) for c in batch])
            self.last_queries += 1
            # A document the model left out of its answer gets 0, never a made-up score.
            scored += [replace(c, rerank_score=scores.get(i, 0.0)) for i, c in enumerate(batch)]
        self.total_queries += self.last_queries
        # Highest score first; Python's sort is stable, so ties keep the retrieval order.
        scored.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return scored[:top_n]


class NoopReranker:
    """Keeps the retrieval order and cuts to top_n: used by the configurations without a
    reranker (bm25, vector, hybrid), so they differ from hybrid_rerank in one thing only."""

    last_queries = 0
    total_queries = 0

    def rerank(self, query: str, chunks: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
        return list(chunks[:top_n])
