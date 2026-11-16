"""Router: keyword rules first, one LLM call only when the rules are silent."""

import pytest

from regrag.interfaces import Router
from regrag.query.router import RuleThenLLMRouter, parse_route, rule_route
from regrag.types import Usage


class FakeLLM:
    def __init__(self, reply="GST", fail=False):
        self.reply = reply
        self.fail = fail
        self.calls = 0

    def complete(self, system, user, max_tokens=1500):
        self.calls += 1
        if self.fail:
            raise RuntimeError("bedrock down")
        return self.reply, Usage(input_tokens=40, output_tokens=1)


RULE_CASES = [
    # RBI (8)
    ("Which documents are officially valid for KYC at a commercial bank?", "rbi"),
    ("What is the maximum amount that can be loaded on a small PPI?", "rbi"),
    ("How must an NBFC classify its loans under scale based regulation?", "rbi"),
    ("What are the priority sector lending targets for foreign banks?", "rbi"),
    ("How much can a resident remit abroad under the LRS?", "rbi"),
    ("Within how many days must a fraud be reported to the Reserve Bank?", "rbi"),
    ("What authentication is required for digital payments by card?", "rbi"),
    ("Can a payment aggregator hold merchant funds in an escrow account?", "rbi"),
    # GST (8)
    ("Can a car dealer claim input tax credit on demo vehicles?", "gst"),
    ("What is the place of supply for data hosting services?", "gst"),
    ("Is an e-invoice required for supplies to a TDS-registered department?", "gst"),
    ("What late fee applies for delayed filing of GSTR-9C?", "gst"),
    ("How is ITC reversed on life insurance premium?", "gst"),
    ("What did Circular 195/07/2023-GST clarify on warranty replacements?", "gst"),
    ("How is the TCS liability split between e-commerce operators?", "gst"),
    ("How are imported services from a related person valued?", "gst"),
    # Both (4)
    ("A bank serves FPIs as custodian: what GST place of supply and what KYC apply?", "both"),
    ("How does GST treat vouchers, and how does RBI regulate PPI issuers?", "both"),
    ("Is GST payable on credit card late payment charges?", "both"),
    ("What GST applies to a corporate guarantee given for an NBFC's loan?", "both"),
]


@pytest.mark.parametrize(("question", "expected"), RULE_CASES)
def test_rules_decide_without_calling_the_llm(question, expected):
    llm = FakeLLM()
    router = RuleThenLLMRouter(llm)
    assert router.route(question) == expected
    assert llm.calls == 0 and router.last_path == "rules"


def test_question_with_no_keywords_makes_exactly_one_llm_call():
    llm = FakeLLM(reply="GST")
    router = RuleThenLLMRouter(llm)
    assert router.route("Are demonstration cars eligible for the benefit?") == "gst"
    assert llm.calls == 1 and router.last_path == "llm"
    assert router.last_usage.input_tokens == 40


@pytest.mark.parametrize("reply", ["I think it is about taxes", "", "42", "Banking, probably"])
def test_garbage_llm_reply_becomes_both(reply):
    assert RuleThenLLMRouter(FakeLLM(reply=reply)).route("Something vague?") == "both"


def test_llm_failure_or_no_llm_falls_back_to_both():
    router = RuleThenLLMRouter(FakeLLM(fail=True))
    assert router.route("Something vague?") == "both" and router.last_path == "default"
    assert RuleThenLLMRouter(None).route("Something vague?") == "both"


def test_parse_route_and_rule_route():
    assert parse_route("RBI.") == "rbi" and parse_route("Both") == "both"
    assert rule_route("Tell me something") is None


def test_satisfies_the_router_protocol():
    assert isinstance(RuleThenLLMRouter(None), Router)
