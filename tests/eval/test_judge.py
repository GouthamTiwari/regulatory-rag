"""Faithfulness judge with a mocked LLM."""

import json

import pytest

from regrag.bedrock.llm import BedrockLLM
from regrag.eval.judge import answer_sentences, judge_faithfulness
from regrag.types import Usage
from tests.fakes import make_chunk

CHUNKS = [make_chunk(1, content="ITC on demo vehicles is not blocked.")]
ANSWER = (
    "Input tax credit is available on demo vehicles [C1]. "
    "The vehicle must be used to promote sales [C1]. "
    "The dealer must capitalise it [C1][C2]. "
    "Credit is lost after five years [C1].\n"
    "This is not legal or tax advice."
)


class FakeLLM:
    model_id = "global.amazon.nova-2-lite-v1:0"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, user, max_tokens=1500):
        self.calls.append((system, user))
        return self.replies.pop(0), Usage(input_tokens=300, output_tokens=40)


def labels(*values):
    return json.dumps([{"n": i, "label": v, "reason": "r"} for i, v in enumerate(values, 1)])


def test_three_of_four_supported_gives_075():
    llm = FakeLLM(labels("supported", "supported", "supported", "unsupported"))
    result = judge_faithfulness(ANSWER, CHUNKS, llm)
    assert result.score == pytest.approx(0.75)
    assert result.per_sentence[3]["label"] == "unsupported"
    assert result.usage.input_tokens == 300 and result.model_id == FakeLLM.model_id


def test_markers_and_disclaimer_are_not_sentences():
    sentences = answer_sentences(ANSWER)
    assert len(sentences) == 4
    assert all("[C" not in s for s in sentences)
    assert not any("advice" in s for s in sentences)


def test_malformed_json_is_retried_once_then_fails_as_none():
    llm = FakeLLM("Sure! Here you go: not json", "[{'n': 1}]")
    result = judge_faithfulness(ANSWER, CHUNKS, llm)
    assert result.score is None and result.failed
    assert len(llm.calls) == 2 and "previous reply" in llm.calls[1][0]


def test_retry_that_succeeds_is_used():
    llm = FakeLLM("oops", "```json\n" + labels(*["supported"] * 4) + "\n```")
    assert judge_faithfulness(ANSWER, CHUNKS, llm).score == 1.0


def test_incomplete_labels_count_as_malformed():
    llm = FakeLLM(labels("supported"), labels("supported", "supported"))
    assert judge_faithfulness(ANSWER, CHUNKS, llm).score is None


def test_judge_model_id_is_what_gets_sent():
    class FakeClient:
        def __init__(self):
            self.model_ids = []

        def converse(self, **kwargs):
            self.model_ids.append(kwargs["modelId"])
            return {
                "output": {"message": {"content": [{"text": labels(*["supported"] * 4)}]}},
                "usage": {"inputTokens": 1, "outputTokens": 1},
                "stopReason": "end_turn",
            }

    client = FakeClient()
    judge = BedrockLLM(client, "apac.amazon.nova-pro-v1:0", sleep=lambda s: None)
    result = judge_faithfulness(ANSWER, CHUNKS, judge)
    assert client.model_ids == ["apac.amazon.nova-pro-v1:0"]
    assert result.model_id == "apac.amazon.nova-pro-v1:0" and result.score == 1.0
