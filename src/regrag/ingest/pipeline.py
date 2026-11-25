"""End-to-end ingestion: manifest → download → parse → chunk → relations → embed → store.

Run:  uv run python -m regrag.ingest.pipeline [--only DOC_ID] [--limit N]
                                             [--skip-download] [--dry-run]

- One failing document is reported and skipped; the rest carry on.
- A document whose PDF hash and embedding model are unchanged since the last run is
  skipped, so re-running costs nothing.
- --dry-run does everything except Bedrock calls and database writes, and prints the
  estimated embedding cost.
- Afterwards: manual relations are (re)loaded, link targets are resolved, the PDF hashes
  are written into data/manifest.csv, and extracted relations are saved to
  data/raw/extracted_relations.csv (gitignored) for a human to review.
"""

import argparse
import csv
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import httpx

from regrag.bedrock.pricing import cost_usd
from regrag.config import Settings, get_settings
from regrag.db import repository as repo
from regrag.ingest.chunk import chunk_document, embedding_text, estimate_tokens
from regrag.ingest.download import RAW_DIR, download_document, make_client, sha256_of
from regrag.ingest.manifest import (
    MANIFEST_COLUMNS,
    MANIFEST_PATH,
    RELATIONS_PATH,
    load_manifest,
    load_relations,
)
from regrag.ingest.parse import ParseError, parse_pdf
from regrag.ingest.statute import (
    StatuteError,
    chunk_statute,
    fetch_statute,
    is_statute,
    parse_statute,
)
from regrag.ingest.statute import make_client as statute_make_client
from regrag.ingest.statute import raw_path as statute_raw_path
from regrag.ingest.supersession import extract_relations
from regrag.interfaces import Embedder
from regrag.types import ManifestRow, Relation

EXTRACTED_RELATIONS_PATH = RAW_DIR / "extracted_relations.csv"


@dataclass
class DocReport:
    doc_id: str
    status: str  # "ingested", "skipped", "failed" or "dry-run"
    chunks: int = 0
    tables: int = 0
    scanned_pages: int = 0
    embed_tokens: int = 0
    cost_usd: float = 0.0
    sha256: str = ""
    relations: list[Relation] = field(default_factory=list)
    message: str = ""


@dataclass
class Deps:
    """Everything the pipeline talks to, passed in so tests can use fakes."""

    settings: Settings
    embedder: Embedder | None
    conn: object | None  # psycopg connection (autocommit), None in a dry run
    raw_dir: Path = RAW_DIR
    http: object | None = None  # httpx client for downloads, None to skip downloading
    # Client for the CBIC portal's law pages (OS trust store); made on first use if None.
    statute_http: object | None = None
    # Opens a fresh database connection; used when the old one died during a long embed.
    reconnect: Callable[[], object] | None = None
    # Re-chunk and store even if the source file is unchanged (after a chunker fix).
    force: bool = False


def _ensure_connection(deps: Deps) -> None:
    """Replace a dead database connection before writing (only when we know how)."""
    if deps.reconnect is None or deps.conn is None:
        return
    try:
        deps.conn.execute("SELECT 1")
    except Exception:  # closed by the server, Docker or a sleeping PC
        deps.conn = deps.reconnect()


