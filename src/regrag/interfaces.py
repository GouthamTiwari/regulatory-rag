"""The six swappable parts of the pipeline, as Protocols (docs/SPEC.md section 7).

A Protocol says "anything with these methods will do". Code depends on these shapes, not on
concrete classes, so a test can pass in a fake and a later project can pass in a
replacement (a cached retriever, a fine-tuned generator, a guardrail validator).
`runtime_checkable` lets tests confirm with isinstance() that a class has the right methods.
"""

from typing import Protocol, runtime_checkable

from regrag.types import (
    DraftAnswer,
    EmbedResult,
    RetrievedChunk,
    Route,
    ValidationResult,
)


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> EmbedResult: ...  # vectors + token count


@runtime_checkable
class Retriever(Protocol):
    def retrieve(self, query: str, route: Route, top_k: int) -> list[RetrievedChunk]: ...


@runtime_checkable
class Reranker(Protocol):
    def rerank(
        self, query: str, chunks: list[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]: ...


@runtime_checkable
class Router(Protocol):
    def route(self, question: str) -> Route: ...  # "rbi" | "gst" | "both"


@runtime_checkable
class Generator(Protocol):
    def generate(self, question: str, chunks: list[RetrievedChunk]) -> DraftAnswer: ...


@runtime_checkable
class Validator(Protocol):
    def validate(
        self, question: str, draft: DraftAnswer, chunks: list[RetrievedChunk]
    ) -> ValidationResult: ...
