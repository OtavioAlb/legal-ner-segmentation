import json

from legal_nlp.audit import audit_phase1, classify_mismatch


def test_mismatch_types():
    assert classify_mismatch("Abc", "abc") == "case_only"
    assert classify_mismatch(" word ", "word") == "edge_whitespace"
    assert classify_mismatch("a", "b") == "other"


def test_audit_local_review_queue(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "documents.jsonl").write_text(
        json.dumps({"document_id": "phase1:1", "text": "Legal text"}) + "\n",
        encoding="utf-8",
    )
    (source / "annotations.jsonl").write_text(
        json.dumps({
            "annotation_id": "a1", "source_row": 2, "document_id": None,
            "source_document_id": None, "label_original": "ENT_RELATOR",
            "task": "NER", "start": 0, "end": 5,
            "span_text_source": "Legal", "issues": ["UNKNOWN_DOCUMENT"],
            "review_flags": []
        }) + "\n", encoding="utf-8"
    )
    report = audit_phase1(source, tmp_path / "output")
    assert report["unknown_document_candidate_counts"] == {"1": 1}
    assert report["annotations_with_issues"] == 1
    queue = json.loads((tmp_path / "output" / "review_queue.jsonl").read_text())
    assert queue["candidate_document_ids"] == ["phase1:1"]
    assert queue["document_id"] is None
