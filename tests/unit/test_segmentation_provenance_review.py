"""Synthetic regression tests for provenance-linked segmentation review queues."""
import json
import pytest

from legal_nlp.datasets.vote_harmonization import build_vote_harmonized_view
from legal_nlp.datasets.segmentation_provenance_review import (
    build_review_queues, write_review_queues, _pair_type,
)
from legal_nlp.io.jsonl import write_jsonl


def fixture(tmp_path):
    root = tmp_path / "snapshot"
    root.mkdir()
    docs = [
        {"document_id": "phase_1:a", "phase": "phase_1", "text": "a" * 30},
        {"document_id": "phase_2:b", "phase": "phase_2", "text": "b" * 40},
    ]
    rows = []
    for phase, doc, name, label, start, end, status in [
        ("phase_1", "phase_1:a", "a", "SEG_RELATORIO", 0, 20, "consolidated"),
        ("phase_1", "phase_1:a", "b", "SEG_RELATORIO", 4, 12, "consolidated"),
        ("phase_1", "phase_1:a", "c", "SEG_EMENTA", 8, 17, "consolidated"),
        ("phase_1", "phase_1:a", "v", "SEG_DECISAO_VOTO_VENCEDOR", 25, 28, "consolidated"),
        ("phase_2", "phase_2:b", "d", "SEG_RELATORIO", 0, 6, "pending_review"),
        ("phase_2", "phase_2:b", "e", "SEG_EMENTA", 3, 8, "consolidated"),
    ]:
        rows.append({
            "phase": phase, "document_id": doc, "region_id": name,
            "task": "SEG", "label": label, "start": start, "end": end,
            "text": ("a" if phase == "phase_1" else "b") * (end-start),
            "source_status": "fixture", "status": status,
            "provenance": {"original_region_id": name, "reviewer_email": "hidden@example.org"}
        })
    write_jsonl(root / "documents.jsonl", docs)
    write_jsonl(root / "annotations.jsonl", rows)
    (root / "dataset_manifest.json").write_text(json.dumps({
        "kind": "diagnostic_snapshot", "training_ready": False,
        "document_count": 2, "annotation_count": len(rows),
        "quarantine_record_count": 0, "corpus_version": "fake",
    }), encoding="utf-8")
    derived = tmp_path / "derived"
    build_vote_harmonized_view(root, derived)
    taxonomy = tmp_path / "labels.json"
    taxonomy.write_text(json.dumps({
        "labels": ["SEG_RELATORIO", "SEG_EMENTA",
                   "SEG_DECISAO_VOTO_VENCEDOR", "ENT_DECISAO_VOTO_VENCEDOR"],
    }), encoding="utf-8")
    return root, derived, taxonomy


def test_pair_categories():
    x = {"start": 0, "end": 10}
    assert _pair_type(x, {"start": 0, "end": 10}) == "identical"
    assert _pair_type(x, {"start": 3, "end": 6}) == "strict_containment"
    assert _pair_type(x, {"start": 8, "end": 12}) == "partial_overlap"


def test_review_queues_and_provenance_redaction(tmp_path):
    source, derived, labels = fixture(tmp_path)
    out = build_review_queues(source, derived, labels, min_gap=5,
                              top_pairs=20, top_gaps=20)
    assert out["training_ready"] is False
    assert out["mapped_vote_spans"] == 1
    assert out["overlap_candidates_total"] == 4  # 3 phase 1 + 1 phase 2
    assert out["phase_metrics"][0]["same_label_pairs"] == 1
    assert out["phase_metrics"][0]["cross_label_pairs"] == 2
    assert out["phase_metrics"][1]["at_least_one_pending_pairs"] == 1
    same = [p for p in out["overlap_review_queue"]
            if p["category"] == "same_label"]
    assert len(same) == 1
    assert same[0]["geometry"] == "strict_containment"
    assert len(same[0]["region_a"]["lineage_sha256"]) == 64
    assert out["gap_review_queue"][0]["phase"] == "phase_2"
    assert out["gap_review_queue"][0]["characters"] == 32
    assert "hidden@example.org" not in json.dumps(out)
    assert "reviewer_email" not in json.dumps(out)


def test_source_preserved_and_refuse_overwrite(tmp_path):
    source, derived, labels = fixture(tmp_path)
    before = {str(p): p.read_bytes() for folder in (source, derived)
              for p in folder.iterdir()}
    target = tmp_path / "review.json"
    result = write_review_queues(source, derived, labels, target,
                                 min_gap=2)
    assert result["gap_candidates_above_threshold_total"] >= 2
    assert before == {str(p): p.read_bytes() for folder in (source, derived)
                      for p in folder.iterdir()}
    with pytest.raises(FileExistsError):
        write_review_queues(source, derived, labels, target)


def test_rejects_invalid_limit_or_changed_source(tmp_path):
    source, derived, labels = fixture(tmp_path)
    with pytest.raises(ValueError, match="positive integers"):
        build_review_queues(source, derived, labels, top_pairs=0)
    path = source / "annotations.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum changed"):
        build_review_queues(source, derived, labels)
