"""Tests: canonical zero labels, potential counts and immutable evidence."""
import json

import pytest

from legal_nlp.datasets.vote_harmonization import build_vote_harmonized_view
from legal_nlp.datasets.harmonized_label_support import (
    analyze_support, write_support_report
)
from legal_nlp.io.jsonl import write_jsonl


def _fixture(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    text = "abcde fghij"
    docs = [
        {"phase": "phase_1", "document_id": "phase_1:1", "text": text},
        {"phase": "phase_2", "document_id": "phase_2:2", "text": text + " second"},
    ]
    def annotation(phase, doc, region, label, task, status):
        return {
            "phase": phase, "document_id": doc, "region_id": region,
            "task": task, "label": label, "start": 0, "end": 5,
            "text": "abcde", "status": status, "source_status": "test",
            "provenance": {"original_region_id": region},
        }
    rows = [
        annotation("phase_1", "phase_1:1", "v1", "SEG_DECISAO_VOTO_VENCEDOR", "SEG", "consolidated"),
        annotation("phase_1", "phase_1:1", "s1", "SEG_RELATORIO", "SEG", "consolidated"),
        annotation("phase_2", "phase_2:2", "v2", "ENT_DECISAO_VOTO_VENCEDOR", "NER", "pending_review"),
        annotation("phase_2", "phase_2:2", "s2", "SEG_RELATORIO", "SEG", "pending_review"),
    ]
    write_jsonl(original / "documents.jsonl", docs)
    write_jsonl(original / "annotations.jsonl", rows)
    (original / "dataset_manifest.json").write_text(json.dumps({
        "kind": "diagnostic_snapshot", "training_ready": False,
        "corpus_version": "test", "document_count": 2,
        "annotation_count": 4, "quarantine_record_count": 0,
        "quarantine_normalized_rows": 0,
    }), encoding="utf-8")
    harmonized = tmp_path / "harmonized"
    build_vote_harmonized_view(original, harmonized)
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text(json.dumps({
        "schema_version": "test",
        "labels": ["ENT_DECISAO_VOTO_VENCEDOR", "ENT_DECISAO_VOTO_VENCIDO",
                   "SEG_RELATORIO", "SEG_JURISPRUDENCIA_VOTO_VENCIDO",
                   "SEG_DECISAO_VOTO_VENCEDOR"],
    }), encoding="utf-8")
    return original, harmonized, taxonomy


def test_support_includes_pending_and_zero_labels(tmp_path):
    original, harmonized, taxonomy = _fixture(tmp_path)
    before = {
        str(p): p.read_bytes()
        for root in (original, harmonized) for p in root.iterdir()
    }
    result = analyze_support(original, harmonized, taxonomy)
    assert result["annotations"] == 4
    assert result["mapped_count"] == 1
    assert result["training_ready"] is False
    vote = next(x for x in result["labels"] if x["label"] == "ENT_DECISAO_VOTO_VENCEDOR")
    assert vote["total_potential"] == 2
    assert vote["total_consolidated"] == 1
    assert vote["total_pending_review"] == 1
    assert vote["documents_with_support_total"] == 2
    assert vote["phase_presence"] == "both"
    assert result["task_diagnostics"]["NER"]["zero_support"] == ["ENT_DECISAO_VOTO_VENCIDO"]
    assert "SEG_JURISPRUDENCIA_VOTO_VENCIDO" in result["task_diagnostics"]["SEG"]["zero_support"]
    assert "SEG_DECISAO_VOTO_VENCEDOR" in result["task_diagnostics"]["SEG"]["zero_support"]
    assert before == {
        str(p): p.read_bytes()
        for root in (original, harmonized) for p in root.iterdir()
    }


def test_detects_mutated_source_and_harmonized_labels(tmp_path):
    original, harmonized, taxonomy = _fixture(tmp_path)
    source = original / "annotations.jsonl"
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum changed"):
        analyze_support(original, harmonized, taxonomy)


def test_write_refuses_overwrite(tmp_path):
    original, harmonized, taxonomy = _fixture(tmp_path)
    output = tmp_path / "report.json"
    result = write_support_report(original, harmonized, taxonomy, output)
    assert len(result["labels"]) == 5
    with pytest.raises(FileExistsError):
        write_support_report(original, harmonized, taxonomy, output)


def test_rejects_semantic_change_in_derived_view(tmp_path):
    original, harmonized, taxonomy = _fixture(tmp_path)
    path = harmonized / "annotations_harmonized.jsonl"
    from legal_nlp.io.jsonl import read_jsonl
    rows = read_jsonl(path)
    rows[0]["label"] = "SEG_RELATORIO"
    write_jsonl(path, rows)
    with pytest.raises(ValueError, match="Unexpected harmonization"):
        analyze_support(original, harmonized, taxonomy)
