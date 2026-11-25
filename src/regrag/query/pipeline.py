"""The single entry point: answer_question() (SPEC sections 5 and 7).

question → route → retrieve → rerank → supersession check → generate → validate (one
retry) → abstain? → citations, cost, per-stage latency → log.

The CLI, the evaluation runner and every future project (cache, guardrails, agents) call
`answer_question`. It prints nothing and returns a JSON-serialisable QueryResult.
`build_pipeline` is the one place where real parts (Bedrock clients, the database) are
created; tests pass fake `Parts` instead.
"""

import time
import uuid
from dataclasses import dataclass, field
from functools import partial

from regrag.bedrock.pricing import cost_usd
from regrag.config import Settings, get_settings
from regrag.db import repository as repo
from regrag.ingest.statute import section_url
from regrag.query.abbreviations import expand_abbreviations
from regrag.query.querylog import record
from regrag.query.references import lookup as lookup_references
from regrag.query.references import parse_references
from regrag.query.supersession import apply_supersession
from regrag.query.validate import CitationValidator, decide_abstain, run_validators
from regrag.types import (
    ChunkRef,
    Citation,
    DraftAnswer,
    PipelineConfig,
    QueryResult,
    RetrievedChunk,
    Usage,
)

DISCLAIMER = "This is not legal or tax advice. Check the cited documents before acting."
ABSTAIN_MESSAGES = {
    "weak_evidence": "I could not find a passage in the RBI/GST documents that answers this.",
    "insufficient_evidence": "The retrieved passages do not answer this question.",
}


@dataclass
class Parts:
    """Everything the pipeline uses. Built by build_pipeline(), or by hand in tests."""

    settings: Settings
    router: object
    retriever: object
    reranker: object
    generator: object
    retry_generator: object  # same model, told what the validator objected to
    validators: list = field(default_factory=list)
    embedder: object | None = None  # for fetching a superseding document's best chunk
    conn: object | None = None  # database: documents, links, query logs
    model_ids: dict[str, str] = field(default_factory=dict)
    # Finds the chunks of provisions a question names (task 34); None = use the database.
    reference_lookup: object | None = None


def build_pipeline(config: PipelineConfig, settings: Settings | None = None, conn=None) -> Parts:
    """Wire the real parts for one of the four configurations (SPEC 6.4)."""
    from regrag.bedrock.client import get_runtime_client
    from regrag.bedrock.embedder import TitanEmbedder
    from regrag.bedrock.llm import BedrockLLM
    from regrag.bedrock.reranker import BedrockReranker, NoopReranker
    from regrag.db.connection import connect
    from regrag.query.generate import CitedGenerator
    from regrag.query.router import RuleThenLLMRouter
    from regrag.retrieval.hybrid import HybridRetriever
    from regrag.retrieval.keyword import KeywordRetriever
    from regrag.retrieval.vector import VectorRetriever

    s = config.settings or settings or get_settings()
    conn = conn if conn is not None else connect(s, autocommit=True)
    client = get_runtime_client(s)
    llm = BedrockLLM(client, s.bedrock_llm_model_id)
    embedder = TitanEmbedder.from_settings(client, s)
    keyword = KeywordRetriever(conn)
    vector = VectorRetriever(conn, embedder, ef_search=s.hnsw_ef_search)
    if config.retriever is not None:
        retriever = config.retriever
    elif config.name == "bm25":
        retriever = keyword
    elif config.name == "vector":
        retriever = vector
    else:
        retriever = HybridRetriever(
            keyword, vector, keyword_top_k=s.keyword_top_k, vector_top_k=s.vector_top_k,
            rrf_k=s.rrf_k,
        )  # fmt: skip
    if config.reranker is not None:
        reranker = config.reranker
    elif config.uses_rerank:
        rerank_client = get_runtime_client(s, region=s.bedrock_rerank_region)
        reranker = BedrockReranker(
            rerank_client,
            model_id=s.bedrock_rerank_model_id,
            requests_per_minute=s.rerank_requests_per_minute,
        )
    else:
        reranker = NoopReranker()
    generator = config.generator or CitedGenerator(llm, max_tokens=s.llm_max_tokens)
    retry = CitedGenerator(
        llm,
        max_tokens=s.llm_max_tokens,
        extra_instruction=(
            "Your previous answer failed a citation check. Every sentence that states a rule "
            "must end with a marker such as [C1], and only markers present in <context> may "
            "be used."
        ),
    )
    return Parts(
        settings=s,
        router=config.router or RuleThenLLMRouter(llm),
        retriever=retriever,
        reranker=reranker,
        generator=generator,
        retry_generator=retry,
        validators=[CitationValidator(), *config.validators],
        embedder=embedder,
        conn=conn,
        model_ids={
            "llm": s.bedrock_llm_model_id,
            "embed": s.bedrock_embed_model_id,
            **({"rerank": s.bedrock_rerank_model_id} if config.uses_rerank else {}),
        },
    )


def _cost(parts: Parts, usage: Usage) -> float:
    ids = parts.model_ids
    total = 0.0
    if "llm" in ids:
        total += cost_usd(ids["llm"], usage.input_tokens, usage.output_tokens)
    if "embed" in ids and usage.embed_tokens:
        total += cost_usd(ids["embed"], input_tokens=usage.embed_tokens)
    if "rerank" in ids and usage.rerank_queries:
        total += cost_usd(ids["rerank"], rerank_queries=usage.rerank_queries)
    return total


def _citations(markers: list[str], chunks: list[RetrievedChunk]) -> list[Citation]:
    citations = []
    for marker in markers:
        index = int(marker[1:]) - 1
        if 0 <= index < len(chunks):
            c = chunks[index]
            citations.append(
                Citation(marker, c.doc_id, c.title, c.section_no, c.page_start, c.page_end,
                         section_url(c.doc_id, c.section_path, c.source_url), c.status)
            )  # fmt: skip
    return citations


