"""Evaluation metrics, exactly as defined in SPEC section 6.3. Pure functions: no I/O.

Conventions:
- Retrieval metrics are computed per question and averaged by the caller (`mean`), using
  only questions that should be answered.
- A metric that cannot be defined for an input returns None (not 0), so a missing value
  is never mistaken for a bad score. `mean` skips None.
"""

import math

from regrag.eval.golden import GoldenItem
from regrag.types import ChunkRef


def is_relevant(chunk: ChunkRef, item: GoldenItem) -> bool:
    """A chunk is relevant if it matches an expected section, or, when the question lists
    no sections, if it comes from an expected document."""
    if not item.expected_sections:
        return chunk.doc_id in item.expected_doc_ids
    chunk_section = chunk.section_no.lower()
    for expected in item.expected_sections:
        wanted = str(expected.get("section_no", "")).lower()
        if expected["doc_id"] == chunk.doc_id and (not wanted or wanted in chunk_section):
            return True
    return False


def recall_at_k(ranked: list[ChunkRef], item: GoldenItem, k: int) -> int:
    """1 if any relevant chunk is in the top k, else 0 (a "hit rate", SPEC 6.3)."""
    return int(any(is_relevant(c, item) for c in ranked[:k]))


def mrr(ranked: list[ChunkRef], item: GoldenItem, k: int = 10) -> float:
    """1 / rank of the first relevant chunk within the top k, or 0 if none."""
    for rank, chunk in enumerate(ranked[:k], start=1):
        if is_relevant(chunk, item):
            return 1.0 / rank
    return 0.0


def citation_validity(answers: list[tuple[list[str], int]]) -> float:
    """Of all citation markers in all non-abstained answers, the share that point to a chunk
    actually given to the model. Input: (markers used, number of chunks supplied) per answer.
    No citations at all counts as fully valid (1.0): nothing was invented."""
    total = valid = 0
    for markers, supplied in answers:
        for marker in markers:
            total += 1
            number = marker[1:] if marker.startswith("C") else ""
            valid += number.isdigit() and 1 <= int(number) <= supplied
    return valid / total if total else 1.0


def citation_accuracy(answers: list[tuple[list[str], list[str]]]) -> float | None:
    """Of all cited chunks, the share whose document is one the question expects.
    Input: (doc_ids of the cited chunks, expected doc_ids) per answer.
    None when nothing was cited (the metric is then excluded, not zero)."""
    total = correct = 0
    for cited_docs, expected in answers:
        for doc_id in cited_docs:
            total += 1
            correct += doc_id in expected
    return correct / total if total else None


def abstention_scores(pairs: list[tuple[bool, bool]]) -> dict[str, float | None]:
    """Input: (abstained, should_abstain) per question.

    accuracy  = share of questions where abstained == should_abstain
    precision = of the abstentions, the share that were right (None if it never abstained)
    recall    = of the questions that should abstain, the share it did (None if none should)
    Why all three: abstaining on everything gives perfect recall and is useless.
    """
    if not pairs:
        return {"accuracy": None, "precision": None, "recall": None}
    true_pos = sum(a and s for a, s in pairs)
    abstained = sum(a for a, _ in pairs)
    should = sum(s for _, s in pairs)
    return {
        "accuracy": sum(a == s for a, s in pairs) / len(pairs),
        "precision": true_pos / abstained if abstained else None,
        "recall": true_pos / should if should else None,
    }


def supersession_flag_rate(rows: list[tuple[bool, bool]]) -> float | None:
    """Input: (answer had supersession notes, question must flag supersession).
    Share of must-flag questions whose answer carried a note; None if there are none."""
    flagged = [has_note for has_note, must in rows if must]
    return sum(flagged) / len(flagged) if flagged else None


def latency_summary(values_ms: list[float]) -> dict[str, float | None]:
    """Mean and 95th percentile (nearest-rank method) of latencies in milliseconds."""
    if not values_ms:
        return {"mean": None, "p95": None}
    ordered = sorted(values_ms)
    rank = math.ceil(0.95 * len(ordered))  # nearest rank, 1-based
    return {"mean": sum(ordered) / len(ordered), "p95": ordered[rank - 1]}


def mean(values: list[float | None]) -> float | None:
    """Average ignoring None; None if nothing is left."""
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None
