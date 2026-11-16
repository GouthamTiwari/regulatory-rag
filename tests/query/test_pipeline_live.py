"""End-to-end against real Bedrock and the ingested database (marked live and db).

Run on purpose only:  uv run pytest -m "live and db" tests/query/test_pipeline_live.py -s
"""

import pytest

from regrag.query.pipeline import answer_question
from regrag.types import PipelineConfig

pytestmark = [pytest.mark.live, pytest.mark.db]


@pytest.fixture(scope="module")
def ready():
    from regrag.bedrock.client import BedrockAuthError, auth_mode
    from regrag.config import get_settings
    from regrag.db.connection import connect

    try:
        auth_mode(get_settings())
        with connect() as conn:
            stored = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    except (BedrockAuthError, RuntimeError) as exc:
        pytest.skip(str(exc))
    if stored == 0:
        pytest.skip("the corpus is not ingested yet")


def test_demo_vehicle_question_is_answered_with_the_right_citation(ready):
    result = answer_question(
        "Can a car dealer claim input tax credit on demo vehicles?",
        config=PipelineConfig(name="hybrid_rerank"),
    )
    print(
        f"\n{result.answer}\ncited={[c.doc_id for c in result.citations]} "
        f"score={result.rerank_top_score} cost=${result.cost_usd:.5f} "
        f"time={result.latency_ms['total']}ms"
    )
    assert not result.abstained, result.abstain_reason
    assert "gst-231-25-2024" in {c.doc_id for c in result.citations}


def test_income_tax_question_is_refused(ready):
    result = answer_question(
        "What TDS rate applies to fixed deposit interest under the Income-tax Act?",
        config=PipelineConfig(name="hybrid_rerank"),
    )
    print(
        f"\nabstained={result.abstained} reason={result.abstain_reason} "
        f"score={result.rerank_top_score}"
    )
    assert result.abstained
