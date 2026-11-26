"""Synthetic tests of phase-aware counts, pending support and interval union."""
import hashlib
import json

import pytest

from legal_nlp.datasets.phase_coverage_audit import compare_phase_coverage, _covered
from legal_nlp.io.jsonl import write_jsonl


def fixture(tmp_path):
    root = tmp_path / "snapshot"
    root.mkdir()
    docs = [
        {"document_id": "phase_1:one", "phase": "phase_1",
         "text": "abcdefghij", "text_sha256": hashlib.sha256(b"abcdefghij").hexdigest()},
        {"document_id": "phase_2:two", "phase": "phase_2",
         "text": "abcdefghijklmnopqrst", "text_sha256": hashlib.sha256(b"abcdefghijklmnopqrst").hexdigest()},
    ]
    annotations = [
        {"document_id": "phase_1:one", "phase": "phase_1",
         "task": "SEG", "label": "SEG_EMENTA", "status": "consolidated",
         "start": 0, "end": 5, "text": "abcde"},
        {"document_id": "phase_2:two", "phase": "phase_2",
         "task": "SEG", "label": "SEG_EMENTA", "status": "pending_review",
         "start": 0, "end": 8, "text": "abcdefgh"},
        {"document_id": "phase_2:two", "phase": "phase_2",
         "task": "SEG", "label": "SEG_RELATORIO", "status": "consolidated",
         "start": 4, "end": 10, "text": "efghij"},
        {"document_id": "phase_2:two", "phase": "phase_2",
         "task": "NER", "label": "ENT_RELATOR", "status": "pending_review",
         "start": 2, "end": 6, "text": "cdef"},
    ]
    quarantine = [
        {"document_id": "phase_2:two", "region_id": "a", "task": "NER",
         "label": "ENT_RELATOR", "reason": "unresolved_source_text_integrity"},
        {"document_id": "phase_2:two", "region_id": "a", "project": "11",
         "task": "NER", "label": "ENT_RELATOR", "record_type": "raw_source_occurrence",
         "reason": "unresolved_text_mismatch"},
    ]
    write_jsonl(root / "documents.jsonl", docs)
    write_jsonl(root / "annotations.jsonl", annotations)
    write_jsonl(root / "quarantine.jsonl", quarantine)
    (root / "dataset_manifest.json").write_text(json.dumps({
        "kind": "diagnostic_snapshot", "training_ready": False,
        "corpus_version": "fixture", "document_count": 2,
        "annotation_count": 4, "quarantine_record_count": 2
    }), encoding="utf-8")
    return root


def test_pending_included_without_promotion_and_coverage_is_union(tmp_path):
    snapshot = fixture(tmp_path)
    result = compare_phase_coverage(snapshot)
    assert result["analysis_mode"] == "potential_includes_pending_not_gold"
    assert result["by_phase"]["phase_1"]["task_counts"]["SEG"]["potential_in_snapshot"] == 1
    assert result["by_phase"]["phase_2"]["task_counts"]["SEG"]["potential_in_snapshot"] == 2
    assert result["by_phase"]["phase_2"]["task_counts"]["SEG"]["pending_review"] == 1
    assert result["by_phase"]["phase_2"]["segmentation_covered_characters"] == 10
    assert result["by_phase"]["phase_2"]["segmentation_character_coverage_fraction"] == 0.5
    assert result["quarantine"]["normalized_rows"] == 1
    assert result["quarantine"]["raw_source_occurrences"] == 1
    assert result["quarantine"]["normalized_by_task"] == {"NER": 1}
    freq = next(r for r in result["labels"] if r["label"] == "SEG_EMENTA")
    assert freq["phase_1_potential"] == 1
    assert freq["phase_2_potential"] == 1
    assert freq["phase_2_pending_share"] == 1
    assert freq["total_potential_in_snapshot"] == 2


def test_overlap_union_not_naive_sum():
    assert _covered([(0, 8), (4, 10), (12, 15)]) == 13
    assert _covered([(1, 3), (1, 3)]) == 2
    assert _covered([]) == 0


def test_read_only_and_validates_manifest(tmp_path):
    snapshot = fixture(tmp_path)
    watched = list(snapshot.iterdir())
    before = {p.name: p.read_bytes() for p in watched}
    compare_phase_coverage(snapshot)
    assert before == {p.name: p.read_bytes() for p in watched}
    rows = json.loads((snapshot / "dataset_manifest.json").read_text(encoding="utf-8"))
    rows["annotation_count"] = 999
    (snapshot / "dataset_manifest.json").write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(ValueError, match="Manifest totals"):
        compare_phase_coverage(snapshot)
