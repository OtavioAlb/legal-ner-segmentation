"""Synthetic tests for structural alert refinement."""
import copy
import pytest
from legal_nlp.phase2_structural_alerts import refine


def label(rid, start, end, name):
    return {"id": rid, "type": "labels",
            "value": {"start": start, "end": end, "labels": [name]}}


def choice(rid, value):
    return {"id": rid, "type": "choices", "value": {"choices": [value]},
            "origin": "manual"}


def task(original, reviewed, project=11):
    return {"project": project, "data": {"idacordao": 123, "acordao": "synthetic"},
            "annotations": [{"completed_by": 8, "result": reviewed,
                             "prediction": {"result": original}}]}


def alert(new, labelname, end, flags, *, original_ids=(), alternative_ids=(),
          duplicate_ids=(), overlap_ids=()):
    return {
        "idacordao": "123", "project": "11", "region_id": new,
        "labels": [labelname], "start": 1, "end": end,
        "structural_flags": flags, "original_exact_ids": list(original_ids),
        "same_boundary_other_label_ids": list(alternative_ids),
        "duplicate_new_ids": list(duplicate_ids),
        "strong_overlap_original_ids": list(overlap_ids),
        "comment_category": "nova_anotacao_exata",
    }


def test_ner_seg_can_coexist_and_preserves_human_evidence():
    before = [label("original", 1, 6, "SEG_FUNDAMENTO_DECISAO")]
    reviewed = [*before, choice("original", "Incorreto"),
                label("new", 1, 6, "ENT_NORMA_ARTIGO")]
    data = task(before, reviewed)
    saved = copy.deepcopy(data)
    report, rows = refine([data], [alert("new", "ENT_NORMA_ARTIGO", 6,
                                         ["same_boundary_different_label"],
                                         alternative_ids=["original"])])
    assert report["counts"]["category:coincidencia_ner_seg"] == 1
    assert rows[0]["original_evidence"][0]["choice_values"] == ["Incorreto"]
    assert rows[0]["gold_status"] == "not_adjudicated"
    assert data == saved


def test_ner_conflict_is_not_a_ner_seg_overlap():
    original = [label("original", 1, 6, "ENT_NORMA_LEI")]
    reviewed = [*original, label("new", 1, 6, "ENT_NORMA_ARTIGO")]
    _, rows = refine([task(original, reviewed)], [
        alert("new", "ENT_NORMA_ARTIGO", 6, ["same_boundary_different_label"],
              alternative_ids=["original"])])
    assert rows[0]["primary_category"] == "rotulo_alternativo_mesma_tarefa"


def test_original_relabel_still_keeps_exact_duplicate_evidence():
    old = [label("old", 1, 6, "SEG_EMENTA")]
    review = [label("old", 1, 6, "ENT_LEI_CODIFICADA"),
              choice("old", "Certo"), label("new", 1, 6, "SEG_EMENTA")]
    _, rows = refine([task(old, review)], [
        alert("new", "SEG_EMENTA", 6,
              ["exact_original_duplicate", "same_boundary_different_label"],
              original_ids=["old"], alternative_ids=["old"])])
    assert rows[0]["original_evidence"][0]["original_region_relabelled"]
    assert rows[0]["primary_category"] == "copia_exata_do_original"


def test_same_new_signature_with_rejected_human_neighbor():
    old = [label("old", 1, 6, "ENT_A")]
    reviewed = [*old, label("rejected", 1, 7, "ENT_B"),
                choice("rejected", "Incorreto"), label("new", 1, 7, "ENT_B")]
    _, rows = refine([task(old, reviewed)], [
        alert("new", "ENT_B", 7, ["duplicate_new_in_same_review"],
              duplicate_ids=["rejected"])])
    assert rows[0]["duplicate_new_evidence"][0]["choice_values"] == ["Incorreto"]


def test_boundary_adjustment_related_to_imprecise_human_choice():
    old = [label("old", 1, 6, "ENT_A")]
    reviewed = [*old, choice("old", "Limite impreciso"),
                label("new", 1, 7, "ENT_A")]
    _, rows = refine([task(old, reviewed)], [
        alert("new", "ENT_A", 7, ["strong_overlap_same_label"],
              overlap_ids=["old"])])
    assert rows[0]["primary_category"] == "ajuste_de_limite_possivel"
    assert rows[0]["original_evidence"][0]["choice_values"] == ["Limite impreciso"]


def test_empty_alert_set():
    old = [label("old", 1, 6, "ENT_A")]
    report, rows = refine([task(old, old)], [])
    assert not rows and report["counts"] == {}


def test_unknown_candidate_is_rejected():
    old = [label("old", 1, 6, "ENT_A")]
    review = [*old, label("new", 1, 6, "ENT_B")]
    with pytest.raises(ValueError, match="Unknown original ID"):
        refine([task(old, review)], [alert(
            "new", "ENT_B", 6, ["same_boundary_different_label"],
            alternative_ids=["missing"])])


def test_corrupted_input_signature_is_rejected():
    old = [label("old", 1, 6, "ENT_A")]
    review = [*old, label("new", 1, 6, "ENT_B")]
    with pytest.raises(ValueError, match="Triage signature differs"):
        refine([task(old, review)], [alert(
            "new", "ENT_B", 7, ["same_boundary_different_label"],
            alternative_ids=["old"])])


def test_repeated_region_is_rejected():
    old = [label("old", 1, 6, "ENT_A")]
    review = [*old, label("new", 1, 6, "ENT_B")]
    row = alert("new", "ENT_B", 6, ["same_boundary_different_label"],
                alternative_ids=["old"])
    with pytest.raises(ValueError, match="Duplicate triage region"):
        refine([task(old, review)], [row, row])
