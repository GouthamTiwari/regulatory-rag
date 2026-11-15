"""Load and validate data/manifest.csv and data/relations.csv (SPEC sections 3 and 5).

The manifest is the list of documents we are allowed to ingest. Validation runs over every
row and reports *all* problems at once, so a bad edit is fixed in one pass, not one error at
a time. Run a check with:  uv run python -m regrag.ingest.manifest --check
"""

import argparse
import csv
import re
import sys
import warnings
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from regrag.config import Settings, get_settings
from regrag.types import ManifestRow, Relation

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "data" / "manifest.csv"
RELATIONS_PATH = REPO_ROOT / "data" / "relations.csv"

MANIFEST_COLUMNS = (
    "doc_id",
    "corpus",
    "doc_type",
    "title",
    "reference_no",
    "applies_to",
    "publish_date",
    "updated_as_on",
    "source_url",
    "pdf_url",
    "status",
    "sha256",
)
RELATION_COLUMNS = ("from_doc_id", "relation", "to_doc_ref", "to_doc_id", "scope_note", "evidence")

CORPORA = {"rbi", "gst"}
STATUSES = {"active", "superseded", "withdrawn"}
TO_VERIFY = "to_verify"  # a row whose URL is not confirmed yet: skipped, never ingested
RELATION_TYPES = {"supersedes", "amends", "withdraws", "clarifies", "corrects"}
# Lowercase slug that starts with its corpus, e.g. rbi-13141 or gst-231-25-2024.
DOC_ID = re.compile(r"^(rbi|gst)-[a-z0-9]+(-[a-z0-9]+)*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """Raised with every problem found, one per line, each naming its CSV line number."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass
class ManifestResult:
    rows: list[ManifestRow]
    skipped: list[str] = field(default_factory=list)  # doc_ids with status to_verify


def is_allowed_host(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    """True for https URLs on an allowed host or one of its subdomains.

    Why the dot check: "www.rbi.org.in" must pass, but a look-alike such as
    "rbi.org.in.evil.example" or "fakerbi.org.in" must not.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    return any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)  # YYYY-MM-DD only; raises ValueError otherwise


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[tuple[int, dict[str, str]]]:
    # utf-8-sig: tolerates the invisible BOM that Excel adds when it saves a CSV.
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise ManifestError([f"{path.name}: missing column(s): {', '.join(missing)}"])
        # Line numbers start at 2 because line 1 is the header.
        return [
            (i, {k: (v or "").strip() for k, v in row.items() if k})
            for i, row in enumerate(reader, start=2)
        ]


def load_manifest(path: Path = MANIFEST_PATH, settings: Settings | None = None) -> ManifestResult:
    settings = settings or get_settings()
    problems: list[str] = []
    rows: list[ManifestRow] = []
    skipped: list[str] = []
    seen: set[str] = set()

    for line, r in _read_csv(path, MANIFEST_COLUMNS):
        where = f"{path.name} line {line} ({r.get('doc_id') or '?'})"
        row_problems: list[str] = []

        doc_id = r["doc_id"]
        if not DOC_ID.match(doc_id):
            row_problems.append("doc_id must look like rbi-13141 or gst-231-25-2024")
        elif doc_id in seen:
            row_problems.append("duplicate doc_id")
        seen.add(doc_id)

        if r["corpus"] not in CORPORA:
            row_problems.append(f"corpus must be one of {sorted(CORPORA)}")
        elif not doc_id.startswith(r["corpus"] + "-"):
            row_problems.append("doc_id must start with its corpus")

        status = r["status"]
        if status == TO_VERIFY:
            # Not an error: the row is parked until a human confirms the URL.
            skipped.append(doc_id)
            continue
        if status not in STATUSES:
            row_problems.append(f"status must be one of {sorted(STATUSES | {TO_VERIFY})}")

        for required in ("title", "publish_date", "source_url", "pdf_url"):
            if not r[required]:
                row_problems.append(f"{required} is empty")
        for url_field in ("source_url", "pdf_url"):
            if r[url_field] and not is_allowed_host(r[url_field], settings.allowed_download_hosts):
                row_problems.append(f"{url_field} is not an https URL on an official host")

        publish_date = updated_as_on = None
        try:
            publish_date = _parse_date(r["publish_date"]) if r["publish_date"] else None
            updated_as_on = _parse_date(r["updated_as_on"]) if r["updated_as_on"] else None
        except ValueError:
            row_problems.append("dates must be YYYY-MM-DD")
        if publish_date and updated_as_on and updated_as_on < publish_date:
            row_problems.append("updated_as_on is before publish_date")

        if r["sha256"] and not SHA256.match(r["sha256"]):
            row_problems.append("sha256 must be 64 lowercase hex characters or empty")

        if row_problems:
            problems.extend(f"{where}: {p}" for p in row_problems)
            continue
        rows.append(
            ManifestRow(
                doc_id=doc_id,
                corpus=r["corpus"],
                doc_type=r["doc_type"],
                title=r["title"],
                reference_no=r["reference_no"],
                applies_to=r["applies_to"],
                publish_date=publish_date,
                source_url=r["source_url"],
                pdf_url=r["pdf_url"],
                status=status,
                updated_as_on=updated_as_on,
                sha256=r["sha256"],
            )
        )

    if problems:
        raise ManifestError(problems)
    for doc_id in skipped:
        # stacklevel=2: the warning points at the caller, which is more useful to read.
        warnings.warn(
            f"{doc_id}: status '{TO_VERIFY}', skipped until its URL is confirmed", stacklevel=2
        )
    return ManifestResult(rows=rows, skipped=skipped)


def load_relations(
    path: Path = RELATIONS_PATH, known_doc_ids: set[str] | None = None
) -> list[Relation]:
    """Hand-curated links (SPEC 3.4, source 1). Trusted, so they count as reviewed."""
    problems: list[str] = []
    relations: list[Relation] = []
    for line, r in _read_csv(path, RELATION_COLUMNS):
        where = f"{path.name} line {line}"
        row_problems = []
        if r["relation"] not in RELATION_TYPES:
            row_problems.append(f"relation must be one of {sorted(RELATION_TYPES)}")
        if not r["to_doc_ref"]:
            row_problems.append("to_doc_ref is empty")
        if not r["evidence"]:
            # Why required: a wrong "superseded" flag misleads users, so every manual link
            # must say where it came from.
            row_problems.append("evidence is empty")
        if known_doc_ids is not None:
            if r["from_doc_id"] not in known_doc_ids:
                row_problems.append(f"from_doc_id {r['from_doc_id']!r} is not in the manifest")
            if r["to_doc_id"] and r["to_doc_id"] not in known_doc_ids:
                row_problems.append(f"to_doc_id {r['to_doc_id']!r} is not in the manifest")
        if row_problems:
            problems.extend(f"{where}: {p}" for p in row_problems)
            continue
        relations.append(
            Relation(
                from_doc_id=r["from_doc_id"],
                relation=r["relation"],
                to_doc_ref=r["to_doc_ref"],
                to_doc_id=r["to_doc_id"] or None,
                scope_note=r["scope_note"],
                evidence=r["evidence"],
                source="manual",
                reviewed=True,
            )
        )
    if problems:
        raise ManifestError(problems)
    return relations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate data/manifest.csv and relations.csv")
    parser.add_argument("--check", action="store_true", help="validate and print counts")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--relations", type=Path, default=RELATIONS_PATH)
    args = parser.parse_args(argv)
    try:
        result = load_manifest(args.manifest)
        known = {r.doc_id for r in result.rows}
        relations = load_relations(args.relations, known)
    except ManifestError as exc:
        print(f"Manifest check FAILED:\n{exc}", file=sys.stderr)
        return 1
    by_corpus = {c: sum(r.corpus == c for r in result.rows) for c in sorted(CORPORA)}
    by_status = {s: sum(r.status == s for r in result.rows) for s in sorted(STATUSES)}
    print(f"Documents: {len(result.rows)}  by corpus: {by_corpus}  by status: {by_status}")
    print(f"Skipped (to_verify): {len(result.skipped)}  Relations: {len(relations)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
