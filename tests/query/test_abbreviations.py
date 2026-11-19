"""Abbreviation expansion before routing and search."""

from regrag.query.abbreviations import GLOSSARY, expand_abbreviations
from regrag.query.pipeline import Parts, answer_question
from regrag.query.router import rule_route
from regrag.types import DraftAnswer
from tests.fakes import FakeReranker, FakeRetriever, FakeRouter, make_chunk
from tests.query.test_pipeline import MODEL_IDS, SETTINGS


def test_bare_abbreviation_gets_its_full_form():
    assert expand_abbreviations("What is RCM?") == "What is RCM (reverse charge mechanism)?"


def test_expansion_lets_the_rules_route_to_gst():
    assert rule_route("What is RCM?") is None  # the gap that sent RCM to "both"
    assert rule_route(expand_abbreviations("What is RCM?")) == "gst"


def test_plural_and_several_abbreviations():
    assert expand_abbreviations("Do NBFCs need KYC?") == (
        "Do NBFCs (non-banking financial company) need KYC (know your customer)?"
    )


def test_only_first_use_is_expanded():
    assert expand_abbreviations("PSL target vs PSL sub-target") == (
        "PSL (priority sector lending) target vs PSL sub-target"
    )


def test_full_form_already_present_is_left_alone():
    question = "Is input tax credit (ITC) available on demo cars?"
    assert expand_abbreviations(question) == question


def test_lower_case_words_and_word_parts_are_not_touched():
    assert expand_abbreviations("emi and apr in lower case, ITCs vs ITCX") == (
        "emi and apr in lower case, ITCs (input tax credit) vs ITCX"
    )


def test_glossary_keys_are_upper_case_abbreviations():
    assert all(key.isupper() and key.isalpha() for key in GLOSSARY)


class RecordingGenerator:
    def __init__(self):
        self.questions: list[str] = []

    def generate(self, question, chunks):
        self.questions.append(question)
        return DraftAnswer(text="The recipient pays the tax [C1].", markers=["C1"])


def test_pipeline_searches_with_full_form_but_returns_the_typed_question():
    router, retriever = FakeRouter("gst"), FakeRetriever([make_chunk(1, corpus="gst")])
    generator = RecordingGenerator()
    parts = Parts(
        settings=SETTINGS,
        router=router,
        retriever=retriever,
        reranker=FakeReranker(scores={1: 0.9}),
        generator=generator,
        retry_generator=generator,
        validators=[],
        model_ids=MODEL_IDS,
    )
    result = answer_question("What is RCM?", parts=parts, log=False)
    assert router.calls == ["What is RCM (reverse charge mechanism)?"]
    assert retriever.calls[0][0] == "What is RCM (reverse charge mechanism)?"
    assert generator.questions == ["What is RCM (reverse charge mechanism)?"]
    assert result.question == "What is RCM?"
