"""Synthetic tests for segmentation overlap matrix and gap geometry."""
import json

import pytest

from legal_nlp.datasets.vote_harmonization import build_vote_harmonized_view
from legal_nlp.datasets.segmentation_overlap_gaps import (
    _uncovered_intervals, _pairs, analyze_overlap_gaps, write_overlap_gaps_report
)
from legal_nlp.io.jsonl import write_jsonl


def _fixture(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    docs = [
        {"phase": "phase_1", "document_id": "phase_1:a", "text": "a" * 30},
        {"phase": "phase_2", "document_id": "phase_2:b", "text": "b" * 30},
    ]
    rows = []
    for doc, phase, rid, label, start, end, status in [
        ("phase_1:a", "phase_1", "r1", "SEG_RELATORIO", 0, 10, "consolidated"),
        ("phase_1:a", "phase_1", "r2", "SEG_RELATORIO", 5, 12, "consolidated"),
        ("phase_1:a", "phase_1", "r3", "SEG_EMENTA", 6, 8, "consolidated"),
        ("phase_1:a", "phase_1", "vote", "SEG_DECISAO_VOTO_VENCEDOR", 15, 20, "consolidated"),
        ("phase_2:b", "phase_2", "r4", "SEG_RELATORIO", 0, 12, "pending_review"),
        ("phase_2:b", "phase_2", "r5", "SEG_EMENTA", 8, 16, "consolidated"),
    ]:
        rows.append({
            "document_id": doc, "phase": phase, "region_id": rid,
            "label": label, "task": "SEG",
            "status": status, "source_status": "fixture",
            "start": start, "end": end, "text": ("a" if phase == "phase_1" else "b") * (end-start),
            "provenance": {"original_region_id": rid},
        })
    write_jsonl(src / "documents.jsonl", docs)
    write_jsonl(src / "annotations.jsonl", rows)
    (src / "dataset_manifest.json").write_text(json.dumps({
        "kind": "diagnostic_snapshot", "training_ready": False,
        "document_count": 2, "annotation_count": len(rows),
        "corpus_version": "test", "quarantine_record_count": 0
    }), encoding="utf-8")
    derived = tmp_path / "derived"
    build_vote_harmonized_view(src, derived)
    taxonomy = tmp_path / "labels.json"
    taxonomy.write_text(json.dumps({
        "schema_version": "test",
        "labels": ["SEG_RELATORIO", "SEG_EMENTA",
                   "SEG_DECISAO_VOTO_VENCEDOR", "ENT_DECISAO_VOTO_VENCEDOR"]
    }), encoding="utf-8")
    return src, derived, taxonomy


def test_uncovered_intervals_merges_contiguous_spans():
    assert _uncovered_intervals(20, [
        {"start": 0, "end": 4}, {"start": 4, "end": 6},
        {"start": 9, "end": 11}
    ]) == [(6, 9), (11, 20)]
    assert _uncovered_intervals(10, []) == [(0, 10)]
    assert _uncovered_intervals(0, []) == []


def test_distinct_overlapping_pairs():
    rows = [
        {"start": 0, "end": 10, "region_id": "a"},
        {"start": 5, "end": 12, "region_id": "b"},
        {"start": 12, "end": 15, "region_id": "c"}
    ]
    pairs = list(_pairs(rows))
    assert len(pairs) == 1
    assert pairs[0][2] == 5


def test_matrix_gaps_and_mapped_vote_exclusion(tmp_path):
    src, derived, taxonomy = _fixture(tmp_path)
    before = {str(f): f.read_bytes() for d in (src, derived) for f in d.iterdir()}
    result = analyze_overlap_gaps(src, derived, taxonomy, min_gap=2, top_n=10)
    assert result["training_ready"] is False
    assert result["mapped_vote_spans"] == 1
    assert result["by_phase"]["phase_1"]["uncovered_characters"] == 18
    assert result["by_phase"]["phase_2"]["uncovered_characters"] == 14
    assert result["by_phase"]["phase_1"]["overlapping_pairs"] == 3
    assert result["by_phase"]["phase_2"]["overlapping_pairs"] == 1
    phase1_pairs = [r for r in result["overlap_matrix"] if r["phase"] == "phase_1"]
    same = next(r for r in phase1_pairs if r["same_label"])
    assert same["pair_count"] == 1
    assert same["documents_with_pair"] == 1
    cross = next(r for r in phase1_pairs if not r["same_label"])
    assert cross["pair_count"] == 2
    assert result["by_phase"]["phase_2"]["geometry_pairs"]["partial_overlap"] == 1
    assert result["by_phase"]["phase_1"]["geometry_pairs"]["strict_containment"] == 2
    assert result["top_uncovered_intervals"][0]["characters"] == 18
    assert before == {str(f): f.read_bytes() for d in (src, derived) for f in d.iterdir()}


def test_no_overwrite_and_validation(tmp_path):
    src, derived, taxonomy = _fixture(tmp_path)
    dest = tmp_path / "report.json"
    write_overlap_gaps_report(src, derived, taxonomy, dest, min_gap=1)
    with pytest.raises(FileExistsError):
        write_overlap_gaps_report(src, derived, taxonomy, dest)
    with pytest.raises(ValueError, match="positive integers"):
        analyze_overlap_gaps(src, derived, taxonomy, min_gap=0)


def test_refuses_tampered_source(tmp_path):
    src, derived, taxonomy = _fixture(tmp_path)
    p = src / "annotations.jsonl"
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum changed"):
        analyze_overlap_gaps(src, derived, taxonomy)
