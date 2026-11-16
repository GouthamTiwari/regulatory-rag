"""Evaluation runner: every golden question through every configuration (SPEC section 6).

    uv run python -m regrag.eval [--configs bm25,vector,hybrid,hybrid_rerank]
                                 [--retrieval-only] [--limit N] [--include-unreviewed]
                                 [--sample] [--out docs/eval]

Writes docs/eval/results.md (comparison table) and docs/eval/results.json (per question).
The four configurations differ only in retrieval and reranking (SPEC 6.4), so differences
in the table come from retrieval. One pipeline is built per configuration and reused for
all its questions, which keeps the Bedrock pacers effective across questions.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from regrag.bedrock.pricing import PRICES, PRICES_CHECKED_ON, cost_usd
from regrag.config import Settings, get_settings
from regrag.eval import metrics as m
from regrag.eval.golden import GoldenItem, load_golden
from regrag.eval.judge import judge_faithfulness
from regrag.ingest.manifest import REPO_ROOT
from regrag.query.pipeline import Parts, answer_question
from regrag.query.router import rule_route
from regrag.types import CONFIG_NAMES, ChunkRef, PipelineConfig, QueryResult, RetrievedChunk

OUT_DIR = REPO_ROOT / "docs" / "eval"
# Honest labels (SPEC decision 5): never "BM25" alone.
LABELS = {
    "bm25": "keyword (Postgres FTS, BM25-like)",
    "vector": "vector (Titan V2 + pgvector)",
    "hybrid": "hybrid (keyword + vector, RRF)",
    "hybrid_rerank": "hybrid + rerank (Amazon Rerank 1.0)",
}


@dataclass
class QuestionRow:
    id: str
    type: str
    config: str
    status: str = "ok"  # "ok" or "error"
    error: str = ""
    abstained: bool = False
    should_abstain: bool = False
    recall_at_5: int | None = None
    recall_at_10: int | None = None
    mrr: float | None = None
    markers: list[str] = field(default_factory=list)
    supplied: int = 0
    cited_docs: list[str] = field(default_factory=list)
    expected_docs: list[str] = field(default_factory=list)
    faithfulness: float | None = None
    judge_failed: bool = False
    has_notes: bool = False
    must_flag: bool = False
    latency_ms: float = 0.0
    cost_usd: float = 0.0


def ranked_refs(result: QueryResult) -> list[ChunkRef]:
    """The final ranking: what the model saw (reranked) first, then the rest retrieved."""
    shown = {r.chunk_id for r in result.reranked}
    return list(result.reranked) + [r for r in result.retrieved if r.chunk_id not in shown]


def _retrieval_only(item: GoldenItem, config: PipelineConfig, parts: Parts) -> QueryResult:
    """Search (and rerank when the configuration has it) without any LLM call."""
    s = parts.settings
    start = time.perf_counter()
    route = rule_route(item.question) or "both"  # rules only: no LLM
    retrieved = parts.retriever.retrieve(item.question, route, s.fused_top_k)
    reranked = parts.reranker.rerank(item.question, retrieved, s.rerank_top_n)
    vector = getattr(parts.retriever, "vector", parts.retriever)
    embed_tokens = getattr(vector, "last_embed_tokens", 0)
    queries = getattr(parts.reranker, "last_queries", 0)
    cost = 0.0
    if embed_tokens and "embed" in parts.model_ids:
        cost += cost_usd(parts.model_ids["embed"], input_tokens=embed_tokens)
    if queries and "rerank" in parts.model_ids:
        cost += cost_usd(parts.model_ids["rerank"], rerank_queries=queries)
    return QueryResult(
        query_id="retrieval-only",
        question=item.question,
        route=route,
        config_name=config.name,
        answer="",
        retrieved=[ChunkRef(c.chunk_id, c.doc_id, c.section_no) for c in retrieved],
        reranked=[ChunkRef(c.chunk_id, c.doc_id, c.section_no) for c in reranked],
        cost_usd=cost,
        latency_ms={"total": round((time.perf_counter() - start) * 1000, 1)},
    )


def evaluate_question(
    item: GoldenItem,
    config: PipelineConfig,
    parts: Parts,
    *,
    retrieval_only: bool,
    judge_llm=None,
    fetch_chunks: Callable[[list[int]], list[RetrievedChunk]] | None = None,
) -> QuestionRow:
    row = QuestionRow(
        id=item.id,
        type=item.type,
        config=config.name,
        should_abstain=item.should_abstain,
        expected_docs=list(item.expected_doc_ids),
        must_flag=item.must_flag_supersession,
    )
    try:
        if retrieval_only:
            result = _retrieval_only(item, config, parts)
        else:
            result = answer_question(item.question, config=config, parts=parts, log=False)
    except Exception as exc:  # one broken question must not stop a 30-minute run
        row.status, row.error = "error", f"{type(exc).__name__}: {exc}"[:300]
        return row
    ranked = ranked_refs(result)
    if not item.should_abstain:
        row.recall_at_5 = m.recall_at_k(ranked, item, 5)
        row.recall_at_10 = m.recall_at_k(ranked, item, 10)
        row.mrr = m.mrr(ranked, item, 10)
    row.abstained = result.abstained
    row.markers = [c.marker for c in result.citations]
    row.supplied = len(result.reranked)
    row.cited_docs = [c.doc_id for c in result.citations]
    row.has_notes = bool(result.supersession_notes)
    row.latency_ms = result.latency_ms.get("total", 0.0)
    row.cost_usd = result.cost_usd
    if not retrieval_only and not result.abstained and judge_llm is not None and fetch_chunks:
        cited_ids = []
        for marker in row.markers:
            index = int(marker[1:]) - 1
            if 0 <= index < len(result.reranked):
                cited_ids.append(result.reranked[index].chunk_id)
        judged = judge_faithfulness(
            result.answer, fetch_chunks(list(dict.fromkeys(cited_ids))), judge_llm
        )
        row.faithfulness, row.judge_failed = judged.score, judged.failed
        if judged.model_id in PRICES:
            row.cost_usd += cost_usd(
                judged.model_id, judged.usage.input_tokens, judged.usage.output_tokens
            )
    return row


def run_eval(
    items: list[GoldenItem],
    config_names: list[str],
    parts_for: Callable[[str], Parts],
    *,
    retrieval_only: bool = False,
    judge_llm=None,
    fetch_chunks=None,
    progress: Callable[[QuestionRow], None] | None = None,
) -> list[QuestionRow]:
    rows = []
    for name in config_names:
        config = PipelineConfig(name=name)
        parts = parts_for(name)  # built once per configuration
        for item in items:
            row = evaluate_question(
                item, config, parts, retrieval_only=retrieval_only,
                judge_llm=judge_llm, fetch_chunks=fetch_chunks,
            )  # fmt: skip
            rows.append(row)
            if progress:
                progress(row)
    return rows


def summarize(rows: list[QuestionRow]) -> dict:
    ok = [r for r in rows if r.status == "ok"]
    answered = [r for r in ok if not r.abstained]
    abst = m.abstention_scores([(r.abstained, r.should_abstain) for r in ok])
    return {
        "questions": len(rows),
        "errors": len(rows) - len(ok),
        "recall_at_5": m.mean([r.recall_at_5 for r in ok]),
        "recall_at_10": m.mean([r.recall_at_10 for r in ok]),
        "mrr": m.mean([r.mrr for r in ok]),
        "citation_validity": m.citation_validity([(r.markers, r.supplied) for r in answered]),
        "citation_accuracy": m.citation_accuracy(
            [(r.cited_docs, r.expected_docs) for r in answered]
        ),
        "faithfulness": m.mean([r.faithfulness for r in answered]),
        "judge_failed": sum(r.judge_failed for r in answered),
        "abstain_accuracy": abst["accuracy"],
        "abstain_precision": abst["precision"],
        "abstain_recall": abst["recall"],
        "supersession_flag_rate": m.supersession_flag_rate(
            [(r.has_notes, r.must_flag) for r in ok]
        ),
        "latency_p95_s": (m.latency_summary([r.latency_ms for r in ok])["p95"] or 0) / 1000,
        "mean_cost_usd": m.mean([r.cost_usd for r in ok]),
        "total_cost_usd": sum(r.cost_usd for r in rows),
    }


def estimate_cost(
    n_questions: int, config_names: list[str], settings: Settings, *, retrieval_only: bool
) -> float:
    """Rough upper estimate printed before a run. Uses the judge model's own price."""
    total = 0.0
    for name in config_names:
        config = PipelineConfig(name=name)
        per_config = 0.0
        if config.uses_vector:
            per_config += cost_usd(settings.bedrock_embed_model_id, input_tokens=30)
        if config.uses_rerank:
            per_config += cost_usd(settings.bedrock_rerank_model_id, rerank_queries=1)
        if not retrieval_only:
            per_config += cost_usd(
                settings.bedrock_llm_model_id, 4000, 400
            )  # answer (+ retry headroom)
            per_config += cost_usd(settings.bedrock_judge_model_id, 3000, 300)  # faithfulness judge
        total += per_config * n_questions
    return total


