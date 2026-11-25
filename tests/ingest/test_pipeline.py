"""Ingest pipeline with fakes: no AWS, no database, no network."""

import shutil
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from regrag.config import Settings
from regrag.ingest import pipeline
from regrag.ingest.manifest import MANIFEST_COLUMNS
from regrag.types import ManifestRow
from tests.fakes import FakeEmbedder

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_direction.pdf"
SETTINGS = Settings()


def row(doc_id: str) -> ManifestRow:
    return ManifestRow(
        doc_id=doc_id,
        corpus="rbi",
        doc_type="direction",
        title=f"Test {doc_id}",
        reference_no=f"RBI/TEST/{doc_id}",
        applies_to="",
        publish_date=date(2099, 1, 1),
        source_url="https://www.rbi.org.in/x",
        pdf_url="https://rbidocs.rbi.org.in/x.pdf",
    )


class FakeConn:
    @contextmanager
    def transaction(self):
        yield


@pytest.fixture
def recorder(monkeypatch):
    """Replace the repository functions with recorders; nothing touches a database."""
    calls: list[tuple] = []
    state: dict[str, tuple[str, str]] = {}
    monkeypatch.setattr(pipeline.repo, "document_state", lambda conn, d: state.get(d))

    def upsert(conn, r, chunks, *, page_count, embedding_model):
        calls.append(("upsert", r.doc_id, len(chunks), page_count))
        assert all(c.embedding is not None for c in chunks)  # embedded before storing
        state[r.doc_id] = (r.sha256, embedding_model)

    monkeypatch.setattr(pipeline.repo, "upsert_document", upsert)
    monkeypatch.setattr(pipeline.repo, "stored_embeddings", lambda conn, d, t, m: {})
    monkeypatch.setattr(
        pipeline.repo, "replace_relations",
        lambda conn, d, rels: calls.append(("relations", d, len(rels))),
    )  # fmt: skip
    return calls


def raw_dir_with(tmp_path, good: list[str], broken: list[str]) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    for doc_id in good:
        shutil.copy(FIXTURE, raw / f"{doc_id}.pdf")
    for doc_id in broken:
        (raw / f"{doc_id}.pdf").write_bytes(b"%PDF-1.4 but nothing else")
    return raw


def test_two_documents_in_calls_in_order(tmp_path, recorder):
    raw = raw_dir_with(tmp_path, ["rbi-a", "rbi-b"], [])
    embedder = FakeEmbedder(dimensions=8)
    deps = pipeline.Deps(SETTINGS, embedder, FakeConn(), raw_dir=raw)
    reports = pipeline.run([row("rbi-a"), row("rbi-b")], deps)
    assert [r.status for r in reports] == ["ingested", "ingested"]
    assert [c[:2] for c in recorder] == [
        ("upsert", "rbi-a"), ("relations", "rbi-a"), ("upsert", "rbi-b"), ("relations", "rbi-b"),
    ]  # fmt: skip
    assert recorder[0][3] == 3  # page count of the fixture
    assert len(embedder.calls) == 2 and reports[0].embed_tokens > 0


def test_a_parse_failure_does_not_stop_the_other_document(tmp_path, recorder):
    raw = raw_dir_with(tmp_path, ["rbi-b"], ["rbi-a"])
    deps = pipeline.Deps(SETTINGS, FakeEmbedder(dimensions=8), FakeConn(), raw_dir=raw)
    reports = pipeline.run([row("rbi-a"), row("rbi-b")], deps)
    assert [r.status for r in reports] == ["failed", "ingested"]
    assert "rbi-a" in reports[0].message


def test_unchanged_document_is_skipped_on_the_second_run(tmp_path, recorder):
    raw = raw_dir_with(tmp_path, ["rbi-a"], [])
    embedder = FakeEmbedder(dimensions=8)
    deps = pipeline.Deps(SETTINGS, embedder, FakeConn(), raw_dir=raw)
    pipeline.run([row("rbi-a")], deps)
    (second,) = pipeline.run([row("rbi-a")], deps)
    assert second.status == "skipped" and second.cost_usd == 0
    assert len(embedder.calls) == 1  # no second embedding call


