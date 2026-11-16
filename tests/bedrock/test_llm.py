"""BedrockLLM with a fake Converse client (unit) and one real call (live)."""

import time

import pytest
from botocore.exceptions import ClientError

from regrag.bedrock.llm import BedrockLLM, LLMError


class FakeConverse:
    def __init__(self, response=None, fail_first: int = 0):
        self.response = response or {
            "output": {"message": {"content": [{"text": "pong"}]}},
            "usage": {"inputTokens": 12, "outputTokens": 2},
            "stopReason": "end_turn",
        }
        self.fail_first = fail_first
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_first:
            self.fail_first -= 1
            raise ClientError({"Error": {"Code": "ThrottlingException"}}, "Converse")
        return self.response


def make(fake):
    return BedrockLLM(fake, "global.amazon.nova-2-lite-v1:0", sleep=lambda s: None)


def test_text_and_usage_are_returned_and_request_is_shaped():
    fake = FakeConverse()
    text, usage = make(fake).complete("Be brief.", "ping", max_tokens=20)
    assert text == "pong"
    assert (usage.input_tokens, usage.output_tokens) == (12, 2)
    call = fake.calls[0]
    assert call["system"] == [{"text": "Be brief."}]
    assert call["inferenceConfig"] == {"maxTokens": 20, "temperature": 0.0}
    assert call["modelId"] == "global.amazon.nova-2-lite-v1:0"


def test_only_text_blocks_are_used():
    fake = FakeConverse(
        {
            "output": {
                "message": {
                    "content": [
                        {"reasoningContent": {"reasoningText": {"text": "scratch work"}}},
                        {"text": "The answer."},
                    ]
                }
            },
            "usage": {"inputTokens": 5, "outputTokens": 40},
            "stopReason": "end_turn",
        }
    )
    assert make(fake).complete("", "q")[0] == "The answer."


def test_throttling_is_retried():
    fake = FakeConverse(fail_first=2)
    assert make(fake).complete("", "q")[0] == "pong" and len(fake.calls) == 3


def test_max_tokens_with_empty_text_raises_a_clear_error():
    fake = FakeConverse(
        {"output": {"message": {"content": []}}, "usage": {}, "stopReason": "max_tokens"}
    )
    with pytest.raises(LLMError, match="raise llm_max_tokens"):
        make(fake).complete("", "q")


@pytest.mark.live
def test_live_one_line_prompt():
    from regrag.bedrock.client import BedrockAuthError, auth_mode, get_runtime_client
    from regrag.bedrock.pricing import cost_usd
    from regrag.config import get_settings

    settings = get_settings()
    try:
        auth_mode(settings)
    except BedrockAuthError as exc:
        pytest.skip(str(exc))
    llm = BedrockLLM(get_runtime_client(settings), settings.bedrock_llm_model_id)
    start = time.perf_counter()
    text, usage = llm.complete("Answer in one short sentence.", "What does KYC stand for?", 100)
    seconds = time.perf_counter() - start
    assert text
    cost = cost_usd(settings.bedrock_llm_model_id, usage.input_tokens, usage.output_tokens)
    print(
        f"\nreply={text!r} tokens={usage.input_tokens}/{usage.output_tokens} "
        f"latency={seconds:.2f}s cost=${cost:.6f}"
    )
