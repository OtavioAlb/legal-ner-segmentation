"""Synthetic tests for connected components and stratified queue selection."""
import json

import pytest

from legal_nlp.datasets.segmentation_overlap_components import (
    _components, _summarize, _balanced_sample,
    analyze_overlap_components, write_component_report,
)
from legal_nlp.datasets.vote_harmonization import build_vote_harmonized_view
from legal_nlp.io.jsonl import write_jsonl


def _row(doc_id, region_id, label, start, end, status="consolidated"):
    phase = doc_id.split(":")[0]
    return {
        "phase": phase, "document_id": doc_id,
        "region_id": region_id, "label": label,
        "task": "SEG", "source_task": "SEG", "source_label": label,
        "start": start, "end": end,
        "text": ("a" if phase == "phase_1" else "b") * (end-start),
        "status": status, "source_status": "test",
        "provenance": {"source_region_id": region_id},
    }


def _fixture(tmp_path):
    root = tmp_path / "snapshot"
    root.mkdir()
    docs = [
        {"phase": "phase_1", "document_id": "phase_1:a", "text": "a" * 30},
        {"phase": "phase_1", "document_id": "phase_1:b", "text": "a" * 30},
        {"phase": "phase_2", "document_id": "phase_2:c", "text": "b" * 30},
    ]
    rows = [
        _row("phase_1:a", "a1", "SEG_RELATORIO", 0, 20),
        _row("phase_1:a", "a2", "SEG_RELATORIO", 0, 19),
        _row("phase_1:a", "a3", "SEG_RELATORIO", 10, 25),
        _row("phase_1:a", "a4", "SEG_RELATORIO", 25, 30),
        _row("phase_1:a", "a5", "SEG_EMENTA", 0, 10),
        _row("phase_1:b", "b1", "SEG_RELATORIO", 0, 10),
        _row("phase_1:b", "b2", "SEG_RELATORIO", 0, 10),
        _row("phase_2:c", "c1", "SEG_RELATORIO", 0, 10, "pending_review"),
        _row("phase_2:c", "c2", "SEG_RELATORIO", 2, 8),
    ]
    write_jsonl(root / "documents.jsonl", docs)
    write_jsonl(root / "annotations.jsonl", rows)
    (root / "dataset_manifest.json").write_text(json.dumps({
        "kind": "diagnostic_snapshot", "training_ready": False,
        "corpus_version": "fixture", "document_count": 3,
        "annotation_count": len(rows), "quarantine_record_count": 0,
    }), encoding="utf-8")
    derived = tmp_path / "derived"
    build_vote_harmonized_view(root, derived)
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({
        "labels": ["SEG_RELATORIO", "SEG_EMENTA"]
    }), encoding="utf-8")
    return root, derived, labels


def test_components_are_same_label_only_and_touching_do_not_overlap():
    doc = "phase_1:a"
    rows = [
        _row(doc, "1", "SEG_RELATORIO", 0, 10),
        _row(doc, "2", "SEG_RELATORIO", 5, 12),
        _row(doc, "3", "SEG_RELATORIO", 10, 14),
        _row(doc, "4", "SEG_RELATORIO", 14, 16),
        _row(doc, "5", "SEG_EMENTA", 0, 10),
    ]
    comps = _components(rows)
    assert len(comps) == 1
    assert comps[0][0] == "SEG_RELATORIO"
    assert {r["region_id"] for r in comps[0][1]} == {"1", "2", "3"}


def test_summarize_transitive_component_does_not_inflate_near_pairs():
    doc = "phase_1:a"
    group = [
        _row(doc, "a", "SEG_RELATORIO", 0, 20),
        _row(doc, "b", "SEG_RELATORIO", 0, 19),
        _row(doc, "c", "SEG_RELATORIO", 10, 25),
    ]
    summary = _summarize("phase_1", doc, "SEG_RELATORIO", group, 1)
    assert summary["number_of_regions"] == 3
    assert summary["overlapping_pairs"] == 3
    assert summary["near_boundary_pairs"] == 1
    assert summary["strict_containment_pairs"] == 1
    assert summary["partial_overlap_pairs"] == 2
    assert summary["distinct_boundaries"] == 3
    assert summary["distinct_lineage_fingerprints"] == 3


def test_balanced_queue_round_robins_documents():
    def item(doc, i):
        return {
            "document_id": doc, "label": "SEG_RELATORIO",
            "near_boundary_pairs": 0, "strict_containment_pairs": 0,
            "number_of_regions": 2, "envelope_characters": 10,
            "envelope_start": i,
        }
    rows = [item("phase_1:a", i) for i in range(8)]
    rows += [item("phase_1:b", 0), item("phase_1:c", 0)]
    selected = _balanced_sample(rows, max_groups=4, max_per_document=2)
    assert [r["document_id"] for r in selected] == [
        "phase_1:a", "phase_1:b", "phase_1:c", "phase_1:a"
    ]


def test_full_report_integrity_and_immutability(tmp_path):
    src, derived, labels = _fixture(tmp_path)
    before = {str(f): f.read_bytes() for d in (src, derived) for f in d.iterdir()}
    report = analyze_overlap_components(src, derived, labels,
                                        max_groups=2, max_per_document=1)
    assert report["training_ready"] is False
    assert report["by_phase"]["phase_1"]["overlap_components"] == 2
    assert report["by_phase"]["phase_1"]["regions_in_components"] == 5
    assert report["by_phase"]["phase_1"]["overlapping_pairs_in_components"] == 4
    assert report["by_phase"]["phase_1"]["near_boundary_pairs"] == 2
    assert report["by_phase"]["phase_2"]["overlap_components"] == 1
    assert report["by_phase"]["phase_2"]["overlapping_pairs_in_components"] == 1
    assert len(report["review_queue"]) == 2
    assert {g["document_id"] for g in report["review_queue"]} == {
        "phase_1:a", "phase_1:b"
    }
    assert "provenance" not in json.dumps(report)
    assert before == {str(f): f.read_bytes() for d in (src, derived) for f in d.iterdir()}


def test_report_writes_without_overwriting_and_rejects_invalid_params(tmp_path):
    src, derived, labels = _fixture(tmp_path)
    output = tmp_path / "groups.json"
    write_component_report(src, derived, labels, output)
    with pytest.raises(FileExistsError):
        write_component_report(src, derived, labels, output)
    with pytest.raises(ValueError, match="limits positive"):
        analyze_overlap_components(src, derived, labels, max_groups=0)
    with pytest.raises(ValueError, match="limits positive"):
        analyze_overlap_components(src, derived, labels, near_tolerance=-1)


def test_fails_on_modified_snapshot(tmp_path):
    src, derived, labels = _fixture(tmp_path)
    path = src / "annotations.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum changed"):
        analyze_overlap_components(src, derived, labels)
