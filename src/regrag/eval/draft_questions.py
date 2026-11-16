"""Grow the golden set: draft questions from real passages, review them in Excel, accept.

1. Draft (uses the database and the LLM; about $0.03):
     uv run python -m regrag.eval.draft_questions draft --per-corpus 16 --tables 3
   Samples passages spread across documents (every document once before any repeats),
   asks the LLM for one question and a short answer from each passage only, adds a few
   hand-written questions of the kinds an LLM can't draft well (superseded, cross-corpus,
   should-refuse), and writes ONE review sheet together with the existing questions:
   data/raw/golden_review.csv (gitignored; opens in Excel).
2. Review: in Excel, put Y in the "keep" column for every row that is right. Edit the
   question or answer if needed, save as CSV.
3. Accept:
     uv run python -m regrag.eval.draft_questions accept
   Rows marked Y are written to data/golden/golden.jsonl with reviewed=true (existing rows
   are updated, not duplicated); the file is validated before it is saved.

Drafted rows carry section-level gold (doc, section, page) from the passage they came from,
which is what lets retrieval metrics tell the configurations apart.
"""

import argparse
import csv
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from regrag.eval.golden import GOLDEN_PATH, GoldenError, load_golden
from regrag.ingest.manifest import REPO_ROOT
from regrag.types import RetrievedChunk

REVIEW_PATH = REPO_ROOT / "data" / "raw" / "golden_review.csv"
REVIEW_COLUMNS = [
    "keep", "id", "type", "corpus", "question", "reference_answer", "expected_doc_ids",
    "section_no", "page", "should_abstain", "must_flag_supersession", "source", "excerpt",
]  # fmt: skip

DRAFT_SYSTEM = """You write test questions for a search system over Indian regulation.
Given ONE passage, write ONE question that a compliance analyst might ask and that this
passage answers completely, plus a short answer (1-2 sentences) using ONLY the passage.
The question must make sense without seeing the passage (name the topic, not "this passage").
Reply with ONLY JSON: {"question": "...", "answer": "..."}"""

# Kinds of question an LLM cannot draft from one passage. Written by hand; reviewed like
# every other row. Expected documents come from data/relations.csv and the manifest.
HANDWRITTEN = [
    {"type": "superseded", "corpus": "gst", "must_flag_supersession": True,
     "question": "How should a corporate guarantee between related persons be valued for GST "
                 "after Circular 204/16/2023-GST, and was that guidance later clarified?",
     "expected_doc_ids": ["gst-225-19-2024", "gst-204-16-2023"]},
    {"type": "superseded", "corpus": "rbi", "must_flag_supersession": True,
     "question": "Under the 2020 priority sector lending directions, what was the target for "
                 "lending to weaker sections, and what applies now?",
     "expected_doc_ids": ["rbi-12799", "rbi-11959"]},
    {"type": "superseded", "corpus": "gst", "must_flag_supersession": True,
     "question": "Is the guidance on input tax credit for warranty replacements in Circular "
                 "195/07/2023-GST still complete for extended warranties?",
     "expected_doc_ids": ["gst-216-10-2024", "gst-195-07-2023"]},
    {"type": "cross_corpus", "corpus": "both",
     "question": "How is TCS handled under GST when several e-commerce operators take part in one "
                 "transaction, and what must a payment aggregator do before onboarding merchants?",
     "expected_doc_ids": ["gst-194-06-2023", "rbi-12896"]},
    {"type": "abstain", "corpus": "gst", "should_abstain": True,
     "question": "What is the GST rate on restaurant services?"},
    {"type": "abstain", "corpus": "none", "should_abstain": True,
     "question": "What cash reserve ratio must banks currently maintain?"},
    {"type": "abstain", "corpus": "none", "should_abstain": True,
     "question": "What is the due date for filing GSTR-3B for October 2026?"},
    {"type": "abstain", "corpus": "none", "should_abstain": True,
     "question": "How does SEBI regulate investment advisers?"},
]  # fmt: skip


