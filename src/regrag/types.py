"""Plain data shapes shared by every stage of the pipeline.

These are deliberately simple dataclasses with no behaviour beyond small helpers: they are
the contract between tasks, and later projects (cache, guardrails, evals) depend on them.
Fields may be added; existing ones are not renamed or removed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    # Only for type hints: importing these at runtime would create an import cycle
    # (interfaces.py imports this module).
    from regrag.config import Settings
    from regrag.interfaces import Generator, Reranker, Retriever, Router, Validator

Route = Literal["rbi", "gst", "both"]
Corpus = Literal["rbi", "gst"]
ContentType = Literal["text", "table"]
DocStatus = Literal["active", "superseded", "withdrawn"]
RelationType = Literal["supersedes", "amends", "withdraws", "clarifies", "corrects"]
ConfigName = Literal["bm25", "vector", "hybrid", "hybrid_rerank"]

CONFIG_NAMES: tuple[str, ...] = ("bm25", "vector", "hybrid", "hybrid_rerank")


# --- Ingestion -----------------------------------------------------------------------------


@dataclass
class ManifestRow:
    """One document from data/manifest.csv."""

    doc_id: str
    corpus: Corpus
    doc_type: str
    title: str
    reference_no: str
    applies_to: str
    publish_date: date
    source_url: str
    pdf_url: str
    status: DocStatus = "active"
    updated_as_on: date | None = None
    sha256: str = ""


@dataclass
class ParsedPage:
    """One PDF page after parsing. Tables are already converted to Markdown."""

    page_no: int  # 1-based, as a human would cite it
    text: str
    tables: list[str] = field(default_factory=list)
    scanned: bool = False  # True when the page has almost no text (OCR is a non-goal)


@dataclass
class ParsedDocument:
    doc_id: str
    pages: list[ParsedPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)


@dataclass
class Chunk:
    """A piece of a document ready to embed and store."""

    doc_id: str
    chunk_index: int
    section_no: str
    section_path: str
    page_start: int
    page_end: int
    content_type: ContentType
    content: str
    token_count: int
    embedding: list[float] | None = None
    chunk_id: int | None = None  # assigned by the database


@dataclass
class Relation:
    """A supersession or amendment link between two documents."""

    from_doc_id: str
    relation: RelationType
    to_doc_ref: str  # always filled, e.g. "195/07/2023-GST"
    to_doc_id: str | None = None  # filled only when the target is in our corpus
    scope_note: str = ""  # e.g. "para 4 only"
    evidence: str = ""  # the sentence the link came from
    source: Literal["manual", "extracted"] = "extracted"
    reviewed: bool = False


# --- Retrieval -----------------------------------------------------------------------------


@dataclass
class RetrievedChunk:
    """A chunk returned by a retriever, with document details needed for citing it."""

    chunk_id: int
    doc_id: str
    corpus: Corpus
    title: str
    section_no: str
    section_path: str
    page_start: int
    page_end: int
    content_type: ContentType
    content: str
    source_url: str = ""
    status: DocStatus = "active"
    # Each stage fills in its own score or rank; None means "that stage did not run".
    keyword_rank: int | None = None
    vector_rank: int | None = None
    keyword_score: float | None = None
    vector_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None
    supersession_mark: str | None = None  # e.g. "SUPERSEDED BY rbi-12799"


@dataclass
class ChunkRef:
    """Minimal pointer to a chunk, enough for retrieval metrics and logs."""

    chunk_id: int
    doc_id: str
    section_no: str


@dataclass
class EmbedResult:
    vectors: list[list[float]]
    input_tokens: int = 0


# --- Answering -----------------------------------------------------------------------------


@dataclass
class Usage:
    """Billable usage for one question. Add two Usage objects with `+`."""

    input_tokens: int = 0  # LLM input tokens (router + generator)
    output_tokens: int = 0  # LLM output tokens, including thinking tokens
    embed_tokens: int = 0
    rerank_queries: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            embed_tokens=self.embed_tokens + other.embed_tokens,
            rerank_queries=self.rerank_queries + other.rerank_queries,
        )


@dataclass
class Citation:
    marker: str  # "C1"
    doc_id: str
    title: str
    section_no: str
    page_start: int
    page_end: int
    source_url: str
    status: DocStatus = "active"


@dataclass
class DraftAnswer:
    """What the generator produced, before validation."""

    text: str
    markers: list[str] = field(default_factory=list)  # cited markers, in order of appearance
    insufficient: bool = False  # the model replied INSUFFICIENT_EVIDENCE
    usage: Usage = field(default_factory=Usage)


@dataclass
class ValidationResult:
    passed: bool
    reason: str = ""  # short code such as "unknown_marker"; empty when passed
    problems: list[str] = field(default_factory=list)  # human-readable details


@dataclass
class QueryResult:
    """The final answer to one question: what answer_question() returns."""

    query_id: str
    question: str
    route: Route
    config_name: str
    answer: str
    abstained: bool = False
    abstain_reason: str = ""
    citations: list[Citation] = field(default_factory=list)
    supersession_notes: list[str] = field(default_factory=list)
    retrieved: list[ChunkRef] = field(default_factory=list)  # ranked list before rerank
    reranked: list[ChunkRef] = field(default_factory=list)  # list given to the model
    rerank_top_score: float | None = None
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    latency_ms: dict[str, float] = field(default_factory=dict)  # per stage
    model_ids: dict[str, str] = field(default_factory=dict)  # role -> model ID

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict: only str, int, float, bool, None, lists and dicts."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryResult:
        # Why ignore unknown keys: a newer version may have added fields (the schema only
        # grows), and an older reader such as a cache entry should still load it.
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        known["citations"] = [Citation(**c) for c in known.get("citations", [])]
        known["retrieved"] = [ChunkRef(**c) for c in known.get("retrieved", [])]
        known["reranked"] = [ChunkRef(**c) for c in known.get("reranked", [])]
        known["usage"] = Usage(**known.get("usage", {}))
        return cls(**known)


@dataclass
class PipelineConfig:
    """Which retrieval configuration to run, plus optional replacement parts.

    Any part left as None is built from the defaults. `validators` run after the built-in
    citation validator: this is the plug-in point for the guardrails project.
    """

    name: ConfigName = "hybrid_rerank"
    settings: Settings | None = None
    retriever: Retriever | None = None
    reranker: Reranker | None = None
    router: Router | None = None
    generator: Generator | None = None
    validators: list[Validator] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.name not in CONFIG_NAMES:
            raise ValueError(f"unknown config {self.name!r}; expected one of {CONFIG_NAMES}")

    @property
    def uses_keyword(self) -> bool:
        return self.name in ("bm25", "hybrid", "hybrid_rerank")

    @property
    def uses_vector(self) -> bool:
        return self.name in ("vector", "hybrid", "hybrid_rerank")

    @property
    def uses_rerank(self) -> bool:
        return self.name == "hybrid_rerank"