def ingest_document(row: ManifestRow, deps: Deps, *, dry_run: bool = False) -> DocReport:
    settings = deps.settings
    if is_statute(row):
        # The bare law (task 33): saved section pages instead of a PDF.
        path = statute_raw_path(row, deps.raw_dir)
        if deps.http is not None and not path.exists():
            try:
                if deps.statute_http is None:
                    deps.statute_http = statute_make_client(settings)
                fetch_statute(row, deps.statute_http, settings, deps.raw_dir)
            except (StatuteError, httpx.HTTPError) as exc:
                return DocReport(row.doc_id, "failed", message=f"statute fetch: {exc}")
        if not path.exists():
            return DocReport(
                row.doc_id,
                "failed",
                message="statute text missing: run python -m regrag.ingest.statute",
            )
    else:
        path = deps.raw_dir / f"{row.doc_id}.pdf"
        if deps.http is not None:
            download = download_document(row, deps.http, deps.raw_dir, settings)
            if download.status == "failed":
                return DocReport(row.doc_id, "failed", message=f"download: {download.message}")
        if not path.exists():
            return DocReport(row.doc_id, "failed", message="PDF missing: run the downloader first")
    sha = sha256_of(path)

    model = settings.bedrock_embed_model_id
    unchanged = not deps.force and not dry_run
    if unchanged and repo.document_state(deps.conn, row.doc_id) == (sha, model):
        return DocReport(row.doc_id, "skipped", sha256=sha, message="unchanged")

    if is_statute(row):
        try:
            parsed = parse_statute(path, row.doc_id)
            chunks = chunk_statute(path, row, settings)
        except StatuteError as exc:
            return DocReport(row.doc_id, "failed", sha256=sha, message=str(exc))
        relations: list[Relation] = []  # amendments are recorded in the law text itself
    else:
        try:
            parsed = parse_pdf(path, row.doc_id)
        except ParseError as exc:
            return DocReport(row.doc_id, "failed", sha256=sha, message=str(exc))
        chunks = chunk_document(parsed, row, settings)
        relations = extract_relations(row.doc_id, chunks, row.reference_no)
    texts = [embedding_text(c, row.title) for c in chunks]
    report = DocReport(
        row.doc_id,
        "dry-run" if dry_run else "ingested",
        chunks=len(chunks),
        tables=sum(c.content_type == "table" for c in chunks),
        scanned_pages=sum(p.scanned for p in parsed.pages),
        sha256=sha,
        relations=relations,
    )
    if dry_run:
        report.embed_tokens = sum(estimate_tokens(t) for t in texts)
        report.cost_usd = cost_usd(model, input_tokens=report.embed_tokens)
        return report

    # Reuse stored vectors for chunks whose embedded text is unchanged; pay only for the rest.
    stored = repo.stored_embeddings(deps.conn, row.doc_id, row.title, model)
    todo = []
    for i, chunk in enumerate(chunks):
        vector = stored.get((chunk.section_path or "", chunk.content))
        if vector is None:
            todo.append(i)
        else:
            chunk.embedding = vector
    new_tokens = 0
    if todo:
        embedded = deps.embedder.embed([texts[i] for i in todo])
        for i, vector in zip(todo, embedded.vectors, strict=True):
            chunks[i].embedding = vector
        new_tokens = embedded.input_tokens
    report.message = f"reused {len(chunks) - len(todo)} stored vectors" if stored else ""
    _ensure_connection(deps)  # embedding can take many minutes; the connection may be gone
    # One transaction for the document, its chunks and its extracted links.
    with deps.conn.transaction():
        repo.upsert_document(
            deps.conn,
            replace(row, sha256=sha),
            chunks,
            page_count=parsed.page_count,
            embedding_model=model,
        )
        repo.replace_relations(deps.conn, row.doc_id, relations)
    report.embed_tokens = new_tokens
    report.cost_usd = cost_usd(model, input_tokens=new_tokens)
    return report


def run(
    rows: list[ManifestRow],
    deps: Deps,
    *,
    dry_run: bool = False,
    progress: Callable[[DocReport], None] | None = None,
) -> list[DocReport]:
    reports = []
    for row in rows:
        try:
            report = ingest_document(row, deps, dry_run=dry_run)
        except Exception as exc:  # one bad document must not stop the other 64
            report = DocReport(row.doc_id, "failed", message=f"{type(exc).__name__}: {exc}")
        reports.append(report)
        if progress:
            progress(report)
    return reports


