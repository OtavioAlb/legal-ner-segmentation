"""Synthetic diagnostics: no judicial text or personal data."""
import json
from legal_nlp.phase2_mismatch_diagnostics import diagnose

def test_classifies_unique_local_shift(tmp_path):
    item = {
        "id": 1, "project": 11,
        "data": {"idacordao": 123, "acordao": "aa bbbb cc"},
        "annotations": [{"result": [{"type": "labels", "value": {
            "start": 2, "end": 6, "text": "bbbb", "labels": ["ENT_CLASSE"]
        }}]}],
    }
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps([item]))
    b.write_text("[]")
    report = diagnose(a, b, tmp_path / "out")
    assert report["total_mismatches"] == 1
    assert report["diagnostic_reasons"]["unique_nearby_exact_match"] == 1
    assert report["candidate_shifts_top"][0] == {"shift": 1, "count": 1}

def test_exact_text_not_flagged(tmp_path):
    item = {
        "id": 1, "data": {"idacordao": 321, "acordao": "alpha"},
        "annotations": [{"result": [{"type": "labels", "value": {
            "start": 0, "end": 5, "text": "alpha", "labels": ["ENT_CLASSE"]
        }}]}],
    }
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps([item]))
    b.write_text("[]")
    report = diagnose(a, b, tmp_path / "out")
    assert report["total_mismatches"] == 0
