"""Citation validation and the abstain decision."""

import pytest

from regrag.interfaces import Validator
from regrag.query.validate import (
    CitationValidator,
    decide_abstain,
    markers_in,
    run_validators,
)
from regrag.types import DraftAnswer, ValidationResult
from tests.fakes import FakeValidator, make_chunk

CHUNKS = [make_chunk(1), make_chunk(2)]
QUESTION = "Can a dealer claim ITC on demo vehicles?"


def check(text: str, chunks=CHUNKS) -> ValidationResult:
    return CitationValidator().validate(QUESTION, DraftAnswer(text=text), chunks)


def test_clean_answer_passes():
    text = (
        "Yes. Input tax credit is available on demo vehicles used to promote sales [C1]. "
        "The vehicle must be capitalised in the books of the dealer [C1][C2].\n"
        "This is not legal or tax advice."
    )
    assert check(text).passed


def test_unknown_marker_fails():
    result = check("Input tax credit is available on demo vehicles [C3].")
    assert not result.passed and result.reason == "unknown_marker"
    assert "C3" in result.problems[0]


def test_rule_sentence_without_a_marker_fails():
    text = (
        "Input tax credit is available on demo vehicles [C1]. "
        "However, credit is not available if the vehicle is used for personal travel."
    )
    result = check(text)
    assert not result.passed and result.reason == "uncited_claim"
    assert "personal travel" in result.problems[0]


def test_answer_without_any_citation_fails():
    result = check("Yes, that is right, according to the circular on this topic.")
    assert not result.passed and result.reason == "no_citations"


def test_insufficient_draft_is_not_checked():
    draft = DraftAnswer(text="INSUFFICIENT_EVIDENCE", insufficient=True)
    assert CitationValidator().validate(QUESTION, draft, CHUNKS).passed


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A [C1]. B [C2][C3]. C [C1, C4].", ["C1", "C2", "C3", "C4"]),
        ("No markers here.", []),
    ],
)
def test_markers_in(text, expected):
    assert markers_in(text) == expected


# --- decide_abstain --------------------------------------------------------------------------

OK = ValidationResult(passed=True)
CLEAN = DraftAnswer(text="Rule [C1].")


def test_low_rerank_score_abstains_as_weak_evidence():
    assert decide_abstain(0.29, CLEAN, OK, threshold=0.30) == (True, "weak_evidence")


def test_score_at_threshold_does_not_abstain():
    assert decide_abstain(0.30, CLEAN, OK, threshold=0.30) == (False, "")


def test_no_reranker_means_no_threshold_rule():
    assert decide_abstain(None, CLEAN, OK, threshold=0.30) == (False, "")


def test_model_saying_insufficient_abstains():
    draft = DraftAnswer(text="INSUFFICIENT_EVIDENCE", insufficient=True)
    assert decide_abstain(None, draft, OK, threshold=0.30) == (True, "insufficient_evidence")


def test_failed_validation_abstains_with_its_reason():
    failed = ValidationResult(passed=False, reason="unknown_marker")
    assert decide_abstain(0.9, CLEAN, failed, threshold=0.30) == (True, "unknown_marker")


# --- run_validators (the guardrails plug-in point) ---------------------------------------------


def test_a_second_validator_can_force_abstention():
    guardrail = FakeValidator(passed=False, reason="guardrail_blocked")
    result = run_validators([CitationValidator(), guardrail], QUESTION, CLEAN, CHUNKS)
    assert result.reason == "guardrail_blocked"
    assert decide_abstain(0.9, CLEAN, result, threshold=0.3) == (True, "guardrail_blocked")


def test_validators_stop_at_the_first_failure():
    first = FakeValidator(passed=False, reason="first")
    second = FakeValidator(passed=False, reason="second")
    assert run_validators([first, second], QUESTION, CLEAN, CHUNKS).reason == "first"
    assert second.calls == []


def test_citation_validator_satisfies_the_protocol():
    assert isinstance(CitationValidator(), Validator)
