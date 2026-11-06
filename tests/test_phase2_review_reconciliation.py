"""Synthetic-only decision review reconciliation tests."""
import json
from legal_nlp.phase2_review_reconciliation import reconcile, run


def task(project, reviewer, *items):
    return {"project": project, "id": reviewer, "data": {
        "idacordao": 12345, "acordao": "alpha beta gamma"
    }, "annotations": [{"completed_by": reviewer, "result": list(items)}]}


def label(rid, start, end, tag):
    return {"id": rid, "type": "labels", "value": {
        "start": start, "end": end, "labels": [tag],
    }}


def choice(rid, state):
    return {"id": rid, "type": "choices", "value": {"choices": [state]}}


def test_missing_choice_not_agreement():
    original = [task(6, 1, label("s1", 0, 5, "ENT_CLASSE"))]
    evaluated = [
        task(11, 2, label("s1", 0, 5, "ENT_CLASSE"), choice("s1", "Certo")),
        task(17, 3, label("s1", 0, 5, "ENT_CLASSE")),
    ]
    report, candidates, comparisons = reconcile(original, evaluated)
    assert report["counts"]["one_choice_missing"] == 1
    assert comparisons[0]["status"] == "one_choice_missing"
    assert not candidates


def test_new_region_candidate_not_auto_linked():
    original = [task(6, 1, label("s1", 0, 5, "ENT_CLASSE"))]
    evaluated = [task(11, 2,
                      label("s1", 0, 5, "ENT_CLASSE"), choice("s1", "Incorreto"),
                      label("new", 0, 5, "ENT_ASSUNTO"))]
    report, candidates, _ = reconcile(original, evaluated)
    assert report["counts"]["new_regions_with_candidate"] == 1
    assert candidates[0]["candidate_count"] == 1
    assert candidates[0]["status"] == "requires_manual_classification"


def test_creates_csv(tmp_path):
    original = [task(6, 1, label("s1", 0, 5, "ENT_CLASSE"))]
    evaluated = [task(11, 2, label("s1", 0, 5, "ENT_CLASSE"), choice("s1", "Certo"))]
    a, b = tmp_path / "original.json", tmp_path / "eval.json"
    a.write_text(json.dumps(original))
    b.write_text(json.dumps(evaluated))
    report = run(a, b, tmp_path / "out")
    assert report["evaluation_records"] == 1
    assert (tmp_path / "out" / "paired_choice_review.csv").exists()
