"""Synthetic contract for raw-file hashes and Phase 1 lineage to harmonized snapshot."""
import hashlib
import json

import pytest

from legal_nlp.datasets.phase1_source_lineage import audit_phase1_lineage
from legal_nlp.datasets.vote_harmonization import build_vote_harmonized_view
from legal_nlp.io.jsonl import write_jsonl


def fixture(tmp_path):
    raw_texts = tmp_path / "raw_docs.csv"
    raw_annotations = tmp_path / "raw_annotations.csv"
    raw_texts.write_text("id,text\\n1,aaaaaaaaaa\\n", encoding="utf-8")
    raw_annotations.write_text("id_text,label\\n1,SEG_RELATORIO\\n", encoding="utf-8")
    ing = tmp_path / "ingested"
    ing.mkdir()
    san = tmp_path / "sanitized"
    san.mkdir()
    logical = tmp_path / "logical"
    logical.mkdir()
    docs = tmp_path / "document_spans.jsonl"
    original_doc = {"document_id": "phase1:1", "text": "a" * 10,
                    "idacordao": None}
    ingested_row = {
        "annotation_id": "phase1:ann1", "source_row": 2,
        "annotator_id": "annotator", "start": 0, "end": 5,
        "target_selection_status": "reviewed_final",
        "fields_original": {"label": "SEG_RELATORIO", "start": 0, "end": 4},
        "fields_revised": {"label": "SEG_RELATORIO", "start": 0, "end": 5},
        "review_agree_count": 1, "review_disagree_count": 1,
    }
    clean_row = {
        "annotation_id": "phase1:ann1", "source_row": 2,
        "annotator_id": "annotator", "document_id": "phase1:1",
        "task": "SEG", "label": "SEG_RELATORIO", "start": 0, "end": 5,
        "source_of_truth": "evaluator_reviewed_fields",
    }
    provenance = [{
        "annotation_id": "phase1:ann1", "source_row": 2,
        "annotator_id": "annotator", "selection_status": "reviewed_final",
        "source_of_truth": "evaluator_reviewed_fields",
        "review_agree_count": 1, "review_disagree_count": 1,
    }]
    logical_row = {
        "logical_span_id": "ls_1", "document_id": "phase1:1",
        "task": "SEG", "label": "SEG_RELATORIO", "start": 0,
        "end": 5, "source_annotation_count": 1, "provenance": provenance,
    }
    write_jsonl(ing / "documents.jsonl", [original_doc])
    write_jsonl(ing / "annotations.jsonl", [ingested_row])
    write_jsonl(san / "sanitized_annotations.jsonl", [clean_row])
    write_jsonl(logical / "logical_spans.jsonl", [logical_row])
    write_jsonl(docs, [{
        "document_id": "phase1:1", "text": "a" * 10, "idacordao": None,
        "spans": {"NER": [], "SEG": [logical_row]},
    }])
    (ing / "dataset_manifest.json").write_text(json.dumps({
        "input_sha256": {
            "texts": hashlib.sha256(raw_texts.read_bytes()).hexdigest(),
            "annotations": hashlib.sha256(raw_annotations.read_bytes()).hexdigest()
        }
    }), encoding="utf-8")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    write_jsonl(snapshot / "documents.jsonl", [{
        "document_id": "phase_1:phase1:1", "phase": "phase_1",
        "text": "a" * 10,
    }])
    write_jsonl(snapshot / "annotations.jsonl", [{
        "document_id": "phase_1:phase1:1", "phase": "phase_1",
        "region_id": "ls_1", "task": "SEG", "label": "SEG_RELATORIO",
        "start": 0, "end": 5, "text": "a" * 5,
        "source_status": "phase1_evaluator_final_logical_span",
        "status": "consolidated", "provenance": provenance,
    }])
    (snapshot / "dataset_manifest.json").write_text(json.dumps({
        "kind": "diagnostic_snapshot", "training_ready": False,
        "corpus_version": "synthetic", "annotation_count": 1,
        "document_count": 1, "quarantine_record_count": 0,
    }), encoding="utf-8")
    derived = tmp_path / "derived"
    build_vote_harmonized_view(snapshot, derived)
    labels = tmp_path / "taxonomy.json"
    labels.write_text(json.dumps({"labels": ["SEG_RELATORIO"]}), encoding="utf-8")
    return (snapshot, derived, labels, raw_texts, raw_annotations,
            ing, san, logical, docs)


def test_full_source_chain_verified(tmp_path):
    args = fixture(tmp_path)
    result = audit_phase1_lineage(*args)
    assert result["verified_logical_spans"] == 1
    assert result["verified_seg_spans"] == 1
    assert result["verified_source_annotations"] == 1
    assert result["selection_counts"]["reviewed_final"] == 1
    assert result["lineage"][0]["source_records"][0]["source_row"] == 2
    assert "annotator" not in json.dumps(result)


def test_raw_source_mutation_fail_closed(tmp_path):
    args = fixture(tmp_path)
    args[4].write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Original raw export checksum mismatch"):
        audit_phase1_lineage(*args)


def test_intermediate_span_mutation_fail_closed(tmp_path):
    args = fixture(tmp_path)
    san = args[6]
    path = san / "sanitized_annotations.jsonl"
    from legal_nlp.io.jsonl import read_jsonl
    records = read_jsonl(path)
    records[0]["end"] = 6
    write_jsonl(path, records)
    with pytest.raises(ValueError, match="Sanitized span differs"):
        audit_phase1_lineage(*args)


def test_unverified_annotator_linkage_fail_closed(tmp_path):
    args = fixture(tmp_path)
    logical = args[7]
    path = logical / "logical_spans.jsonl"
    from legal_nlp.io.jsonl import read_jsonl
    rows = read_jsonl(path)
    rows[0]["provenance"][0]["annotator_id"] = "different"
    write_jsonl(path, rows)
    with pytest.raises(ValueError, match="Provenance changed"):
        audit_phase1_lineage(*args)
