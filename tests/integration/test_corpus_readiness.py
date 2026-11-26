"""Synthetic diagnostics for leakage and eligibility; never create train splits."""
import hashlib
import json

import pytest

from legal_nlp.datasets.readiness import analyze_readiness, write_readiness_report
from legal_nlp.io.jsonl import write_jsonl


def make_snapshot(tmp_path, *, pending=True, with_process=False):
    root = tmp_path / "diagnostic_snapshot"
    root.mkdir()
    text = "abc def"
    document = {
        "document_id": "phase_2:42", "phase": "phase_2",
        "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "idacordao": "42",
    }
    if with_process:
        document["process_id"] = "0000123-45.2026.8.26.0001"
    status = "pending_review" if pending else "consolidated"
    span = {
        "phase": "phase_2", "document_id": "phase_2:42",
        "region_id": "r1", "task": "NER",
        "label": "ENT_COMARCA", "start": 0, "end": 3, "text": "abc",
        "status": status, "source_status": "PENDENTE_GEOMETRIA" if pending
        else "CONCORDANCIA_ORIGINAL",
        "provenance": {"original_region_id": "r1"},
    }
    write_jsonl(root / "documents.jsonl", [document])
    write_jsonl(root / "annotations.jsonl", [span])
    (root / "dataset_manifest.json").write_text(json.dumps({
        "kind": "diagnostic_snapshot", "training_ready": False,
        "splits_frozen": False, "corpus_version": "test_v1",
        "document_count": 1, "annotation_count": 1,
        "taxonomy_version": "1.1.0",
        "input_sha256": {"phase2_original": "example"},
    }), encoding="utf-8")
    return root


def test_pending_and_unlinked_process_block_training(tmp_path):
    root = make_snapshot(tmp_path)
    report = analyze_readiness(root)
    assert report["training_ready"] is False
    assert report["annotation_status_counts"] == {"pending_review": 1}
    assert report["documents_with_pending_reviews"] == 1
    assert report["documents_without_process_id"] == 1
    assert "process_linkage_complete" in report["blockers"]
    assert "annotation_adjudication_complete" in report["blockers"]
    assert "formal_gold_approval" in report["blockers"]
    assert "splits_frozen" in report["blockers"]


def test_even_completed_process_linked_data_are_not_auto_gold(tmp_path):
    root = make_snapshot(tmp_path, pending=False, with_process=True)
    report = analyze_readiness(root)
    assert report["checks"]["process_linkage_complete"] is True
    assert report["checks"]["annotation_adjudication_complete"] is True
    assert report["training_ready"] is False
    assert "formal_gold_approval" in report["blockers"]


def test_text_tampering_is_rejected(tmp_path):
    root = make_snapshot(tmp_path)
    path = root / "documents.jsonl"
    rows = [json.loads(path.read_text(encoding="utf-8"))]
    rows[0]["text"] = "altered"
    write_jsonl(path, rows)
    with pytest.raises(ValueError, match="checksum mismatch"):
        analyze_readiness(root)


def test_report_is_non_destructive_and_refuses_overwrite(tmp_path):
    root = make_snapshot(tmp_path)
    path = root / "readiness.json"
    result = write_readiness_report(root, path)
    assert result["training_ready"] is False
    assert json.loads(path.read_text(encoding="utf-8"))["training_ready"] is False
    with pytest.raises(FileExistsError):
        write_readiness_report(root, path)
    with pytest.raises(ValueError, match="manifest"):
        write_readiness_report(root, root / "dataset_manifest.json")


def test_source_annotation_integrity_and_nonpromotion(tmp_path):
    root = make_snapshot(tmp_path)
    path = root / "annotations.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["start"] = 1
    write_jsonl(path, [row])
    with pytest.raises(ValueError, match="Span text mismatch"):
        analyze_readiness(root)