def test_missing_pdf_is_reported(tmp_path, recorder):
    raw = raw_dir_with(tmp_path, [], [])
    (report,) = pipeline.run([row("rbi-a")], pipeline.Deps(SETTINGS, None, FakeConn(), raw_dir=raw))
    assert report.status == "failed" and "PDF missing" in report.message


def test_dry_run_estimates_cost_without_aws_or_database(tmp_path, recorder):
    raw = raw_dir_with(tmp_path, ["rbi-a"], [])
    (report,) = pipeline.run(
        [row("rbi-a")], pipeline.Deps(SETTINGS, None, None, raw_dir=raw), dry_run=True
    )
    assert report.status == "dry-run" and report.chunks > 0
    assert report.embed_tokens > 0 and report.cost_usd > 0
    assert recorder == []  # nothing stored


def test_update_manifest_hashes_changes_only_that_column(tmp_path):
    path = tmp_path / "manifest.csv"
    path.write_text(
        ",".join(MANIFEST_COLUMNS) + "\n" + "rbi-a,rbi,direction,T,R,,2099-01-01,,u,p,active,\n",
        encoding="utf-8",
    )
    assert pipeline.update_manifest_hashes(path, {"rbi-a": "f" * 64}) == 1
    assert path.read_text(encoding="utf-8").splitlines()[1].endswith("active," + "f" * 64)
    assert pipeline.update_manifest_hashes(path, {"rbi-a": "f" * 64}) == 0


def test_a_dead_connection_is_replaced_before_writing(tmp_path, recorder):
    class DeadConn(FakeConn):
        def execute(self, sql):
            raise RuntimeError("server closed the connection unexpectedly")

    class LiveConn(FakeConn):
        def execute(self, sql):
            return None

    raw = raw_dir_with(tmp_path, ["rbi-a"], [])
    fresh = LiveConn()
    deps = pipeline.Deps(SETTINGS, FakeEmbedder(dimensions=8), DeadConn(), raw_dir=raw,
                         reconnect=lambda: fresh)  # fmt: skip
    (report,) = pipeline.run([row("rbi-a")], deps)
    assert report.status == "ingested" and deps.conn is fresh


def test_unchanged_chunks_reuse_stored_vectors(tmp_path, recorder, monkeypatch):
    raw = raw_dir_with(tmp_path, ["rbi-a"], [])
    first = FakeEmbedder(dimensions=8)
    deps = pipeline.Deps(SETTINGS, first, FakeConn(), raw_dir=raw)
    (report,) = pipeline.run([row("rbi-a")], deps)
    all_texts = first.calls[0]
    # Pretend everything but the last chunk is already stored with its vector.
    stored = {}
    for text in all_texts[:-1]:
        # embedded text = title \n section path \n\n content
        path, content = text.split("\n")[1], text.split("\n\n", 1)[1]
        stored[(path, content)] = [0.5] * 8
    monkeypatch.setattr(pipeline.repo, "stored_embeddings", lambda conn, d, t, m: stored)
    second = FakeEmbedder(dimensions=8)
    deps = pipeline.Deps(SETTINGS, second, FakeConn(), raw_dir=raw, force=True)
    (again,) = pipeline.run([row("rbi-a")], deps)
    assert again.status == "ingested" and second.calls == [all_texts[-1:]]
    assert again.embed_tokens < report.embed_tokens and "reused" in again.message


def test_force_reingests_an_unchanged_file(tmp_path, recorder):
    raw = raw_dir_with(tmp_path, ["rbi-a"], [])
    deps = pipeline.Deps(SETTINGS, FakeEmbedder(dimensions=8), FakeConn(), raw_dir=raw)
    pipeline.run([row("rbi-a")], deps)
    (skipped,) = pipeline.run([row("rbi-a")], deps)
    assert skipped.status == "skipped"
    deps.force = True
    (forced,) = pipeline.run([row("rbi-a")], deps)
    assert forced.status == "ingested"
