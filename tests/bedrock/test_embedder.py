"""Titan embedder with a fake Bedrock client (unit) and one real call (live)."""

import io
import json
import math
import threading
import time

import pytest
from botocore.exceptions import ClientError

from regrag.bedrock.embedder import MAX_INPUT_CHARS, TitanEmbedder
from regrag.interfaces import Embedder


class FakeBedrock:
    """Answers invoke_model like Titan: a vector derived from the text, plus a token count."""

    def __init__(self, fail_first: int = 0, delay_for: str | None = None):
        self.calls: list[dict] = []
        self.fail_first = fail_first
        self.delay_for = delay_for
        self.lock = threading.Lock()

    def invoke_model(self, modelId, body, **kwargs):
        request = json.loads(body)
        with self.lock:
            self.calls.append({"modelId": modelId, **request})
            if self.fail_first:
                self.fail_first -= 1
                raise ClientError(
                    {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
                    "InvokeModel",
                )
        if request["inputText"] == self.delay_for:
            time.sleep(0.05)  # make this one finish last, to prove order is kept
        vector = [float(len(request["inputText"]))] + [0.0] * (request["dimensions"] - 1)
        out = {"embedding": vector, "inputTextTokenCount": len(request["inputText"].split())}
        return {"body": io.BytesIO(json.dumps(out).encode())}


def make(fake, **kwargs):
    return TitanEmbedder(fake, dimensions=8, sleep=lambda s: None, **kwargs)


def test_order_is_preserved_with_concurrency():
    fake = FakeBedrock(delay_for="a")
    result = make(fake, concurrency=4).embed(["a", "bb", "ccc", "dddd"])
    assert [v[0] for v in result.vectors] == [1.0, 2.0, 3.0, 4.0]


def test_request_body_and_token_total():
    fake = FakeBedrock()
    result = make(fake).embed(["one two three", "four five"])
    assert result.input_tokens == 5
    assert fake.calls[0]["dimensions"] == 8 and fake.calls[0]["normalize"] is True
    assert fake.calls[0]["modelId"] == "amazon.titan-embed-text-v2:0"


def test_throttling_is_retried():
    fake = FakeBedrock(fail_first=2)
    result = make(fake).embed(["retry me"])
    assert len(result.vectors) == 1 and len(fake.calls) == 3


def test_non_retryable_error_is_raised():
    class Broken:
        def invoke_model(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "InvokeModel")

    with pytest.raises(ClientError):
        make(Broken()).embed(["x"])


def test_empty_list_makes_no_call():
    fake = FakeBedrock()
    assert make(fake).embed([]).vectors == [] and fake.calls == []


def test_overlong_text_is_truncated_with_a_warning():
    fake = FakeBedrock()
    with pytest.warns(UserWarning, match="truncated"):
        make(fake).embed(["x" * (MAX_INPUT_CHARS + 10)])
    assert len(fake.calls[0]["inputText"]) == MAX_INPUT_CHARS


def test_satisfies_the_embedder_protocol():
    assert isinstance(make(FakeBedrock()), Embedder)


@pytest.mark.live
def test_live_two_sentences_give_two_unit_vectors():
    from regrag.bedrock.client import BedrockAuthError, auth_mode, get_runtime_client
    from regrag.config import get_settings

    settings = get_settings()
    try:
        auth_mode(settings)
    except BedrockAuthError as exc:
        pytest.skip(str(exc))
    embedder = TitanEmbedder.from_settings(get_runtime_client(settings), settings)
    start = time.perf_counter()
    result = embedder.embed(
        ["Input tax credit on demo vehicles.", "KYC documents for an individual customer."]
    )
    seconds = time.perf_counter() - start
    assert [len(v) for v in result.vectors] == [1024, 1024]
    for vector in result.vectors:
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, rel_tol=1e-3)
    print(f"\nregion={settings.aws_region} tokens={result.input_tokens} latency={seconds:.2f}s")


def test_pacer_spaces_calls_evenly():
    # A frozen clock makes the expected waits exact (no dependence on machine speed).
    from regrag.bedrock.embedder import _Pacer

    waits: list[float] = []
    pacer = _Pacer(10.0, waits.append, clock=lambda: 100.0)
    for _ in range(5):
        pacer.wait()
    assert waits == pytest.approx([0.1, 0.2, 0.3, 0.4])  # first call goes at once


def test_embedder_uses_the_pacer_for_every_call():
    waits: list[float] = []
    embedder = TitanEmbedder(
        FakeBedrock(), dimensions=8, concurrency=1, requests_per_second=1000.0, sleep=waits.append
    )
    embedder.embed(["a", "b", "c"])
    assert len(waits) <= 2  # paced (calls 2 and 3 may wait), never more waits than calls