def _abstain_text(reason: str, chunks: list[RetrievedChunk]) -> str:
    message = ABSTAIN_MESSAGES.get(
        reason, "I could not produce an answer that passes the citation checks."
    )
    seen, suggestions = set(), []
    for c in chunks:
        if c.doc_id not in seen and len(suggestions) < 3:
            seen.add(c.doc_id)
            suggestions.append(f"- {c.title} ({c.source_url})")
    if suggestions:
        message += "\nYou may want to read:\n" + "\n".join(suggestions)
    return message


def answer_question(
    question: str,
    *,
    config: PipelineConfig | None = None,
    parts: Parts | None = None,
    log: bool = True,
) -> QueryResult:
    config = config or PipelineConfig()
    parts = parts or build_pipeline(config)
    s = parts.settings
    latency: dict[str, float] = {}
    usage = Usage()
    # Every stage sees the spelled-out question; the result keeps what the user typed.
    expanded = expand_abbreviations(question)

    def timed(stage: str, fn, *args):
        start = time.perf_counter()
        value = fn(*args)
        latency[stage] = round((time.perf_counter() - start) * 1000, 1)
        return value

    route = timed("route", parts.router.route, expanded)
    usage += getattr(parts.router, "last_usage", Usage())

    retrieved = timed("retrieve", parts.retriever.retrieve, expanded, route, s.fused_top_k)
    usage.embed_tokens += _embed_tokens(parts.retriever)

    reranked = timed("rerank", parts.reranker.rerank, expanded, retrieved, s.rerank_top_n)
    usage.rerank_queries += getattr(parts.reranker, "last_queries", 0)
    top_score = reranked[0].rerank_score if reranked and config.uses_rerank else None

    # Task 34: a provision named in the question ("rule 36(4)") goes first, then context.
    pinned = timed("references", _pinned_references, parts, expanded, route)
    if pinned:
        pinned_ids = {c.chunk_id for c in pinned}
        rest = [c for c in reranked if c.chunk_id not in pinned_ids]
        reranked = (pinned + rest)[: max(s.rerank_top_n, len(pinned))]
        if top_score is not None:
            top_score = max(top_score, PINNED_SCORE)

    shown, notes = timed("supersession", _supersession, parts, expanded, reranked, usage)

    draft: DraftAnswer = timed("generate", parts.generator.generate, expanded, shown)
    usage += draft.usage
    validation = run_validators(parts.validators, expanded, draft, shown)
    if not validation.passed and not draft.insufficient:
        draft = timed("regenerate", parts.retry_generator.generate, expanded, shown)
        usage += draft.usage
        validation = run_validators(parts.validators, expanded, draft, shown)

    abstained, reason = decide_abstain(top_score, draft, validation, s.abstain_threshold)
    result = QueryResult(
        query_id=str(uuid.uuid4()),
        question=question,
        route=route,
        config_name=config.name,
        answer=_abstain_text(reason, shown) if abstained else draft.text,
        abstained=abstained,
        abstain_reason=reason,
        citations=[] if abstained else _citations(draft.markers, shown),
        supersession_notes=notes,
        retrieved=[ChunkRef(c.chunk_id, c.doc_id, c.section_no) for c in retrieved],
        reranked=[ChunkRef(c.chunk_id, c.doc_id, c.section_no) for c in shown],
        rerank_top_score=top_score,
        usage=usage,
        cost_usd=_cost(parts, usage),
        latency_ms=latency,
        model_ids=dict(parts.model_ids),
    )
    result.latency_ms["total"] = round(sum(v for k, v in latency.items() if k != "total"), 1)
    if log:
        record(result, parts.conn)
    return result


PINNED_SCORE = 1.0  # a provision the question names is the strongest evidence there is


def _pinned_references(parts: Parts, question: str, route: str) -> list[RetrievedChunk]:
    """Statute chunks for the provisions the question names (none for RBI-only questions)."""
    references = parse_references(question)
    if not references or route == "rbi":
        return []
    lookup = parts.reference_lookup
    if lookup is None:
        if parts.conn is None:
            return []
        lookup = partial(lookup_references, parts.conn)
    chunks = lookup(references)
    for c in chunks:
        c.rerank_score = PINNED_SCORE
    return chunks


def _embed_tokens(retriever) -> int:
    """Embedding tokens spent by the retriever (a hybrid retriever holds a vector one)."""
    inner = getattr(retriever, "vector", retriever)
    return getattr(inner, "last_embed_tokens", 0)


def _supersession(parts: Parts, question: str, chunks: list[RetrievedChunk], usage: Usage):
    if parts.conn is None or not chunks:
        return chunks, []
    doc_ids = sorted({c.doc_id for c in chunks})
    relations = repo.get_relations_for(parts.conn, doc_ids)
    involved = (
        doc_ids
        + [r.from_doc_id for r in relations]
        + [r.to_doc_id for r in relations if r.to_doc_id]
    )
    documents = repo.get_documents(parts.conn, sorted(set(involved)))

    def fetch_replacement(doc_id: str, old_chunk: RetrievedChunk) -> list[RetrievedChunk]:
        # The newer document's passages closest to the *old passage* (the same rule in the
        # new text), found with stored vectors: no extra Bedrock call. Searching by the
        # question instead pulled an unrelated annex of the PSL 2025 directions.
        return repo.chunks_like(parts.conn, doc_id, old_chunk.chunk_id, limit=2)

    return apply_supersession(chunks, documents, relations, fetch_replacement)
