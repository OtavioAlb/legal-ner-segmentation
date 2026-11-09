"""Synthetic fixtures only; do not commit judicial text or evaluations."""
import copy
import pytest
from legal_nlp.phase2_new_region_comments import triage


def label(rid, lo, hi, cls):
    return {"id": rid, "type": "labels", "value": {"start": lo, "end": hi, "labels": [cls]}}


def choice(rid, value):
    return {"id": rid, "type": "choices", "value": {"choices": [value]}}


def comment(rid, text):
    return {"id": rid, "type": "textarea", "value": {"text": [text]}}


def task(project=11, old=None, result=None):
    baseline = old if old is not None else [label("old", 0, 5, "ENT_1")]
    return {"data": {"idacordao": 123, "acordao": "abcdefgh"}, "project": project,
            "annotations": [{"completed_by": 9, "result": result or [],
                             "prediction": {"result": baseline}}]}


def test_explicit_declaration_not_gold_and_no_mutation():
    review = task(result=[label("old", 0, 5, "ENT_1"),
                          label("new", 6, 8, "ENT_2"), comment("new", "Nova anotação")])
    saved = copy.deepcopy(review)
    report, rows, missing = triage([review])
    assert rows[0]["triage_status"] == "candidato_inclusao_declarada"
    assert rows[0]["observacoes"] == ["Nova anotação"]
    assert rows[0]["gold_status"] == "not_adjudicated"
    assert report["counts"]["new_without_choice"] == 1
    assert missing == []
    assert review == saved


def test_variant_and_unmarked_separately():
    review = task(result=[label("old", 0, 5, "ENT_1"),
                          label("n1", 6, 7, "ENT_2"), comment("n1", "nova observação"),
                          label("n2", 7, 8, "ENT_2")])
    _, rows, _ = triage([review])
    assert {x["triage_status"] for x in rows} == {
        "candidato_inclusao_variante", "inclusao_nao_confirmada"}


def test_duplicate_new_and_missing_original_pending():
    review = task(result=[label("copy", 0, 5, "ENT_1"),
                          label("copy2", 0, 5, "ENT_1")])
    report, rows, missing = triage([review])
    assert len(rows) == 2 and len(missing) == 1
    assert all(x["triage_status"] ==
               "inspecionar_possivel_duplicacao_ou_substituicao" for x in rows)
    assert all("duplicate_new_in_same_review" in x["structural_flags"] for x in rows)
    assert report["counts"]["originals_missing"] == 1


def test_same_offsets_different_labels_are_evidence_not_error():
    review = task(result=[label("old", 0, 5, "ENT_1"),
                          label("new", 0, 5, "SEG_1"), comment("new", "nova anotação")])
    _, rows, _ = triage([review])
    assert rows[0]["structural_flags"] == ["same_boundary_different_label"]
    assert rows[0]["gold_status"] == "not_adjudicated"


def test_existing_choice_excludes_new_from_pending():
    review = task(result=[label("old", 0, 5, "ENT_1"),
                          label("new", 6, 8, "ENT_2"), choice("new", "Certo")])
    report, rows, _ = triage([review])
    assert rows == [] and report["counts"]["new_with_existing_choice"] == 1


def test_crossreview_is_only_evidence():
    a = task(result=[label("old", 0, 5, "ENT_1"), label("newA", 6, 8, "ENT_2")])
    b = task(project=17, result=[label("old", 0, 5, "ENT_1"),
                                 label("newB", 6, 8, "ENT_2")])
    report, rows, _ = triage([a, b])
    assert report["counts"]["crossreview_exact_signature"] == 2
    assert all(x["crossreview_exact_signatures"] for x in rows)
    assert all(x["gold_status"] == "not_adjudicated" for x in rows)


def test_different_original_snapshots_fail():
    a = task(result=[label("old", 0, 5, "ENT_1")])
    b = task(project=17, old=[label("old", 1, 5, "ENT_1")],
             result=[label("old", 1, 5, "ENT_1")])
    with pytest.raises(ValueError, match="snapshots disagree"):
        triage([a, b])
