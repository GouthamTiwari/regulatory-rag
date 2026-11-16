"""Golden set loader and the committed seed file."""

import json

import pytest

from regrag.eval.golden import GoldenError, load_golden, main
from regrag.ingest.manifest import load_manifest


def good(**overrides):
    row = {
        "id": "g900",
        "schema_version": 1,
        "question": "Can a car dealer claim input tax credit on demo vehicles?",
        "corpus": "gst",
        "type": "factual",
        "expected_doc_ids": ["gst-231-25-2024"],
        "expected_sections": [{"doc_id": "gst-231-25-2024", "section_no": "Para 4", "page": 2}],
        "reference_answer": "Yes, when used for further supply.",
        "should_abstain": False,
        "must_flag_supersession": False,
        "tags": ["itc"],
        "source": "manual",
        "reviewed": True,
    }
    row.update(overrides)
    return row


def write(tmp_path, *rows):
    path = tmp_path / "golden.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_valid_row_loads(tmp_path):
    (item,) = load_golden(write(tmp_path, good()))
    assert item.id == "g900" and item.expected_doc_ids == ["gst-231-25-2024"]


def test_bad_type_is_rejected(tmp_path):
    with pytest.raises(GoldenError, match="type must be one of"):
        load_golden(write(tmp_path, good(type="trivia")))


def test_duplicate_id_is_rejected(tmp_path):
    with pytest.raises(GoldenError, match="duplicate id"):
        load_golden(write(tmp_path, good(), good()))


def test_extra_fields_are_kept_not_rejected(tmp_path):
    (item,) = load_golden(write(tmp_path, good(difficulty="hard")))
    assert item.extra == {"difficulty": "hard"}


def test_abstain_rows_must_have_no_expected_docs(tmp_path):
    row = good(type="abstain", should_abstain=True, corpus="none", expected_sections=[])
    with pytest.raises(GoldenError, match="abstain rows must have empty expected_doc_ids"):
        load_golden(write(tmp_path, row))


def test_unreviewed_rows_are_excluded_unless_asked(tmp_path):
    path = write(tmp_path, good(), good(id="g901", reviewed=False))
    assert [i.id for i in load_golden(path)] == ["g900"]
    assert len(load_golden(path, include_unreviewed=True)) == 2


def test_unknown_doc_id_is_rejected_when_manifest_known(tmp_path):
    with pytest.raises(GoldenError, match="not in the manifest"):
        load_golden(write(tmp_path, good()), known_doc_ids={"rbi-13141"})


def test_all_problems_reported_together(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text("not json\n" + json.dumps(good(corpus="sebi")) + "\n", encoding="utf-8")
    with pytest.raises(GoldenError) as info:
        load_golden(path)
    assert len(info.value.problems) == 2


def test_committed_seed_file_is_valid():
    known = {r.doc_id for r in load_manifest().rows}
    items = load_golden(include_unreviewed=True, known_doc_ids=known)
    assert len(items) >= 20
    types = [i.type for i in items]
    assert types.count("superseded") >= 3
    assert types.count("abstain") >= 3
    assert types.count("cross_corpus") >= 2
    questions = {i.question for i in items}
    assert "Can a car dealer claim input tax credit on demo vehicles?" in questions


def test_check_command_exits_zero(capsys):
    assert main(["--check"]) == 0
    assert "Rows: 61" in capsys.readouterr().out
