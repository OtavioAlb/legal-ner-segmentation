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


def test_label_proposals_are_not_applied():
    from legal_nlp.audit import _propose_label
    known = {"ENT_NORMA_DECRETO", "SEG_FUNDAMENTO_DECISAO"}
    assert _propose_label("ENT_NORM_DECRETO", known, {}) == {
        "category": "possible_lexical_alias", "candidate": "ENT_NORMA_DECRETO"
    }
    assert _propose_label("SEG_DECISAO_VOTO_VENCEDOR", known, {}) == {
        "category": "legacy_segmentation_class", "candidate": None
    }
    assert _propose_label("ENT_JUR_DECISAO", known, {}) == {
        "category": "legacy_entity_class", "candidate": None
    }
    assert _propose_label("SIM", known, {})["category"] == "not_structured_label"


def test_audit_classifies_reviews_and_blank_offsets(tmp_path):
    source = tmp_path / "data"
    source.mkdir()
    document = {"document_id": "phase1:1", "text": "Legal text"}
    annotation = {
        "annotation_id": "a1", "source_row": 2, "document_id": "phase1:1",
        "source_document_id": "1", "label_original": None,
        "task": None, "start": None, "end": None, "span_text_source": None,
        "review_state": "revised_all_empty",
        "review_flags": ["EMPTY_REVISED_LABEL_NEW", "EMPTY_REVISED_START_NEW"],
        "reviewer_opinions": {
            "Alice": {"agreement_raw": "NÃO", "comment_raw": "review"},
            "Bob": {"agreement_raw": "SIM", "comment_raw": ""},
        },
        "issues": ["MISSING_LABEL", "INVALID_OFFSETS"],
    }
    (source / "documents.jsonl").write_text(
        json.dumps(document) + "\n", encoding="utf-8"
    )
    (source / "annotations.jsonl").write_text(
        json.dumps(annotation, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report = audit_phase1(source, tmp_path / "audit")
    assert report["review_state_counts"]["revised_all_empty"] == 1
    assert report["invalid_offset_reason_counts"]["missing_or_noninteger_start"] == 1
    assert report["reviewer_agreement_counts"]["Alice"]["disagree"] == 1
    assert report["reviewer_agreement_counts"]["Bob"]["agree"] == 1
    assert report["diagnostic_queue_count"] == 1
    assert (tmp_path / "audit" / "unknown_labels_review.jsonl").exists()


def test_disagreement_does_not_block_final_valid_corrected_span(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "documents.jsonl").write_text(
        json.dumps({"document_id": "phase1:1", "text": "Legal text"}) + "\n",
        encoding="utf-8",
    )
    ann = {
        "annotation_id": "review1", "source_row": 9,
        "document_id": "phase1:1", "source_document_id": "1",
        "label_original": "SEG_EMENTA", "label_canonical": "SEG_EMENTA", "task": "SEG", "start": 0,
        "end": 5, "span_text_source": "Legal",
        "review_state": "revised_complete",
        "review_flags": [], "issues": [],
        "disagreement_reviewers": ["R2"],
        "changed_review_fields": ["label"],
        "correction_status": "reviewed_fields_changed_final",
        "reviewer_opinions": {
            "R1": {"status": "not_recorded", "agreement_raw": None},
            "R2": {"status": "disagree", "agreement_raw": "NÃO"},
        },
    }
    (source / "annotations.jsonl").write_text(
        json.dumps(ann, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    result = audit_phase1(source, tmp_path / "audit")
    assert result["annotations_without_issues"] == 1
    assert result["annotations_with_explicit_disagreement"] == 1
    # Final evaluator corrections are not blocked by prior disagreement.
    assert result["diagnostic_queue_count"] == 0
    assert result["supervised_annotation_count"] == 1
    assert result["supervised_excluded_count"] == 0
    assert result["reviewer_agreement_counts"]["R1"]["not_recorded"] == 1
    assert result["reviewer_agreement_counts"]["R2"]["disagree"] == 1
    assert (tmp_path / "audit" / "review_queue.jsonl").read_text() == ""
    final_rows = (tmp_path / "audit" / "supervised_annotations.jsonl").read_text().splitlines()
    assert len(final_rows) == 1
    reviewed = json.loads(final_rows[0])
    assert reviewed["annotation_id"] == "review1"
    assert reviewed["label"] == "SEG_EMENTA"
    assert reviewed["source_of_truth"] == "evaluator_reviewed_fields"


def test_final_supervised_view_uses_corrected_fields_and_does_not_gate_on_disagreement(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "documents.jsonl").write_text(
        json.dumps({"document_id": "phase1:1", "text": "ABCD"}) + "\n",
        encoding="utf-8",
    )
    rows = [
        {
            "annotation_id": "accepted", "source_row": 2,
            "document_id": "phase1:1", "label_canonical": "SEG_EMENTA",
            "annotator_id": "A", "task": "SEG", "start": 0, "end": 4,
            "review_state": "revised_complete", "issues": [], "review_flags": [],
            "disagreement_reviewers": ["B"], "correction_status": "reviewed_fields_changed_final",
        },
        {
            "annotation_id": "excluded", "source_row": 3,
            "document_id": "phase1:1", "label_canonical": None,
            "annotator_id": "A", "task": None, "start": None, "end": None,
            "review_state": "revised_all_empty",
            "issues": ["MISSING_LABEL", "INVALID_OFFSETS"], "review_flags": [],
            "disagreement_reviewers": [], "correction_status": "no_explicit_disagreement",
        },
    ]
    (source / "annotations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    output = tmp_path / "audit"
    report = audit_phase1(source, output)
    accepted = [json.loads(x) for x in (
        output / "supervised_annotations.jsonl").read_text(encoding="utf-8").splitlines()]
    excluded = [json.loads(x) for x in (
        output / "supervised_exclusions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert report["supervised_annotation_count"] == 1
    assert report["supervised_excluded_count"] == 1
    assert accepted[0]["annotation_id"] == "accepted"
    assert accepted[0]["label"] == "SEG_EMENTA"
    assert excluded[0]["annotation_id"] == "excluded"
    assert "REVIEWED_FIELDS_INCOMPLETE" in excluded[0]["reasons"]


def test_unknown_labels_that_differ_only_by_case_are_preserved(tmp_path):
    source = tmp_path / "dataset"
    source.mkdir()
    (source / "documents.jsonl").write_text(
        json.dumps({"document_id": "phase1:1", "text": "text"}) + "\n",
        encoding="utf-8",
    )
    rows = []
    for index, label in enumerate(("SIM", "sim"), start=1):
        rows.append({
            "annotation_id": f"a{index}", "source_row": index + 1,
            "document_id": "phase1:1", "source_document_id": "1",
            "label_original": label, "label_canonical": None, "task": None,
            "start": 0, "end": 4, "span_text_source": "text",
            "issues": ["UNKNOWN_LABEL"], "review_flags": [],
            "review_state": "revised_complete",
        })
    (source / "annotations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    output = tmp_path / "audit"
    audit_phase1(source, output)
    report = json.loads((output / "audit_summary.json").read_text(encoding="utf-8"))
    assert report["audit_schema_version"] == "1.1.0"
    assert report["unknown_label_counts"] == [
        {"label": "SIM", "count": 1},
        {"label": "sim", "count": 1},
    ]
    assert report["supervised_excluded_count"] == 2


def test_audit_accepts_confirmed_original_and_excludes_conflicting_votes(tmp_path):
    source = tmp_path / "dataset"
    source.mkdir()
    (source / "documents.jsonl").write_text(
        json.dumps({"document_id": "phase1:1", "text": "Juiz"}) + "\n",
        encoding="utf-8",
    )
    accepted = {
        "annotation_id": "confirmed", "source_row": 23, "document_id": "phase1:1",
        "label_original": "ENT_RELATOR", "label_canonical": "ENT_RELATOR",
        "task": "NER", "start": 0, "end": 4, "span_text_source": "Juiz",
        "review_state": "revised_all_empty",
        "target_selection_status": "original_confirmed_by_reviewers",
        "issues": [], "review_flags": [], "disagreement_reviewers": [],
    }
    conflict = {
        **accepted,
        "annotation_id": "conflict", "source_row": 946,
        "target_selection_status": "conflicting_votes_without_correction",
        "label_original": None, "label_canonical": None,
        "start": None, "end": None,
        "issues": ["MISSING_LABEL", "INVALID_OFFSETS"],
        "disagreement_reviewers": ["B"],
    }
    (source / "annotations.jsonl").write_text(
        json.dumps(accepted) + "\n" + json.dumps(conflict) + "\n",
        encoding="utf-8",
    )
    report = audit_phase1(source, tmp_path / "audit")
    assert report["supervised_annotation_count"] == 1
    assert report["supervised_excluded_count"] == 1
    assert report["target_selection_status_counts"] == {
        "conflicting_votes_without_correction": 1,
        "original_confirmed_by_reviewers": 1,
    }
    final = json.loads((tmp_path / "audit" / "supervised_annotations.jsonl").read_text())
    assert final["annotation_id"] == "confirmed"
    assert final["source_of_truth"] == "original_confirmed_by_reviewers"
    exclusion = json.loads((tmp_path / "audit" / "supervised_exclusions.jsonl").read_text())
    assert exclusion["annotation_id"] == "conflict"
    assert "NO_VALIDATED_TARGET_SELECTION" in exclusion["reasons"]
