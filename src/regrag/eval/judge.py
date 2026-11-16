"""Faithfulness judge: is each sentence of an answer supported by the passages it cites?
(SPEC section 6.3)

The judge is a separate model call (BEDROCK_JUDGE_MODEL_ID): Nova 2 Lite for development
runs, Nova Pro for the final reported run. The code never assumes which model it is.
Score = supported sentences / all judged sentences. If the judge's reply cannot be read
even after one retry, the result is None ("judge failed"), never 0, so a parsing problem
is not mistaken for an unfaithful answer.
"""

import json
import re
from dataclasses import dataclass, field

from regrag.query.validate import _MARKER_GROUP
from regrag.types import RetrievedChunk, Usage

JUDGE_SYSTEM = """You check answers about Indian regulation for faithfulness.
For each numbered sentence, decide if it is fully supported by the SOURCES alone.
"supported": every fact in the sentence is stated in the sources.
"unsupported": anything in it is missing from, or contradicts, the sources.
Reply with ONLY a JSON array, one object per sentence, nothing else:
[{"n": 1, "label": "supported", "reason": "short reason"}]"""

RETRY_REMINDER = (
    "Your previous reply was not valid JSON in the required shape. Reply with ONLY the JSON "
    'array, one object per sentence, each with "n", "label" and "reason".'
)

_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[\d])|\n+")
# The disclaimer ("This is not legal or tax advice.") and a "Sources:" heading are frame,
# not claims.
_FRAME = re.compile(r"not\s+(?:legal|tax)(?:\s+or\s+(?:legal|tax))?\s+advice|^sources?\s*:", re.I)
_LABELS = {"supported", "unsupported"}


@dataclass
class JudgeResult:
    score: float | None  # None when the judge failed
    per_sentence: list[dict] = field(default_factory=list)  # {"sentence", "label", "reason"}
    usage: Usage = field(default_factory=Usage)
    model_id: str = ""
    failed: bool = False


def answer_sentences(answer: str) -> list[str]:
    """The sentences to judge: citation markers removed, the disclaimer and empty or
    marker-only fragments skipped."""
    out = []
    for piece in _SPLIT.split(answer):
        text = _MARKER_GROUP.sub("", piece).strip(" -*•\t")
        if len(text.split()) < 3 or _FRAME.search(text):
            continue
        text = re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s+", " ", text))  # "years ." -> "years."
        out.append(text)
    return out


def _parse(reply: str, count: int) -> list[dict] | None:
    """The judge's labels, or None if the reply is not exactly what was asked for."""
    match = re.search(r"\[.*\]", reply, re.S)  # tolerate ```json fences around the array
    if not match:
        return None
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    labels: dict[int, dict] = {}
    for item in items if isinstance(items, list) else []:
        if (
            isinstance(item, dict)
            and isinstance(item.get("n"), int)
            and 1 <= item["n"] <= count
            and str(item.get("label", "")).lower() in _LABELS
        ):
            labels[item["n"]] = {
                "label": str(item["label"]).lower(),
                "reason": str(item.get("reason", ""))[:200],
            }
    return [labels[n] for n in range(1, count + 1)] if len(labels) == count else None


def judge_faithfulness(answer: str, cited_chunks: list[RetrievedChunk], llm) -> JudgeResult:
    """`llm` is any object with complete(system, user, max_tokens) -> (text, Usage) and a
    `model_id` attribute (a BedrockLLM built with the judge model ID)."""
    model_id = getattr(llm, "model_id", "")
    sentences = answer_sentences(answer)
    if not sentences:
        return JudgeResult(score=None, model_id=model_id, failed=True)
    sources = "\n\n".join(
        f"[S{i}] {c.title} | {c.section_no}\n{c.content}" for i, c in enumerate(cited_chunks, 1)
    )
    numbered = "\n".join(f"{n}. {s}" for n, s in enumerate(sentences, 1))
    user = f"SOURCES:\n{sources}\n\nSENTENCES:\n{numbered}"
    usage = Usage()
    for system in (JUDGE_SYSTEM, f"{JUDGE_SYSTEM}\n\n{RETRY_REMINDER}"):
        reply, used = llm.complete(system, user, max_tokens=60 * len(sentences) + 200)
        usage += used
        labels = _parse(reply, len(sentences))
        if labels is not None:
            per_sentence = [
                {"sentence": s, **lab} for s, lab in zip(sentences, labels, strict=True)
            ]
            supported = sum(lab["label"] == "supported" for lab in labels)
            return JudgeResult(supported / len(labels), per_sentence, usage, model_id)
    return JudgeResult(score=None, usage=usage, model_id=model_id, failed=True)
