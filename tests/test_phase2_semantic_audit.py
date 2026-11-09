"""Synthetic-only tests of ID-first Phase 2 review decisions."""
import json
from legal_nlp.phase2_semantic_audit import audit


def make_row(project, labels, choice=None, region_id="region-a"):
    results = [{"id": region_id, "type": "labels", "value": {
        "start": 0, "end": 5, "text": "alpha", "labels": labels,
    }}]
    if choice:
        results.append({"id": region_id, "type": "choices",
                        "value": {"choices": [choice]}})
    return {
        "project": project, "data": {"idacordao": 12345678, "acordao": "alpha beta"},
        "annotations": [{"result": results, "completed_by": 1}],
        "annotated_by": 1, "evaluated_by": 2,
    }


def test_stable_id_tracks_label_edit_and_choice(tmp_path):
    original = [make_row(6, ["ENT_CLASSE"])]
    reviews = [make_row(11, ["ENT_ASSUNTO"], "Incorreto"),
               make_row(17, ["ENT_CLASSE"], "Certo")]
    a, b = tmp_path / "original.json", tmp_path / "reviews.json"
    a.write_text(json.dumps(original))
    b.write_text(json.dumps(reviews))
    summary = audit(a, b, tmp_path / "out")
    assert summary["original_documents"] == 1
    assert summary["evaluation_records"] == 2
    assert summary["decision_regions"] == 2
    assert summary["counts"]["change:label_only"] == 1
    assert summary["counts"]["review_comparison:different_span_and_choice"] == 1


def test_new_id_is_not_assumed_final(tmp_path):
    original = [make_row(6, ["ENT_CLASSE"])]
    reviews = [make_row(11, ["ENT_CLASSE"], "Certo", "new-region")]
    a, b = tmp_path / "original.json", tmp_path / "reviews.json"
    a.write_text(json.dumps(original))
    b.write_text(json.dumps(reviews))
    summary = audit(a, b, tmp_path / "out")
    assert summary["counts"]["relation:new_id"] == 1
    assert summary["counts"]["flag:NEW_REGION_ID_REQUIRES_CLASSIFICATION"] == 1