def update_manifest_hashes(path: Path, hashes: dict[str, str]) -> int:
    """Write sha256 values into the manifest, changing nothing else. Returns rows changed."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    changed = 0
    for row in rows:
        new = hashes.get(row["doc_id"])
        if new and row["sha256"] != new:
            row["sha256"] = new
            changed += 1
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return changed


def write_extracted_relations(path: Path, relations: list[Relation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["from_doc_id", "relation", "to_doc_ref", "scope_note", "evidence"])
        for r in relations:
            writer.writerow([r.from_doc_id, r.relation, r.to_doc_ref, r.scope_note, r.evidence])


def summarize(reports: list[DocReport], seconds: float) -> str:
    count = {
        s: sum(r.status == s for r in reports) for s in ("ingested", "skipped", "failed", "dry-run")
    }
    lines = [
        f"Documents: {len(reports)}  ingested: {count['ingested']}  skipped: {count['skipped']}  "
        f"failed: {count['failed']}  dry-run: {count['dry-run']}",
        f"Chunks: {sum(r.chunks for r in reports)}  tables: {sum(r.tables for r in reports)}  "
        f"scanned pages: {sum(r.scanned_pages for r in reports)}",
        f"Embedding tokens: {sum(r.embed_tokens for r in reports):,}  "
        f"cost: ${sum(r.cost_usd for r in reports):.4f}  time: {seconds:.0f}s",
        f"Extracted relations: {sum(len(r.relations) for r in reports)}",
    ]
    lines += [f"  FAILED {r.doc_id}: {r.message}" for r in reports if r.status == "failed"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest the manifest into Postgres")
    parser.add_argument("--only", action="append", help="only this doc_id (repeatable)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-chunk and store even if the file is unchanged (reuses stored vectors)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    rows = load_manifest(settings=settings).rows
    if args.only:
        rows = [r for r in rows if r.doc_id in set(args.only)]
    rows = rows[: args.limit] if args.limit else rows

    def show(r: DocReport) -> None:
        print(
            f"{r.status:8} {r.doc_id:24} chunks={r.chunks:4} tokens={r.embed_tokens:7,} "
            f"${r.cost_usd:.5f} {r.message}",
            flush=True,
        )

    start = time.perf_counter()
    http = None if args.skip_download else make_client(settings)
    if args.dry_run:
        reports = run(rows, Deps(settings, None, None, http=http), dry_run=True, progress=show)
        print(summarize(reports, time.perf_counter() - start))
        return 0

    # Imported here so a dry run needs neither AWS credentials nor Docker.
    from regrag.bedrock.client import get_runtime_client
    from regrag.bedrock.embedder import TitanEmbedder
    from regrag.db.connection import connect

    embedder = TitanEmbedder.from_settings(get_runtime_client(settings), settings)
    with connect(settings, autocommit=True) as first_conn:
        deps = Deps(
            settings, embedder, first_conn, http=http,
            reconnect=lambda: connect(settings, autocommit=True), force=args.force,
        )  # fmt: skip
        reports = run(rows, deps, progress=show)
        conn = deps.conn  # may be a fresh connection after a reconnect
        stored = {r[0] for r in conn.execute("SELECT doc_id FROM documents").fetchall()}
        manual = [
            rel
            for rel in load_relations(
                RELATIONS_PATH, known_doc_ids={r.doc_id for r in load_manifest().rows}
            )
            if rel.from_doc_id in stored and (rel.to_doc_id is None or rel.to_doc_id in stored)
        ]
        repo.load_manual_relations(conn, manual)
        resolved = repo.resolve_relation_targets(conn)
        if conn is not first_conn:
            conn.close()
    changed = update_manifest_hashes(
        MANIFEST_PATH, {r.doc_id: r.sha256 for r in reports if r.sha256}
    )
    extracted = [rel for r in reports for rel in r.relations]
    # Only when something was re-extracted: a run that skipped every document must not
    # overwrite the review file with an empty list.
    if extracted:
        write_extracted_relations(EXTRACTED_RELATIONS_PATH, extracted)
    print(summarize(reports, time.perf_counter() - start))
    print(
        f"Manual relations loaded: {len(manual)}  link targets resolved: {resolved}  "
        f"manifest hashes updated: {changed}"
    )
    if extracted:
        print(f"Extracted relations for review: {EXTRACTED_RELATIONS_PATH}")
    return 1 if any(r.status == "failed" for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
