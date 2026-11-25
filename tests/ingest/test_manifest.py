"""Manifest and relations validation, plus a check of the real committed data files."""

import csv

import pytest

from regrag.config import Settings
from regrag.ingest.manifest import (
    MANIFEST_COLUMNS,
    RELATION_COLUMNS,
    ManifestError,
    is_allowed_host,
    load_manifest,
    load_relations,
    main,
)

SETTINGS = Settings()


def good_row(**overrides) -> dict[str, str]:
    row = {
        "doc_id": "gst-231-25-2024",
        "corpus": "gst",
        "doc_type": "circular",
        "title": "Circular No. 231/25/2024-GST: test title",
        "reference_no": "231/25/2024-GST",
        "applies_to": "",
        "publish_date": "2024-09-11",
        "updated_as_on": "",
        "source_url": "https://gstcouncil.gov.in/cgst-circulars",
        "pdf_url": "https://gstcouncil.gov.in/sites/default/files/test.pdf",
        "status": "active",
        "sha256": "",
    }
    row.update(overrides)
    return row


def write_csv(path, columns, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    return path


def manifest(tmp_path, *rows):
    return write_csv(tmp_path / "manifest.csv", MANIFEST_COLUMNS, rows)


# --- Host check ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://www.rbi.org.in/Scripts/x.aspx?id=1", True),  # subdomain of rbi.org.in
        ("https://rbidocs.rbi.org.in/rdocs/a.PDF", True),
        ("https://gstcouncil.gov.in/sites/default/files/a.pdf", True),
        ("http://gstcouncil.gov.in/a.pdf", False),  # plain http
        ("https://rbi.org.in.evil.example/a.pdf", False),  # look-alike
        ("https://fakerbi.org.in/a.pdf", False),  # not a subdomain
        ("https://example.com/a.pdf", False),
        ("not a url", False),
    ],
)
def test_is_allowed_host(url, ok):
    assert is_allowed_host(url, SETTINGS.allowed_download_hosts) is ok


# --- Manifest ------------------------------------------------------------------------------


def test_valid_row_loads(tmp_path):
    result = load_manifest(manifest(tmp_path, good_row()), SETTINGS)
    assert [r.doc_id for r in result.rows] == ["gst-231-25-2024"]
    assert result.rows[0].publish_date.isoformat() == "2024-09-11"


def test_non_official_host_is_rejected(tmp_path):
    path = manifest(tmp_path, good_row(pdf_url="https://example.com/circular.pdf"))
    with pytest.raises(ManifestError, match="pdf_url is not an https URL on an official host"):
        load_manifest(path, SETTINGS)


def test_duplicate_doc_id_is_rejected(tmp_path):
    with pytest.raises(ManifestError, match="duplicate doc_id"):
        load_manifest(manifest(tmp_path, good_row(), good_row()), SETTINGS)


def test_to_verify_rows_are_skipped_with_a_warning(tmp_path):
    path = manifest(tmp_path, good_row(), good_row(doc_id="gst-1-1-2025", status="to_verify"))
    with pytest.warns(UserWarning, match="gst-1-1-2025"):
        result = load_manifest(path, SETTINGS)
    assert [r.doc_id for r in result.rows] == ["gst-231-25-2024"]
    assert result.skipped == ["gst-1-1-2025"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"publish_date": "11-09-2024"}, "YYYY-MM-DD"),
        ({"corpus": "sebi"}, "corpus must be one of"),
        ({"doc_id": "rbi-1"}, "doc_id must start with its corpus"),
        ({"doc_id": "GST 231"}, "doc_id must look like"),
        ({"status": "retired"}, "status must be one of"),
        ({"title": ""}, "title is empty"),
        ({"sha256": "abc"}, "sha256 must be"),
        ({"updated_as_on": "2020-01-01"}, "before publish_date"),
    ],
)
def test_bad_values_are_rejected(tmp_path, overrides, message):
    with pytest.raises(ManifestError, match=message):
        load_manifest(manifest(tmp_path, good_row(**overrides)), SETTINGS)


def test_all_problems_are_reported_together(tmp_path):
    path = manifest(
        tmp_path,
        good_row(doc_id="gst-1-1-2025", corpus="sebi"),
        good_row(doc_id="gst-2-1-2025", publish_date="yesterday"),
    )
    with pytest.raises(ManifestError) as info:
        load_manifest(path, SETTINGS)
    assert len(info.value.problems) == 2
    assert "line 2" in info.value.problems[0] and "line 3" in info.value.problems[1]


def test_missing_column_is_rejected(tmp_path):
    path = tmp_path / "manifest.csv"
    path.write_text("doc_id,corpus\ngst-1-1-2025,gst\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="missing column"):
        load_manifest(path, SETTINGS)


def test_excel_bom_is_tolerated(tmp_path):
    path = manifest(tmp_path, good_row())
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert len(load_manifest(path, SETTINGS).rows) == 1


# --- Relations -----------------------------------------------------------------------------


def relation(**overrides):
    row = {
        "from_doc_id": "gst-216-10-2024",
        "relation": "clarifies",
        "to_doc_ref": "195/07/2023-GST",
        "to_doc_id": "gst-195-07-2023",
        "scope_note": "",
        "evidence": "Official subject line says 'in furtherance to Circular No. 195/07/2023-GST'.",
    }
    row.update(overrides)
    return row


KNOWN = {"gst-216-10-2024", "gst-195-07-2023"}


def test_valid_relation_loads_as_manual_and_reviewed(tmp_path):
    path = write_csv(tmp_path / "r.csv", RELATION_COLUMNS, [relation()])
    (rel,) = load_relations(path, KNOWN)
    assert (rel.source, rel.reviewed, rel.to_doc_id) == ("manual", True, "gst-195-07-2023")


def test_target_outside_corpus_is_allowed(tmp_path):
    path = write_csv(tmp_path / "r.csv", RELATION_COLUMNS, [relation(to_doc_id="")])
    assert load_relations(path, KNOWN)[0].to_doc_id is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"relation": "replaces"}, "relation must be one of"),
        ({"evidence": ""}, "evidence is empty"),
        ({"from_doc_id": "gst-999-1-2025"}, "from_doc_id"),
        ({"to_doc_id": "gst-999-1-2025"}, "to_doc_id"),
    ],
)
def test_bad_relations_are_rejected(tmp_path, overrides, message):
    path = write_csv(tmp_path / "r.csv", RELATION_COLUMNS, [relation(**overrides)])
    with pytest.raises(ManifestError, match=message):
        load_relations(path, KNOWN)


# --- The real committed files --------------------------------------------------------------


def test_committed_manifest_and_relations_are_valid():
    result = load_manifest(settings=SETTINGS)
    by_corpus = {c: sum(r.corpus == c for r in result.rows) for c in ("rbi", "gst")}
    # 56 circulars, the CGST Act, CGST Rules and IGST Act (task 33), 4 GSTN advisories (task 35)
    assert by_corpus == {"rbi": 25, "gst": 63}
    assert result.skipped == []
    relations = load_relations(known_doc_ids={r.doc_id for r in result.rows})
    assert len(relations) >= 6
    # The superseded PSL direction must be marked, and linked from its replacement.
    statuses = {r.doc_id: r.status for r in result.rows}
    assert statuses["rbi-11959"] == "superseded"
    assert any(r.relation == "supersedes" and r.to_doc_id == "rbi-11959" for r in relations)


def test_check_command_exits_zero(capsys):
    assert main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "'rbi': 25" in out and "'gst': 63" in out
