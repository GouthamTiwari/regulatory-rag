"""Check a draft answer before anyone sees it, and decide when to abstain (SPEC section 5).

Checks (CitationValidator):
  (a) every citation marker such as [C3] must point to a chunk that was actually given to
      the model. A marker with nothing behind it is an invented source.
  (b) every sentence that states a rule must carry a citation, so no claim is unsourced.

Abstain (decide_abstain) when the model said INSUFFICIENT_EVIDENCE, when the best rerank
score is below the threshold, or when validation failed. `run_validators` runs a list of
validators in order: the built-in one first, then any extra ones a later project plugs in
(for example guardrails), each able to force an abstention with a reason.
"""

import re

from regrag.interfaces import Validator
from regrag.types import DraftAnswer, RetrievedChunk, ValidationResult

# "[C1]", "[C2][C3]" and "[C1, C2]"
_MARKER_GROUP = re.compile(r"\[(C\d+(?:\s*,\s*C\d+)*)\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[\d])|\n+")
# Words that signal a sentence states a rule, a limit or an entitlement.
_RULE_WORDS = re.compile(
    r"\b(?:shall|must|may|should|required|requires|allowed|permitted|prohibited|eligible|"
    r"available|applicable|applies|exempt|limit|maximum|minimum|not\s+blocked|blocked|"
    r"mandatory|liable|payable|entitled|within\s+\d+)\b|(?:rs\.?|₹)\s?\d|\d\s?%",
    re.I,
)
# Lines that are part of the answer's frame, not claims: the disclaimer and similar.
_FRAME = re.compile(r"not\s+(?:legal|tax)\s+advice|^(?:sources?|citations?|note)\s*:?$", re.I)
_MIN_WORDS_FOR_A_CLAIM = 5


def markers_in(text: str) -> list[str]:
    """All citation markers in the text, in order of first appearance, without duplicates."""
    found: list[str] = []
    for group in _MARKER_GROUP.findall(text):
        for marker in re.split(r"\s*,\s*", group):
            if marker not in found:
                found.append(marker)
    return found


def _claims_without_citation(text: str) -> list[str]:
    missing = []
    for sentence in _SENTENCE_SPLIT.split(text):
        sentence = sentence.strip(" -*•\t")
        if (
            len(sentence.split()) < _MIN_WORDS_FOR_A_CLAIM
            or _FRAME.search(sentence)
            or not _RULE_WORDS.search(sentence)
        ):
            continue
        if not _MARKER_GROUP.search(sentence):
            missing.append(sentence)
    return missing


class CitationValidator:
    """Implements the Validator protocol: checks (a) and (b) above."""

    def validate(
        self, question: str, draft: DraftAnswer, chunks: list[RetrievedChunk]
    ) -> ValidationResult:
        if draft.insufficient:
            return ValidationResult(passed=True)  # nothing claimed, nothing to check
        valid = {f"C{i}" for i in range(1, len(chunks) + 1)}
        unknown = [m for m in markers_in(draft.text) if m not in valid]
        if unknown:
            return ValidationResult(
                passed=False,
                reason="unknown_marker",
                problems=[f"citation {m} does not match any supplied chunk" for m in unknown],
            )
        missing = _claims_without_citation(draft.text)
        if missing:
            return ValidationResult(
                passed=False,
                reason="uncited_claim",
                problems=[f"no citation for: {s[:120]}" for s in missing],
            )
        if not markers_in(draft.text):
            return ValidationResult(
                passed=False, reason="no_citations", problems=["the answer cites nothing"]
            )
        return ValidationResult(passed=True)


def run_validators(
    validators: list[Validator],
    question: str,
    draft: DraftAnswer,
    chunks: list[RetrievedChunk],
) -> ValidationResult:
    """Run validators in order and stop at the first failure."""
    for validator in validators:
        result = validator.validate(question, draft, chunks)
        if not result.passed:
            return result
    return ValidationResult(passed=True)


def decide_abstain(
    top_rerank_score: float | None,
    draft: DraftAnswer,
    validation: ValidationResult,
    threshold: float,
) -> tuple[bool, str]:
    """(abstained, reason). `top_rerank_score` is None when no reranker ran (SPEC 6.4)."""
    if top_rerank_score is not None and top_rerank_score < threshold:
        return True, "weak_evidence"
    if draft.insufficient:
        return True, "insufficient_evidence"
    if not validation.passed:
        return True, validation.reason or "validation_failed"
    return False, ""
