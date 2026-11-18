"""The web page: display helpers, plus one smoke run of the Streamlit script."""

from pathlib import Path

import pytest

from regrag.types import Citation, QueryResult
from regrag.ui.view import (
    CONFIG_LABELS,
    abstain_explanation,
    pages_label,
    source_cards,
    stats,
)

APP = Path(__file__).parents[2] / "src" / "regrag" / "ui" / "app.py"


def result(**overrides) -> QueryResult:
    values = dict(
        query_id="q1",
        question="Can a car dealer claim ITC on demo vehicles?",
        route="gst",
        config_name="hybrid_rerank",
        answer="Yes, when the vehicle is used for further supply [C1].",
        citations=[
            Citation("C1", "gst-231-25-2024", "Circular 231/25/2024-GST", "Para 4", 2, 2, "u1"),
            Citation("C2", "rbi-1", "Old PSL direction", "", 3, 5, "u2", status="superseded"),
        ],
        cost_usd=0.0017,
        latency_ms={"total": 24900.0},
    )
    values.update(overrides)
    return QueryResult(**values)


def test_pages_label():
    assert pages_label(2, 2) == "p. 2"
    assert pages_label(3, 5) == "pp. 3-5"


def test_source_cards_show_section_pages_and_outdated_flag():
    first, second = source_cards(result())
    assert first.location == "Para 4 | p. 2" and not first.outdated
    assert second.location == "pp. 3-5" and second.outdated  # no section label available


def test_stats_are_human_readable():
    assert stats(result()) == [
        ("Searched", "GST"),
        ("Search setup", CONFIG_LABELS["hybrid_rerank"]),
        ("Time", "24.9 s"),
        ("Cost", "$0.00170"),
    ]


def test_unknown_abstain_reason_still_explained():
    assert "too low" in abstain_explanation("weak_evidence")
    assert "odd_code" in abstain_explanation("odd_code")


def test_config_labels_cover_every_config():
    from regrag.types import CONFIG_NAMES

    assert set(CONFIG_LABELS) == set(CONFIG_NAMES)


def test_app_answers_a_question_without_aws_or_db(monkeypatch):
    # The script imports these names at run time, so patching the module is enough.
    testing = pytest.importorskip("streamlit.testing.v1")
    import regrag.query.pipeline as pipeline

    monkeypatch.setattr(pipeline, "build_pipeline", lambda config: object())
    monkeypatch.setattr(pipeline, "answer_question", lambda q, config, parts: result(question=q))

    app = testing.AppTest.from_file(str(APP), default_timeout=30).run()
    app.text_area(key="question").input("Demo vehicles?")
    next(b for b in app.button if b.label == "Ask").click().run()

    assert not app.exception
    assert any("further supply" in m.value for m in app.markdown)
    assert any("Circular 231/25/2024-GST" in m.value for m in app.markdown)


def test_app_shows_a_refusal_warning(monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")
    import regrag.query.pipeline as pipeline

    refused = result(abstained=True, abstain_reason="weak_evidence", citations=[])
    monkeypatch.setattr(pipeline, "build_pipeline", lambda config: object())
    monkeypatch.setattr(pipeline, "answer_question", lambda q, config, parts: refused)

    app = testing.AppTest.from_file(str(APP), default_timeout=30).run()
    app.text_area(key="question").input("Income tax rate?")
    next(b for b in app.button if b.label == "Ask").click().run()

    assert not app.exception
    assert "No answer given" in app.warning[0].value
    assert not any(m.value == "Sources" for m in app.subheader)
