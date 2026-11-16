"""Decide which corpus a question goes to: rbi, gst or both (SPEC section 5, "Router").

Step 1, keyword rules: free and instant, and they settle most questions.
Step 2, only when no rule fires: ask the LLM for one word.
When unsure, the answer is "both". Why: searching too widely costs a little precision;
searching the wrong corpus loses the answer entirely.
"""

import re

from regrag.bedrock.llm import BedrockLLM
from regrag.types import Route, Usage

_GST = re.compile(
    r"\b(?:gst|cgst|igst|sgst|utgst|input\s+tax\s+credit|itc|gstr[\s-]?\w*|place\s+of\s+supply|"
    r"e-?invoic\w*|e-?way\s+bill|cbic|reverse\s+charge|composition\s+scheme|tcs|"
    r"gst\s+council|supply\s+of\s+(?:goods|services)|taxable\s+(?:person|supply|value)|"
    r"export\s+of\s+services|imported\s+services?|refund\s+of\s+(?:igst|itc|tax)|"
    r"valu(?:ation|ed))\b|\d{1,3}/\d{1,2}/20\d{2}-gst",
    re.I,
)
_RBI = re.compile(
    r"\b(?:rbi|reserve\s+bank|kyc|know\s+your\s+customer|nbfcs?|ppis?|prepaid\s+payment|"
    r"banks?|banking|master\s+directions?|payment\s+aggregators?|upi|credit\s+cards?|"
    r"debit\s+cards?|card[\s-]issuers?|loans?|lending|advances|deposits?|priority\s+sector|"
    r"psl|fema|lrs|liberalised\s+remittance|remit\w*|frauds?|cyber\w*|outsourc\w*|bbps|"
    r"e-?mandate|digital\s+payments?|payment\s+systems?|money\s+transfer|"
    r"officially\s+valid\s+documents?|beneficial\s+owner|due\s+diligence|aadhaar)\b",
    re.I,
)

ROUTER_SYSTEM = (
    "You route questions about Indian regulation. Reply with exactly one word: "
    "RBI (banking, payments, NBFCs, KYC, foreign exchange), "
    "GST (goods and services tax), or BOTH."
)


def rule_route(question: str) -> Route | None:
    """The route the keyword rules give, or None when no rule fires."""
    gst, rbi = bool(_GST.search(question)), bool(_RBI.search(question))
    if gst and rbi:
        return "both"
    if gst:
        return "gst"
    if rbi:
        return "rbi"
    return None


def parse_route(reply: str) -> Route:
    """Read the LLM's one-word reply; anything unexpected becomes "both"."""
    words = re.findall(r"[a-z]+", reply.lower())
    if words and words[0] in ("rbi", "gst", "both"):
        return words[0]  # type: ignore[return-value]
    return "both"


class RuleThenLLMRouter:
    """Implements the Router protocol. After each call, `last_path` says what decided it
    ("rules", "llm" or "default") and `last_usage` holds any LLM tokens, for the log."""

    def __init__(self, llm: BedrockLLM | None):
        self.llm = llm
        self.last_path = ""
        self.last_usage = Usage()

    def route(self, question: str) -> Route:
        self.last_usage = Usage()
        decided = rule_route(question)
        if decided:
            self.last_path = "rules"
            return decided
        if self.llm is None:
            self.last_path = "default"
            return "both"
        try:
            reply, self.last_usage = self.llm.complete(ROUTER_SYSTEM, question, max_tokens=5)
        except Exception:  # a routing hiccup must not fail the question: search both
            self.last_path = "default"
            return "both"
        self.last_path = "llm"
        return parse_route(reply)