def spread_sample(chunks: list[RetrievedChunk], n: int, seed: int = 7) -> list[RetrievedChunk]:
    """n chunks, taking every document once before any document twice (round robin).

    Why: a plain random sample would mostly hit the longest directions (the KYC direction
    alone has 189 chunks) and leave short circulars untested."""
    rng = random.Random(seed)  # fixed seed: the same draft set every time
    by_doc: dict[str, list[RetrievedChunk]] = defaultdict(list)
    for chunk in chunks:
        by_doc[chunk.doc_id].append(chunk)
    for pool in by_doc.values():
        rng.shuffle(pool)
    order = sorted(by_doc)
    rng.shuffle(order)
    picked: list[RetrievedChunk] = []
    while len(picked) < n and any(by_doc[d] for d in order):
        for doc_id in order:
            if by_doc[doc_id] and len(picked) < n:
                picked.append(by_doc[doc_id].pop())
    return picked


def parse_draft(reply: str) -> tuple[str, str] | None:
    match = re.search(r"\{.*\}", reply, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    question, answer = str(data.get("question", "")).strip(), str(data.get("answer", "")).strip()
    if len(question.split()) < 5 or not answer or "passage" in question.lower():
        return None
    return question, answer


def draft_rows(chunks: list[RetrievedChunk], llm, kind_for: dict[int, str]) -> list[dict]:
    """One review row per passage the LLM drafted a usable question for."""
    rows = []
    for chunk in chunks:
        user = f"PASSAGE (from {chunk.title}, {chunk.section_no}):\n{chunk.content}"
        try:
            reply, _ = llm.complete(DRAFT_SYSTEM, user, max_tokens=300)
        except Exception:  # one failed call just means one fewer draft
            continue
        parsed = parse_draft(reply)
        if parsed is None:
            continue
        question, answer = parsed
        rows.append({
            "keep": "", "id": "", "type": kind_for.get(chunk.chunk_id, "factual"),
            "corpus": chunk.corpus, "question": question, "reference_answer": answer,
            "expected_doc_ids": chunk.doc_id, "section_no": chunk.section_no,
            "page": chunk.page_start, "should_abstain": "N", "must_flag_supersession": "N",
            "source": "llm_drafted", "excerpt": re.sub(r"\s+", " ", chunk.content)[:700],
        })  # fmt: skip
    return rows


def existing_rows(golden_path: Path) -> list[dict]:
    """The current golden rows, as review rows (so they get reviewed in the same sheet)."""
    rows = []
    for item in load_golden(golden_path, include_unreviewed=True):
        section = item.expected_sections[0] if item.expected_sections else {}
        rows.append({
            "keep": "Y" if item.reviewed else "", "id": item.id, "type": item.type,
            "corpus": item.corpus, "question": item.question,
            "reference_answer": item.reference_answer,
            "expected_doc_ids": ";".join(item.expected_doc_ids),
            "section_no": section.get("section_no", ""), "page": section.get("page", ""),
            "should_abstain": "Y" if item.should_abstain else "N",
            "must_flag_supersession": "Y" if item.must_flag_supersession else "N",
            "source": item.source, "excerpt": "",
        })  # fmt: skip
    return rows


def handwritten_rows() -> list[dict]:
    return [
        {
            "keep": "",
            "id": "",
            "type": h["type"],
            "corpus": h["corpus"],
            "question": h["question"],
            "reference_answer": "Should abstain: not in the corpus."
            if h.get("should_abstain")
            else "",
            "expected_doc_ids": ";".join(h.get("expected_doc_ids", [])),
            "section_no": "",
            "page": "",
            "should_abstain": "Y" if h.get("should_abstain") else "N",
            "must_flag_supersession": "Y" if h.get("must_flag_supersession") else "N",
            "source": "manual",
            "excerpt": "",
        }  # fmt: skip
        for h in HANDWRITTEN
    ]


def write_review(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: Excel then shows characters like "–" and "₹" correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _yes(value: str) -> bool:
    return str(value).strip().lower() in ("y", "yes", "true", "1")


def accept(review_path: Path, golden_path: Path) -> tuple[int, int]:
    """Write the kept rows to the golden set. Returns (rows kept, rows written in total)."""
    with open(review_path, encoding="utf-8-sig", newline="") as f:
        review = list(csv.DictReader(f))
    existing = {}
    if golden_path.exists():
        for line in golden_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                existing[row["id"]] = row
    next_number = max((int(i[1:]) for i in existing if re.fullmatch(r"g\d+", i)), default=0) + 1
    kept = 0
    for r in review:
        if not _yes(r.get("keep", "")):
            continue
        kept += 1
        abstain = _yes(r["should_abstain"])
        docs = [d for d in r["expected_doc_ids"].split(";") if d.strip()] if not abstain else []
        sections = []
        if docs and r.get("section_no", "").strip():
            page = str(r.get("page", "")).strip()
            sections = [{"doc_id": docs[0], "section_no": r["section_no"].strip(),
                         "page": int(page) if page.isdigit() else None}]  # fmt: skip
        row_id = r["id"].strip() or f"g{next_number:03d}"
        if not r["id"].strip():
            next_number += 1
        base = existing.get(row_id, {})
        sections = sections or base.get("expected_sections", [])
        existing[row_id] = {
            **base,
            "id": row_id, "schema_version": 1, "question": r["question"].strip(),
            "corpus": r["corpus"].strip(), "type": r["type"].strip(),
            "expected_doc_ids": docs, "expected_sections": sections,
            "reference_answer": r["reference_answer"].strip(), "should_abstain": abstain,
            "must_flag_supersession": _yes(r["must_flag_supersession"]),
            "tags": base.get("tags", []), "source": r["source"].strip() or "manual",
            "reviewed": True,
        }  # fmt: skip
    rows = sorted(existing.values(), key=lambda row: row["id"])
    tmp = golden_path.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    try:
        load_golden(tmp, include_unreviewed=True)  # validate before replacing the real file
    except GoldenError:
        tmp.unlink()
        raise
    tmp.replace(golden_path)
    return kept, len(rows)


def _candidates(conn) -> list[RetrievedChunk]:
    from psycopg.rows import dict_row

    from regrag.db.repository import RETRIEVED_COLUMNS, row_to_retrieved

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {RETRIEVED_COLUMNS} FROM chunks c JOIN documents d USING (doc_id) "
            "WHERE c.token_count >= 120 AND coalesce(c.section_no, '') <> 'Preamble' "
            "AND d.status = 'active' ORDER BY c.chunk_id"
        )
        return [row_to_retrieved(r) for r in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft, review and accept golden questions")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--per-corpus", type=int, default=16, help="text passages per corpus")
    d.add_argument("--tables", type=int, default=3, help="table passages in total")
    d.add_argument("--out", type=Path, default=REVIEW_PATH)
    a = sub.add_parser("accept")
    a.add_argument("--review", type=Path, default=REVIEW_PATH)
    a.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    if args.command == "accept":
        kept, total = accept(args.review, args.golden)
        print(f"Kept {kept} reviewed rows; golden set now has {total} rows: {args.golden}")
        return 0

    from regrag.bedrock.client import get_runtime_client
    from regrag.bedrock.llm import BedrockLLM
    from regrag.config import get_settings
    from regrag.db.connection import connect

    settings = get_settings()
    with connect(settings) as conn:
        candidates = _candidates(conn)
    picked: list[RetrievedChunk] = []
    kinds: dict[int, str] = {}
    for corpus in ("rbi", "gst"):
        text = [c for c in candidates if c.corpus == corpus and c.content_type == "text"]
        picked += spread_sample(text, args.per_corpus)
    tables = spread_sample([c for c in candidates if c.content_type == "table"], args.tables)
    kinds.update({c.chunk_id: "table" for c in tables})
    picked += tables
    llm = BedrockLLM(get_runtime_client(settings), settings.bedrock_llm_model_id)
    print(f"Drafting from {len(picked)} passages...", flush=True)
    drafted = draft_rows(picked, llm, kinds)
    rows = existing_rows(GOLDEN_PATH) + handwritten_rows() + drafted
    write_review(args.out, rows)
    print(
        f"Review sheet: {args.out}  ({len(rows)} rows: existing, {len(HANDWRITTEN)} hand-written, "
        f"{len(drafted)} drafted). Mark keep = Y, save as CSV, then run the accept command."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
