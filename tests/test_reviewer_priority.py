import json

import pytest

from legal_nlp.reviewer_priority import audit_reviewer_label_priority


def _write(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _ann(identifier, row, original, revised, status="reviewed_final"):
    return {
        "annotation_id": identifier,
        "source_row": row,
        "annotator_id": identifier,
        "target_selection_status": status,
        "fields_original": {"label": original},
        "fields_revised": {"label": revised},
        "review_agree_count": 1,
        "review_disagree_count": 1 if original != revised else 0,
        "disagreement_reviewers": ["Reviewer"] if original != revised else [],
    }


def _pair(first_ids, second_ids, first_label, second_label, category="near_boundaries_different_label"):
    return {
        "document_id": "phase1:1",
        "task": "NER",
        "category": category,
        "delta_start": 2,
        "delta_end": 1,
        "shared_annotator_ids": [],
        "first": {
            "start": 10, "end": 30, "label": first_label,
            "annotation_ids": first_ids,
        },
        "second": {
            "start": 12, "end": 31, "label": second_label,
            "annotation_ids": second_ids,
        },
    }


def test_reviewer_correction_precedence_is_evidence_not_auto_discard(tmp_path):
    anns = [
        _ann("a1", 23, "ENT_CLASSE", "ENT_RELATOR"),
        _ann("a2", 30, "ENT_ASSUNTO", "ENT_ASSUNTO"),
        _ann("a3", 40, "ENT_RELATOR", "ENT_ASSUNTO"),
    ]
    pairs = [
        _pair(["a1"], ["a2"], "ENT_RELATOR", "ENT_ASSUNTO"),
        _pair(["a1"], ["a3"], "ENT_RELATOR", "ENT_ASSUNTO"),
        _pair(["a2"], ["a3"], "ENT_ASSUNTO", "ENT_ASSUNTO"),
    ]
    annotations = tmp_path / "annotations.jsonl"
    candidates = tmp_path / "candidates.jsonl"
    output = tmp_path / "output"
    _write(annotations, anns)
    _write(candidates, pairs)
    result = audit_reviewer_label_priority(annotations, candidates, output)
    assert result["input_candidate_pairs"] == 3
    assert result["different_label_candidate_pairs"] == 2
    assert result["same_label_candidate_pairs_skipped"] == 1
    records = [
        json.loads(x)
        for x in (output / "different_label_review_evidence.jsonl").read_text().splitlines()
    ]
    assert records[0]["priority_evidence_status"] == (
        "one_side_has_explicit_evaluator_label_correction"
    )
    assert records[0]["priority_evidence_side"] == "first"
    assert records[0]["first_review_evidence"][0]["label_original_before_review"] == "ENT_CLASSE"
    assert records[0]["first_review_evidence"][0]["label_revised_by_evaluators"] == "ENT_RELATOR"
    assert records[1]["priority_evidence_status"] == "competing_evaluator_label_corrections"
    assert records[1]["priority_evidence_side"] is None
    assert all(not record["automatic_label_removal"] for record in records)
    assert result["priority_evidence_status_counts"] == {
        "competing_evaluator_label_corrections": 1,
        "one_side_has_explicit_evaluator_label_correction": 1,
    }
    previous = (output / "different_label_review_evidence.jsonl").read_bytes()
    assert audit_reviewer_label_priority(annotations, candidates, output) == result
    assert (output / "different_label_review_evidence.jsonl").read_bytes() == previous


def test_reviewer_priority_preserves_original_confirmation(tmp_path):
    anns = [
        _ann("a1", 2, "ENT_RELATOR", None, "original_confirmed_by_reviewers"),
        _ann("a2", 3, "ENT_ASSUNTO", "ENT_ASSUNTO"),
    ]
    annotations = tmp_path / "annotations.jsonl"
    candidates = tmp_path / "candidates.jsonl"
    _write(annotations, anns)
    _write(candidates, [_pair(["a1"], ["a2"], "ENT_RELATOR", "ENT_ASSUNTO")])
    result = audit_reviewer_label_priority(annotations, candidates, tmp_path / "out")
    assert result["priority_evidence_status_counts"] == {
        "no_explicit_label_correction_to_prioritize": 1
    }


def test_reviewer_priority_rejects_missing_annotation_provenance(tmp_path):
    annotations = tmp_path / "annotations.jsonl"
    candidates = tmp_path / "candidates.jsonl"
    _write(annotations, [])
    _write(candidates, [_pair(["missing"], ["other"], "ENT_RELATOR", "ENT_ASSUNTO")])
    with pytest.raises(ValueError, match="Missing original annotation"):
        audit_reviewer_label_priority(annotations, candidates, tmp_path / "out")
