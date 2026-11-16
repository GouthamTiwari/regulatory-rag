"""Record every answered question: one row in query_logs and one JSON log line."""

import json
import logging

from regrag.db import repository as repo
from regrag.types import QueryResult

logger = logging.getLogger("regrag.query")


def log_summary(result: QueryResult) -> dict:
    """The small, JSON-safe summary written to the log (no answer text, no secrets)."""
    return {
        "query_id": result.query_id,
        "config": result.config_name,
        "route": result.route,
        "abstained": result.abstained,
        "abstain_reason": result.abstain_reason,
        "cited_docs": sorted({c.doc_id for c in result.citations}),
        "rerank_top_score": result.rerank_top_score,
        "latency_ms": result.latency_ms,
        "tokens_in": result.usage.input_tokens,
        "tokens_out": result.usage.output_tokens,
        "embed_tokens": result.usage.embed_tokens,
        "rerank_queries": result.usage.rerank_queries,
        "cost_usd": round(result.cost_usd, 6),
    }


def record(result: QueryResult, conn=None) -> None:
    """Write the log line, and the database row when a connection is given."""
    logger.info(json.dumps(log_summary(result)))
    if conn is not None:
        repo.insert_query_log(conn, result)
