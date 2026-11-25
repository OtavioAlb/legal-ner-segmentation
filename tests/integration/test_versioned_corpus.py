"""Synthetic-only integration tests for a versioned diagnostic corpus snapshot."""
import hashlib
import json

import pytest

from legal_nlp.datasets.versioned_corpus import build_diagnostic_corpus
from legal_nlp.io.jsonl import read_jsonl, write_jsonl


def make_task(doc_id, reviewer, *, text="abc def", updated=None):
    return {
        "id": int(doc_id),
        "data": {"idacordao": int(doc_id), "acordao": text},
        "updated_by": reviewer if updated is None else updated,
        "annotations": [{
            "completed_by": reviewer,
            "result": [{
                "id": "r1", "type": "labels",
                "value": {"labels": ["ENT_COMARCA"], "start": 0,
                          "end": 3, "text": "abc"}
            }, {
                "id": "r1", "type": "choices", "value": {"choices": ["Certo"]}
            }],
        }],
    }


def fixture_paths(tmp_path, *, phase2_text="abc def", p1_acordao="11"):
    p1 = tmp_path / "phase1.jsonl"
    text = "xyz legal"
    write_jsonl(p1, [{
        "document_id": "source-1", "idacordao": p1_acordao,
        "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "spans": {
            "NER": [{
                "logical_span_id": "ls_a", "label": "ENT_COMARCA",
                "start": 0, "end": 3,
                "provenance": [{"annotation_id": "a", "source_row": 1}],
            }],
            "SEG": [],
        },
    }])
    paths = [p1]
    for name, reviewer in (("original", 8), ("review11", 7), ("review17", 5)):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps([make_task(42, reviewer, text=phase2_text)]),
                        encoding="utf-8")
        paths.append(path)
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({
        "schema_version": "1.1.0", "labels": ["ENT_COMARCA"]
    }), encoding="utf-8")
    paths.append(labels)
    return paths


def build(paths, output, version="snapshot_001"):
    return build_diagnostic_corpus(
        *paths, output, version=version
    )


def test_snapshot_contains_phase_namespaced_documents_and_manifest(tmp_path):
    paths = fixture_paths(tmp_path)
    out = tmp_path / "processed" / "snapshot_001"
    manifest = build(paths, out)
    assert manifest["training_ready"] is False
    assert manifest["splits_frozen"] is False
    assert manifest["document_count"] == 2
    assert manifest["annotation_count"] == 2
    assert set(manifest["input_sha256"]) == {
        "phase1_document_spans", "phase2_original",
        "phase2_review_11", "phase2_review_17", "labels",
    }
    docs = read_jsonl(out / "documents.jsonl")
    assert {d["document_id"] for d in docs} == {
        "phase_1:source-1", "phase_2:42",
    }
    rows = read_jsonl(out / "annotations.jsonl")
    assert {r["status"] for r in rows} == {"consolidated"}
    assert {r["text"] for r in rows} == {"xyz", "abc"}
    assert all(r["provenance"] for r in rows)


def test_cross_phase_acordao_collision_is_rejected_without_output(tmp_path):
    paths = fixture_paths(tmp_path, p1_acordao="42")
    out = tmp_path / "snapshot"
    with pytest.raises(ValueError, match="Repeated idacordao"):
        build(paths, out)
    assert not out.exists()


def test_exact_duplicate_text_is_rejected_without_output(tmp_path):
    paths = fixture_paths(tmp_path, phase2_text="xyz legal")
    out = tmp_path / "snapshot"
    with pytest.raises(ValueError, match="Identical source text"):
        build(paths, out)
    assert not out.exists()


def test_existing_snapshot_refuses_overwrite(tmp_path):
    paths = fixture_paths(tmp_path)
    out = tmp_path / "snapshot"
    build(paths, out)
    before = (out / "dataset_manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        build(paths, out)
    assert (out / "dataset_manifest.json").read_bytes() == before


def test_unknown_taxonomy_rejected_before_writing(tmp_path):
    paths = fixture_paths(tmp_path)
    paths[-1].write_text(json.dumps({"labels": ["ENT_RELATOR"]}), encoding="utf-8")
    out = tmp_path / "snapshot"
    with pytest.raises(ValueError, match="Unknown label"):
        build(paths, out)
    assert not out.exists()
