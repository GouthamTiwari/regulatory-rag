"""First real Bedrock call: proves the account, region and API key work. Costs < $0.0001.

Run on purpose only: uv run pytest -m live tests/bedrock/test_live_auth.py -s
"""

import time

import pytest

from regrag.bedrock.client import BedrockAuthError, auth_mode, get_runtime_client
from regrag.bedrock.pricing import cost_usd
from regrag.config import get_settings

pytestmark = pytest.mark.live


def test_one_converse_call_returns_text_and_usage():
    settings = get_settings()
    try:
        mode = auth_mode(settings)
    except BedrockAuthError as exc:
        pytest.skip(f"no Bedrock credentials in .env: {exc}")

    client = get_runtime_client(settings)
    start = time.perf_counter()
    response = client.converse(
        modelId=settings.bedrock_llm_model_id,
        messages=[{"role": "user", "content": [{"text": "Reply with exactly one word: pong"}]}],
        inferenceConfig={"maxTokens": 20, "temperature": 0},
    )
    seconds = time.perf_counter() - start

    text = "".join(
        block.get("text", "") for block in response["output"]["message"]["content"]
    ).strip()
    usage = response["usage"]
    assert text, "the model returned no text"
    assert usage["inputTokens"] > 0 and usage["outputTokens"] > 0

    cost = cost_usd(settings.bedrock_llm_model_id, usage["inputTokens"], usage["outputTokens"])
    # Printed for the changelog (run with -s). The key itself is never printed.
    print(
        f"\nauth={mode} region={settings.aws_region} model={settings.bedrock_llm_model_id} "
        f"reply={text!r} tokens={usage['inputTokens']}/{usage['outputTokens']} "
        f"latency={seconds:.2f}s cost=${cost:.6f}"
    )
