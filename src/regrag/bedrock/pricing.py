"""On-demand prices for every model we may call, and per-call cost (SPEC section 2.4).

All prices are USD. Each model is priced for the region we call it in: embeddings and LLMs
in ap-south-1 (Mumbai), rerankers in ap-northeast-1 (Tokyo). The Amazon rows come from the
public AWS Price List files for those regions; the upgrade-path rows (Claude, Cohere) come
from the Anthropic and AWS pricing pages. Prices change: update this table and
PRICES_CHECKED_ON together.
"""

from dataclasses import dataclass
from datetime import date

PRICES_CHECKED_ON = date(2026, 11, 16)
PRICE_REGIONS = {"llm_and_embeddings": "ap-south-1", "rerank": "ap-northeast-1"}


@dataclass(frozen=True)
class ModelPrice:
    input_per_1m: float = 0.0  # USD per 1M input tokens
    output_per_1m: float = 0.0  # USD per 1M output tokens
    # Rerankers bill per request, not per token: Amazon Rerank per "search unit",
    # Cohere per "query" (each up to 100 documents).
    per_1k_rerank_units: float = 0.0


PRICES: dict[str, ModelPrice] = {
    # --- v1 defaults: Amazon first-party models -------------------------------------------
    "amazon.titan-embed-text-v2:0": ModelPrice(input_per_1m=0.024),  # Mumbai
    "amazon.rerank-v1:0": ModelPrice(per_1k_rerank_units=1.00),  # Tokyo
    # Mumbai, cross-region-global rate.
    "global.amazon.nova-2-lite-v1:0": ModelPrice(input_per_1m=0.35, output_per_1m=2.95),
    # Mumbai list price; assumed equal for the apac. profile (to confirm on the first bill).
    "apac.amazon.nova-pro-v1:0": ModelPrice(input_per_1m=0.94, output_per_1m=3.76),
    # --- Upgrade path (needs AWS Marketplace, i.e. Pay By Invoice on an AISPL account) ----
    "cohere.rerank-v3-5:0": ModelPrice(per_1k_rerank_units=2.00),
    # Haiku costs 5x more for prompts over 100K tokens; our prompts stay far below that.
    "global.anthropic.claude-haiku-5-5": ModelPrice(input_per_1m=0.10, output_per_1m=0.50),
    "global.anthropic.claude-sonnet-5-5": ModelPrice(input_per_1m=2.00, output_per_1m=10.00),
}


class UnknownModelPriceError(KeyError):
    """A model ID with no price. Raised so cost logging can never silently show $0."""


def price_for(model_id: str) -> ModelPrice:
    try:
        return PRICES[model_id]
    except KeyError:
        raise UnknownModelPriceError(
            f"No price for model {model_id!r}. Add it to regrag/bedrock/pricing.py "
            "(SPEC section 2.4)."
        ) from None


def cost_usd(
    model_id: str, input_tokens: int = 0, output_tokens: int = 0, rerank_queries: int = 0
) -> float:
    """Estimated USD cost of one call (or a batch of calls) to `model_id`."""
    if min(input_tokens, output_tokens, rerank_queries) < 0:
        raise ValueError("token and query counts cannot be negative")
    p = price_for(model_id)
    return (
        input_tokens * p.input_per_1m / 1_000_000
        + output_tokens * p.output_per_1m / 1_000_000
        + rerank_queries * p.per_1k_rerank_units / 1_000
    )
