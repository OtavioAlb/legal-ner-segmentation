"""No judicial text: verify residual fingerprints and grouping by source region."""
import json

from legal_nlp.datasets.residual_text_fingerprints import (
    fingerprint, inspect_residuals,
)


def task(doc, reviewer, raw):
    return {
        "id": int(doc), "data": {"idacordao": int(doc), "acordao": "AÇÃO e lei"},
        "updated_by": reviewer,
        "annotations": [{"completed_by": reviewer, "result": [
            {"id": "reg1", "type": "labels",
             "value": {"labels": ["ENT_PARTE_ATIVA"], "start": 0,
                       "end": 4, "text": raw}},
            {"id": "reg1", "type": "choices",
             "value": {"choices": ["Certo"]}},
        ]}],
    }


def test_equal_length_but_different_text_is_detected():
    d = fingerprint("ACAO", "AÇÃO")
    assert d["length_difference"] == 0
    assert d["edit_operation_counts"]["replace"] >= 1
    assert d["source_sha256"] != d["document_slice_sha256"]
    assert d["first_difference_source_position"] is not None
    assert "ACAO" not in str(d)


def test_nfc_equivalence_is_only_diagnostic():
    d = fingerprint("A" + "C" + "\u0327" + "A" + "\u0303" + "O", "AÇÃO")
    assert d["unicode_nfc_equivalent"] is True
    assert d["source_sha256"] != d["document_slice_sha256"]


def test_three_repeated_occurrences_one_region(tmp_path):
    paths = []
    for name, user in (("original", 8), ("11", 7), ("17", 5)):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps([task(42, user, "ACAO")]), encoding="utf-8")
        paths.append(path)
    before = [p.read_bytes() for p in paths]
    result = inspect_residuals(*paths)
    assert result["occurrences"] == 3
    assert result["unique_regions_by_document_and_region_id"] == 1
    assert len(result["regions"][0]["projects"]) == 3
    assert result["source_correction_performed"] is False
    assert result["automatic_adjudication_performed"] is False
    assert "ACAO" not in json.dumps(result)
    assert [p.read_bytes() for p in paths] == before


def test_exact_and_known_literal_escapes_are_not_residual(tmp_path):
    paths = []
    for name, user, raw in (
        ("original", 8, "AÇÃO"),
        ("11", 7, "AÇÃO"),
        ("17", 5, "AÇÃO"),
    ):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps([task(42, user, raw)]), encoding="utf-8")
        paths.append(path)
    report = inspect_residuals(*paths)
    assert report["occurrences"] == 0
