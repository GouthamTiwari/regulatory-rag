"""Turn a QueryResult into the plain pieces the web page shows.

Kept free of Streamlit on purpose: the page logic can then be unit-tested like the rest of
the code, and the Streamlit file stays a thin layout layer.
"""

from dataclasses import dataclass

from regrag.query.prompts import STATUTE_DOC_IDS
from regrag.types import QueryResult

# Order matters: the first entry is the default in the dropdown.
CONFIG_LABELS = {
    "hybrid_rerank": "Hybrid + rerank (best answers, slower)",
    "hybrid": "Hybrid: keyword + vector",
    "vector": "Vector only",
    "bm25": "Keyword only",
}

ROUTE_LABELS = {"rbi": "RBI", "gst": "GST", "both": "RBI + GST"}

# Friendly wording for the reason codes from query.validate.decide_abstain.
ABSTAIN_LABELS = {
    "weak_evidence": "The best matching passages scored too low to answer safely.",
    "insufficient_evidence": "The passages found do not contain the answer.",
    "unknown_marker": "The draft answer cited a source that was not retrieved.",
}

EXAMPLE_QUESTIONS = [
    "Can a car dealer claim input tax credit on demo vehicles?",
    "Under the 2020 Priority Sector Lending Master Direction, what is the overall PSL target "
    "for a domestic commercial bank?",
    "Which documents can a bank accept as officially valid documents for KYC?",
    "What is the income tax rate for a salaried individual?",
]


@dataclass(frozen=True)
class SourceCard:
    marker: str  # "C1", matches the [C1] in the answer text
    title: str
    location: str  # "Para 4 | p. 2"
    url: str
    outdated: bool  # the cited document is superseded or withdrawn


def pages_label(start: int, end: int) -> str:
    return f"p. {start}" if start == end else f"pp. {start}-{end}"


def _location(c) -> str:
    """Section and pages; for the bare law, the section alone (its "pages" are positions)."""
    if c.doc_id in STATUTE_DOC_IDS:
        return c.section_no
    if c.section_no:
        return f"{c.section_no} | {pages_label(c.page_start, c.page_end)}"
    return pages_label(c.page_start, c.page_end)


def source_cards(result: QueryResult) -> list[SourceCard]:
    return [
        SourceCard(
            marker=c.marker,
            title=c.title,
            location=_location(c),
            url=c.source_url,
            outdated=c.status != "active",
        )
        for c in result.citations
    ]


def abstain_explanation(reason: str) -> str:
    return ABSTAIN_LABELS.get(reason, f"The answer did not pass the checks ({reason}).")


def stats(result: QueryResult) -> list[tuple[str, str]]:
    """Small label/value pairs shown under the answer."""
    seconds = result.latency_ms.get("total", 0) / 1000
    return [
        ("Searched", ROUTE_LABELS.get(result.route, result.route)),
        ("Search setup", CONFIG_LABELS.get(result.config_name, result.config_name)),
        ("Time", f"{seconds:.1f} s"),
        ("Cost", f"${result.cost_usd:.5f}"),
    ]