def _fmt(value, kind: str = "ratio") -> str:
    if value is None:
        return "–"
    if kind == "ratio":
        return f"{value:.2f}"
    if kind == "seconds":
        return f"{value:.1f}"
    if kind == "usd":
        return f"${value:.4f}"
    return str(value)


def write_report(out_dir: Path, rows: list[QuestionRow], meta: dict) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    configs = list(dict.fromkeys(r.config for r in rows))
    summaries = {c: summarize([r for r in rows if r.config == c]) for c in configs}
    lines = ["# Evaluation results", ""]
    if meta.get("sample"):
        lines += [f"> **Sample, not final.** {meta.get('sample_note', '')}".rstrip(), ""]
    lines += [
        f"- Date: {meta['date']}",
        f"- Golden questions: {meta['questions']} ({meta['reviewed']} reviewed)",
        "- Mode: "
        + ("retrieval only (no LLM)" if meta["retrieval_only"] else "full answers + LLM judge"),
        f"- Generator: `{meta['llm']}`  Judge: `{meta['judge']}`",
        f"- Embeddings: `{meta['embed']}`  Reranker: `{meta['rerank']}`",
        f"- Regions: {meta['region']} (reranker: {meta['rerank_region']})",
        f"- Prices checked on: {meta['prices_checked_on']}  "
        f"Total run cost: ${meta['total_cost']:.4f}",
        "",
        "| Configuration | Recall@5 | Recall@10 | MRR | Citation validity | Citation accuracy "
        "| Faithfulness | Abstain acc. | Abstain P | Abstain R | Supersession flag "
        "| p95 latency (s) | Mean cost | Errors |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in configs:
        s = summaries[c]
        lines.append(
            f"| {LABELS.get(c, c)} | {_fmt(s['recall_at_5'])} | {_fmt(s['recall_at_10'])} "
            f"| {_fmt(s['mrr'])} | {_fmt(s['citation_validity'])} | {_fmt(s['citation_accuracy'])} "
            f"| {_fmt(s['faithfulness'])} | {_fmt(s['abstain_accuracy'])} "
            f"| {_fmt(s['abstain_precision'])} | {_fmt(s['abstain_recall'])} "
            f"| {_fmt(s['supersession_flag_rate'])} | {_fmt(s['latency_p95_s'], 'seconds')} "
            f"| {_fmt(s['mean_cost_usd'], 'usd')} | {s['errors']} |"
        )
    lines += [
        "",
        "Definitions: SPEC section 6.3. Retrieval metrics use answerable questions only; "
        '"–" means the metric is undefined for this run (e.g. no LLM in retrieval-only mode).',
    ]
    md, js = out_dir / "results.md", out_dir / "results.json"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    js.write_text(
        json.dumps(
            {"meta": meta, "summary": summaries, "rows": [asdict(r) for r in rows]}, indent=2
        ),
        encoding="utf-8",
    )
    return md, js


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the four retrieval configurations")
    parser.add_argument("--configs", default=",".join(CONFIG_NAMES))
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-unreviewed", action="store_true")
    parser.add_argument(
        "--sample", action="store_true", help='label the report "sample, not final"'
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    settings = get_settings()
    config_names = [c.strip() for c in args.configs.split(",") if c.strip()]
    everything = load_golden(include_unreviewed=True)
    items = [i for i in everything if args.include_unreviewed or i.reviewed][: args.limit]
    if not items:
        print("No golden questions to run (none reviewed yet? use --include-unreviewed).")
        return 1
    estimate = estimate_cost(len(items), config_names, settings, retrieval_only=args.retrieval_only)
    print(
        f"{len(items)} questions x {len(config_names)} configurations; judge: "
        f"{settings.bedrock_judge_model_id}; estimated cost up to ${estimate:.3f}",
        flush=True,
    )

    from regrag.bedrock.client import get_runtime_client
    from regrag.bedrock.llm import BedrockLLM
    from regrag.db import repository as repo
    from regrag.db.connection import connect
    from regrag.query.pipeline import build_pipeline

    conn = connect(settings, autocommit=True)
    judge = (
        None
        if args.retrieval_only
        else BedrockLLM(get_runtime_client(settings), settings.bedrock_judge_model_id)
    )

    def show(r: QuestionRow) -> None:
        state = (
            "ERROR " + r.error
            if r.status == "error"
            else ("abstained" if r.abstained else "answered")
        )
        print(
            f"{r.config:14} {r.id} recall@5={r.recall_at_5} mrr={r.mrr} faith={r.faithfulness} "
            f"{state} ${r.cost_usd:.4f}",
            flush=True,
        )

    rows = run_eval(
        items, config_names, lambda name: build_pipeline(PipelineConfig(name=name), settings, conn),
        retrieval_only=args.retrieval_only, judge_llm=judge,
        fetch_chunks=lambda ids: repo.get_chunks(conn, ids), progress=show,
    )  # fmt: skip
    meta = {
        "date": date.today().isoformat(),
        "questions": len(items),
        "reviewed": sum(i.reviewed for i in items),
        "retrieval_only": args.retrieval_only,
        "sample": args.sample,
        "sample_note": "Run on the 20 seed questions, which Goutham has not reviewed yet.",
        "llm": settings.bedrock_llm_model_id,
        "judge": settings.bedrock_judge_model_id,
        "embed": settings.bedrock_embed_model_id,
        "rerank": settings.bedrock_rerank_model_id,
        "region": settings.aws_region,
        "rerank_region": settings.bedrock_rerank_region,
        "prices_checked_on": PRICES_CHECKED_ON.isoformat(),
        "total_cost": sum(r.cost_usd for r in rows),
    }
    md, js = write_report(args.out, rows, meta)
    print(md.read_text(encoding="utf-8"))
    print(f"Wrote {md} and {js}. Total cost ${meta['total_cost']:.4f}")
    return 0
