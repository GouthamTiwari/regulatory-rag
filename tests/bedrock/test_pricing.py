"""Price table and cost arithmetic (SPEC section 2.4)."""

import pytest

from regrag.bedrock.pricing import PRICES, UnknownModelPriceError, cost_usd
from regrag.config import NOVA_PRO_PROFILE_ID, Settings


@pytest.mark.parametrize(
    ("model_id", "kwargs", "expected"),
    [
        ("global.amazon.nova-2-lite-v1:0", {"input_tokens": 1_000_000}, 0.35),
        ("global.amazon.nova-2-lite-v1:0", {"output_tokens": 1_000_000}, 2.95),
        ("amazon.rerank-v1:0", {"rerank_queries": 1}, 0.001),
        ("amazon.titan-embed-text-v2:0", {"input_tokens": 1_000_000}, 0.024),
        ("apac.amazon.nova-pro-v1:0", {"input_tokens": 1_000_000}, 0.94),
        ("apac.amazon.nova-pro-v1:0", {"output_tokens": 1_000_000}, 3.76),
        # Upgrade-path models are priced too, so switching .env never breaks cost logging.
        ("global.anthropic.claude-haiku-5-5", {"input_tokens": 1_000_000}, 0.10),
        ("global.anthropic.claude-sonnet-5-5", {"output_tokens": 1_000_000}, 10.00),
        ("cohere.rerank-v3-5:0", {"rerank_queries": 1}, 0.002),
    ],
)
def test_known_prices(model_id, kwargs, expected):
    assert cost_usd(model_id, **kwargs) == pytest.approx(expected)


def test_typical_question_costs_about_a_third_of_a_cent():
    # 3K tokens in, 300 out on Nova 2 Lite, plus one rerank search unit (SPEC 2.4 budget).
    total = cost_usd("global.amazon.nova-2-lite-v1:0", 3000, 300) + cost_usd(
        "amazon.rerank-v1:0", rerank_queries=1
    )
    assert total == pytest.approx(0.002935)


def test_unknown_model_raises_instead_of_costing_zero():
    with pytest.raises(UnknownModelPriceError):
        cost_usd("some.unknown-model-v9:0", input_tokens=10)


def test_negative_counts_are_rejected():
    with pytest.raises(ValueError):
        cost_usd("amazon.titan-embed-text-v2:0", input_tokens=-1)


def test_every_default_model_has_a_price():
    # Why: a default with no price would crash the first logged query.
    s = Settings()
    for model_id in (
        s.bedrock_embed_model_id,
        s.bedrock_rerank_model_id,
        s.bedrock_llm_model_id,
        s.bedrock_judge_model_id,
        NOVA_PRO_PROFILE_ID,
    ):
        assert model_id in PRICES
