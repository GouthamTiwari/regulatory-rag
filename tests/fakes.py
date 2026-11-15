"""Tiny fake implementations of every Protocol in regrag.interfaces.

Other tasks' tests use these instead of real Bedrock or Postgres, so a test can exercise,
for example, the fusion code before the real retrievers exist. Each fake records its calls
in `.calls`, so tests can assert what was called and how often.
"""

import hashlib
import math

from regrag.types import (
    DraftAnswer,
    EmbedResult,
    RetrievedChunk,
    Route,
    Usage,
    ValidationResult,
)


def make_chunk(chunk_id: int = 1, **overrides) -> RetrievedChunk:
    """A RetrievedChunk with sensible defaults; override only the fields a test cares about."""
    values = {
        "chunk_id": chunk_id,
        "doc_id": f"doc-{chunk_id}",
        "corpus": "gst",
        "title": f"Test document {chunk_id}",
        "section_no": "Para 1",
        "section_path": "Para 1",
        "page_start": 1,
        "page_end": 1,
        "content_type": "text",
        "content": f"Synthetic test content {chunk_id}.",
        "source_url": f"https://example.invalid/doc-{chunk_id}",
    }
    values.update(overrides)
    return RetrievedChunk(**values)


class FakeEmbedder:
    """Deterministic unit-length vectors derived from a hash of the text. No AWS."""

    def __init__(self, dimensions: int = 1024):
        self.dimensions = dimensions
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> EmbedResult:
        self.calls.append(list(texts))
        vectors = [self._vector(t) for t in texts]
        # Word count stands in for the real token count.
        return EmbedResult(vectors=vectors, input_tokens=sum(len(t.split()) for t in texts))

    def _vector(self, text: str) -> list[float]:
        # Why a hash: the same text always gives the same vector, so tests are repeatable.
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [seed[i % len(seed)] - 127.5 for i in range(self.dimensions)]
        norm = math.sqrt(sum(x * x for x in raw))
        return [x / norm for x in raw]


class FakeRetriever:
    """Returns a fixed list of chunks, filtered by route and cut to top_k."""

    def __init__(self, chunks: list[RetrievedChunk] | None = None):
        self.chunks = chunks or []
        self.calls: list[tuple[str, Route, int]] = []

    def retrieve(self, query: str, route: Route, top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, route, top_k))
        matching = [c for c in self.chunks if route == "both" or c.corpus == route]
        return matching[:top_k]


class FakeReranker:
    """Keeps the input order and assigns falling scores (1.0, 0.9, ...), or fixed scores."""

    def __init__(self, scores: dict[int, float] | None = None):
        self.scores = scores  # optional chunk_id -> score
        self.calls: list[tuple[str, int, int]] = []

    def rerank(self, query: str, chunks: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
        self.calls.append((query, len(chunks), top_n))
        for i, chunk in enumerate(chunks):
            if self.scores is not None:
                chunk.rerank_score = self.scores.get(chunk.chunk_id, 0.0)
            else:
                chunk.rerank_score = max(0.0, 1.0 - 0.1 * i)
        ranked = sorted(chunks, key=lambda c: c.rerank_score or 0.0, reverse=True)
        return ranked[:top_n]


class FakeRouter:
    """Always answers with the same route."""

    def __init__(self, route: Route = "both"):
        self.fixed_route: Route = route
        self.calls: list[str] = []

    def route(self, question: str) -> Route:
        self.calls.append(question)
        return self.fixed_route


class FakeGenerator:
    """Cites the first chunk, or replies INSUFFICIENT_EVIDENCE when there are no chunks."""

    def __init__(self, insufficient: bool = False):
        self.insufficient = insufficient
        self.calls: list[tuple[str, int]] = []

    def generate(self, question: str, chunks: list[RetrievedChunk]) -> DraftAnswer:
        self.calls.append((question, len(chunks)))
        usage = Usage(input_tokens=100, output_tokens=20)
        if self.insufficient or not chunks:
            return DraftAnswer(text="INSUFFICIENT_EVIDENCE", insufficient=True, usage=usage)
        return DraftAnswer(text="The rule says X. [C1]", markers=["C1"], usage=usage)


class FakeValidator:
    """Passes, or fails with a fixed reason. Used to test the validator chain."""

    def __init__(self, passed: bool = True, reason: str = "fake_failure"):
        self.passed = passed
        self.reason = reason
        self.calls: list[str] = []

    def validate(
        self, question: str, draft: DraftAnswer, chunks: list[RetrievedChunk]
    ) -> ValidationResult:
        self.calls.append(question)
        if self.passed:
            return ValidationResult(passed=True)
        return ValidationResult(passed=False, reason=self.reason, problems=[self.reason])
