"""Synthetic Phase 2 audit tests; no source documents or actual people."""
import json

from legal_nlp.phase2_audit import audit_phase2


def test_audit_coverage_and_span_comparisons(tmp_path):
    def task(doc, project, user, task_id):
        return {
            "id": task_id, "project": project,
            "data": {"idacordao": doc, "acordao": "alpha beta"},
            "annotations": [{"completed_by": user, "result": [
                {"type": "labels", "value": {
                    "start": 0, "end": 5, "text": "alpha",
                    "labels": ["ENT_CLASSE"]}}
            ]}],
        }
    original = [task(11122233, 6, 1, 1)]
    evaluated = [
        {**task(11122233, 11, 2, 2), "annotated_by": 1,
         "evaluated_by": 2, "identity_validation_status": "assignment_consistent"},
        {**task(11122233, 17, 3, 3), "annotated_by": 1,
         "evaluated_by": 3, "identity_validation_status": "assignment_consistent"},
    ]
    source_paths = [tmp_path / x for x in ("original.json", "reviews.json", "labels.json")]
    for path, obj in zip(source_paths, (original, evaluated, {"labels": ["ENT_CLASSE"]})):
        path.write_text(json.dumps(obj), encoding="utf-8")
    output = tmp_path / "audit"
    report = audit_phase2(*source_paths, output)
    assert report["evaluations"] == 2
    assert report["evaluation_coverage"]["2"] == 1
    assert report["issue_counts"] == {}
    assert report["comparison_record_counts"]["evaluation_vs_evaluation"] == 2
    assert report["comparison_totals"]["original_vs_evaluation"]["unchanged"] == 2
    assert (output / "review_queue.jsonl").exists()
