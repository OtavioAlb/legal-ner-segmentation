"""Synthetic regression for segmentation geometry and pending annotation support."""
import json

import pytest

from legal_nlp.datasets.vote_harmonization import build_vote_harmonized_view
from legal_nlp.datasets.segmentation_granularity import (
    analyze_granularity, write_granularity_report,
    _union_components, _pair_overlap_metrics,
)
from legal_nlp.io.jsonl import write_jsonl


def _fixture(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    docs = [
        {"document_id": "phase_1:one", "phase": "phase_1", "text": "a" * 20},
        {"document_id": "phase_2:two", "phase": "phase_2", "text": "b" * 30},
    ]
    rows = []
    def add(doc, phase, name, label, start, end, status):
        text = "a" if phase == "phase_1" else "b"
        rows.append({
            "document_id": doc, "phase": phase, "region_id": name,
            "task": "SEG" if label.startswith("SEG_") else "NER",
            "label": label, "start": start, "end": end,
            "status": status, "source_status": "fixture",
            "text": text * (end - start),
            "provenance": {"original_region_id": name},
        })
    add("phase_1:one", "phase_1", "x", "SEG_RELATORIO", 0, 5, "consolidated")
    add("phase_1:one", "phase_1", "y", "SEG_RELATORIO", 4, 8, "consolidated")
    add("phase_1:one", "phase_1", "z", "SEG_EMENTA", 12, 15, "consolidated")
    add("phase_1:one", "phase_1", "vote", "SEG_DECISAO_VOTO_VENCEDOR", 16, 18, "consolidated")
    add("phase_2:two", "phase_2", "x", "SEG_RELATORIO", 0, 12, "pending_review")
    add("phase_2:two", "phase_2", "y", "SEG_EMENTA", 10, 18, "consolidated")
    write_jsonl(source / "documents.jsonl", docs)
    write_jsonl(source / "annotations.jsonl", rows)
    (source / "dataset_manifest.json").write_text(json.dumps({
        "kind": "diagnostic_snapshot", "training_ready": False,
        "corpus_version": "fixture", "document_count": 2,
        "annotation_count": len(rows), "quarantine_record_count": 0,
        "quarantine_normalized_rows": 0,
    }), encoding="utf-8")
    derived = tmp_path / "derived"
    build_vote_harmonized_view(source, derived)
    taxonomy = tmp_path / "labels.json"
    taxonomy.write_text(json.dumps({
        "schema_version": "fixture",
        "labels": [
            "SEG_RELATORIO", "SEG_EMENTA", "SEG_JURISPRUDENCIA_VOTO_VENCIDO",
            "SEG_DECISAO_VOTO_VENCEDOR", "ENT_DECISAO_VOTO_VENCEDOR"
        ],
    }), encoding="utf-8")
    return source, derived, taxonomy


def test_union_components_and_cross_label_overlaps():
    assert _union_components([(0, 2), (2, 5), (8, 10)]) == 2
    assert _union_components([]) == 0
    rows = [
        {"start": 0, "end": 8, "label": "SEG_A"},
        {"start": 4, "end": 10, "label": "SEG_A"},
        {"start": 6, "end": 8, "label": "SEG_B"},
    ]
    pair = _pair_overlap_metrics(rows)
    assert pair["overlapping_pairs"] == 3
    assert pair["same_label_pairs"] == 1
    assert pair["cross_label_pairs"] == 2
    assert pair["contained_pairs"] == 1


def test_harmonized_geometry_counts_pending_and_excludes_mapped_vote(tmp_path):
    source, derived, taxonomy = _fixture(tmp_path)
    result = analyze_granularity(source, derived, taxonomy)
    p1 = result["by_phase"]["phase_1"]
    p2 = result["by_phase"]["phase_2"]
    assert p1["seg_potential"] == 3  # vote SEG -> ENT
    assert p1["total_union_covered_characters"] == 11  # [0,8] + [12,15]
    assert p1["union_components"] == 2
    assert p1["pairwise_overlaps"]["same_label_pairs"] == 1
    assert p2["seg_potential"] == 2
    assert p2["seg_pending"] == 1
    assert p2["total_union_covered_characters"] == 18
    assert p2["union_components"] == 1
    assert p2["pairwise_overlaps"]["cross_label_pairs"] == 1
    relatorio = next(item for item in result["by_label"] if item["label"] == "SEG_RELATORIO")
    assert relatorio["phase_1"]["occurrences"] == 2
    assert relatorio["phase_1"]["union_covered_characters"] == 8
    assert relatorio["phase_2"]["occurrences"] == 1
    assert relatorio["phase_2"]["pending"] == 1
    assert relatorio["median_span_length_ratio_phase2_over_phase1"] == 12 / 4.5
    empty = next(item for item in result["by_label"] if item["label"] == "SEG_JURISPRUDENCIA_VOTO_VENCIDO")
    assert empty["phase_1"]["occurrences"] == 0
    assert empty["phase_2"]["span_characters"]["median"] is None
    votes = next(item for item in result["by_label"] if item["label"] == "SEG_DECISAO_VOTO_VENCEDOR")
    assert votes["phase_1"]["occurrences"] == 0
    assert len(result["by_document"]) == 2


def test_read_only_and_refuses_overwrite(tmp_path):
    source, derived, taxonomy = _fixture(tmp_path)
    before = {str(f): f.read_bytes() for root in (source, derived)
              for f in root.iterdir()}
    report = tmp_path / "report.json"
    write_granularity_report(source, derived, taxonomy, report)
    assert before == {str(f): f.read_bytes() for root in (source, derived)
                      for f in root.iterdir()}
    with pytest.raises(FileExistsError):
        write_granularity_report(source, derived, taxonomy, report)


def test_refuses_tampered_annotation_source(tmp_path):
    source, derived, taxonomy = _fixture(tmp_path)
    p = source / "annotations.jsonl"
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum changed"):
        analyze_granularity(source, derived, taxonomy)
