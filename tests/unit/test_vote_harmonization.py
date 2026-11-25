"""Synthetic contract for a reversible vote-label derived view."""
import hashlib
import json

import pytest

from legal_nlp.datasets.vote_harmonization import build_vote_harmonized_view
from legal_nlp.io.jsonl import read_jsonl, write_jsonl


def make_snapshot(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    text_1 = "abc def ghi"
    text_2 = "some legal decision"
    documents = [
        {"document_id": "phase_1:a", "phase": "phase_1", "text": text_1},
        {"document_id": "phase_2:b", "phase": "phase_2", "text": text_2},
    ]
    def row(phase, document_id, region, label, task, status="consolidated"):
        text = text_1 if phase == "phase_1" else text_2
        return {
            "phase": phase, "document_id": document_id, "region_id": region,
            "label": label, "task": task, "status": status,
            "source_status": "example", "start": 0, "end": 3,
            "text": text[:3], "provenance": [{"annotation_id": "a"}] if phase == "phase_1" else {"original_region_id": region},
        }
    annotations = [
        row("phase_1", "phase_1:a", "v1", "SEG_DECISAO_VOTO_VENCEDOR", "SEG"),
        row("phase_1", "phase_1:a", "v2", "SEG_DECISAO_VOTO_VENCIDO", "SEG"),
        row("phase_1", "phase_1:a", "j", "SEG_JURISPRUDENCIA_VOTO_VENCIDO", "SEG"),
        row("phase_2", "phase_2:b", "v3", "ENT_DECISAO_VOTO_VENCEDOR", "NER", "pending_review"),
    ]
    write_jsonl(source / "documents.jsonl", documents)
    write_jsonl(source / "annotations.jsonl", annotations)
    write_jsonl(source / "quarantine.jsonl", [{"record_type": "raw_source_occurrence", "label": "SEG_EMENTA"}])
    (source / "dataset_manifest.json").write_text(json.dumps({
        "kind": "diagnostic_snapshot", "training_ready": False,
        "corpus_version": "v1", "document_count": 2,
        "annotation_count": 4, "quarantine_record_count": 1,
    }), encoding="utf-8")
    return source


def test_harmonizes_only_phase1_votes_and_preserves_evidence(tmp_path):
    source = make_snapshot(tmp_path)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    dest = tmp_path / "derived"
    manifest = build_vote_harmonized_view(source, dest)
    assert manifest["mapped_count"] == 2
    assert manifest["output_annotations"] == 4
    assert manifest["training_ready"] is False
    assert manifest["quarantine_record_count"] == 1
    rows = read_jsonl(dest / "annotations_harmonized.jsonl")
    assert rows[0]["source_label"] == "SEG_DECISAO_VOTO_VENCEDOR"
    assert rows[0]["label"] == "ENT_DECISAO_VOTO_VENCEDOR"
    assert rows[0]["source_task"] == "SEG" and rows[0]["task"] == "NER"
    assert rows[1]["label"] == "ENT_DECISAO_VOTO_VENCIDO"
    assert rows[2]["label"] == "SEG_JURISPRUDENCIA_VOTO_VENCIDO"
    assert rows[3]["label"] == "ENT_DECISAO_VOTO_VENCEDOR"
    assert rows[3]["status"] == "pending_review"
    for i, row in enumerate(read_jsonl(source / "annotations.jsonl")):
        assert (rows[i]["start"], rows[i]["end"], rows[i]["text"], rows[i]["status"], rows[i]["provenance"]) == (
            row["start"], row["end"], row["text"], row["status"], row["provenance"])
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}


def test_refuses_to_overwrite(tmp_path):
    source = make_snapshot(tmp_path)
    out = tmp_path / "derived"
    build_vote_harmonized_view(source, out)
    with pytest.raises(FileExistsError):
        build_vote_harmonized_view(source, out)


def test_rejects_manifest_mismatch_without_output(tmp_path):
    source = make_snapshot(tmp_path)
    manifest = json.loads((source / "dataset_manifest.json").read_text())
    manifest["annotation_count"] = 999
    (source / "dataset_manifest.json").write_text(json.dumps(manifest))
    dest = tmp_path / "invalid"
    with pytest.raises(ValueError, match="manifest count"):
        build_vote_harmonized_view(source, dest)
    assert not dest.exists()
