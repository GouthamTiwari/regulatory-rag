"""Load and validate the golden question set, data/golden/golden.jsonl (SPEC section 6.1).

The schema is stable: later projects read and extend this file. New fields may be added,
so unknown fields are kept (in `extra`), never rejected. Only rows a human has reviewed
count in results; drafts stay `reviewed: false` until then.

Check with:  uv run python -m regrag.eval.golden --check [--include-unreviewed]
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from regrag.ingest.manifest import MANIFEST_PATH, REPO_ROOT, load_manifest

GOLDEN_PATH = REPO_ROOT / "data" / "golden" / "golden.jsonl"
SCHEMA_VERSION = 1
CORPORA = {"rbi", "gst", "both", "none"}
TYPES = {"factual", "table", "cross_corpus", "superseded", "abstain"}
SOURCES = {"manual", "llm_drafted"}
REQUIRED = {
    "id": str,
    "schema_version": int,
    "question": str,
    "corpus": str,
    "type": str,
    "expected_doc_ids": list,
    "expected_sections": list,
    "reference_answer": str,
    "should_abstain": bool,
    "must_flag_supersession": bool,
    "tags": list,
    "source": str,
    "reviewed": bool,
}


class GoldenError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass
class GoldenItem:
    id: str
    question: str
    corpus: str
    type: str
    expected_doc_ids: list[str]
    expected_sections: list[dict[str, Any]]
    reference_answer: str
    should_abstain: bool
    must_flag_supersession: bool
    tags: list[str]
    source: str
    reviewed: bool
    schema_version: int = SCHEMA_VERSION
    extra: dict[str, Any] = field(default_factory=dict)  # fields added by later versions


def _problems_for(row: dict[str, Any], known_doc_ids: set[str] | None) -> list[str]:
    problems = []
    for name, kind in REQUIRED.items():
        if name not in row:
            problems.append(f"missing field '{name}'")
        elif not isinstance(row[name], kind) or (kind is int and isinstance(row[name], bool)):
            problems.append(f"'{name}' must be a {kind.__name__}")
    if problems:
        return problems
    if row["schema_version"] != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    if not row["question"].strip():
        problems.append("question is empty")
    if row["corpus"] not in CORPORA:
        problems.append(f"corpus must be one of {sorted(CORPORA)}")
    if row["type"] not in TYPES:
        problems.append(f"type must be one of {sorted(TYPES)}")
    if row["source"] not in SOURCES:
        problems.append(f"source must be one of {sorted(SOURCES)}")
    if row["should_abstain"] and row["expected_doc_ids"]:
        # Why: an abstain question has no right document; listing one would make the
        # retrieval metrics reward finding something that should not be used.
        problems.append("abstain rows must have empty expected_doc_ids")
    if not row["should_abstain"] and not row["expected_doc_ids"]:
        problems.append("answerable rows need at least one expected_doc_id")
    if (row["type"] == "abstain") != row["should_abstain"]:
        problems.append("type 'abstain' and should_abstain must agree")
    for section in row["expected_sections"]:
        if not isinstance(section, dict) or "doc_id" not in section:
            problems.append("each expected_section needs a doc_id")
        elif section["doc_id"] not in row["expected_doc_ids"]:
            problems.append(f"expected_section doc {section['doc_id']} not in expected_doc_ids")
    if known_doc_ids is not None:
        unknown = [d for d in row["expected_doc_ids"] if d not in known_doc_ids]
        if unknown:
            problems.append(f"expected_doc_ids not in the manifest: {unknown}")
    return problems


def load_golden(
    path: Path = GOLDEN_PATH,
    *,
    include_unreviewed: bool = False,
    known_doc_ids: set[str] | None = None,
) -> list[GoldenItem]:
    """Validate every row, then return the usable ones (reviewed only, by default)."""
    problems: list[str] = []
    items: list[GoldenItem] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"line {line_no}: not valid JSON ({exc.msg})")
                continue
            row_problems = _problems_for(row, known_doc_ids)
            if isinstance(row.get("id"), str):
                if row["id"] in seen:
                    row_problems.append("duplicate id")
                seen.add(row["id"])
            if row_problems:
                problems.extend(f"line {line_no} ({row.get('id', '?')}): {p}" for p in row_problems)
                continue
            known = {k: row[k] for k in REQUIRED}
            extra = {k: v for k, v in row.items() if k not in REQUIRED}
            items.append(GoldenItem(**known, extra=extra))
    if problems:
        raise GoldenError(problems)
    return [i for i in items if include_unreviewed or i.reviewed]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate data/golden/golden.jsonl")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--include-unreviewed", action="store_true")
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    args = parser.parse_args(argv)
    known = {r.doc_id for r in load_manifest().rows} if MANIFEST_PATH.exists() else None
    try:
        everything = load_golden(args.golden, include_unreviewed=True, known_doc_ids=known)
    except GoldenError as exc:
        print(f"Golden set check FAILED:\n{exc}", file=sys.stderr)
        return 1
    usable = [i for i in everything if args.include_unreviewed or i.reviewed]
    print(
        f"Rows: {len(everything)}  reviewed: {sum(i.reviewed for i in everything)}  "
        f"usable now: {len(usable)}"
    )
    print(f"By type: {dict(sorted(Counter(i.type for i in everything).items()))}")
    print(f"By corpus: {dict(sorted(Counter(i.corpus for i in everything).items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
