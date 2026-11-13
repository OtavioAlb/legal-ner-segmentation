"""Synthetic tests: original spans are immutable; concordance uses label+offsets only."""
import json
import pytest
from legal_nlp.phase2_geometry_audit import audit, write, load


def task(doc, by, spans, updated=None):
    result = []
    for rid, label, start, end, choice in spans:
        result.append({"id": rid, "type": "labels",
                       "value": {"labels": [label], "start": start,
                                 "end": end, "text": "synthetic"}})
        if choice:
            result.append({"id": rid, "type": "choices",
                           "value": {"choices": [choice]}})
    return {"data": {"idacordao": doc}, "updated_by": by if updated is None else updated,
            "annotations": [{"completed_by": by, "result": result}]}


def exports(tmp_path, original, a, b):
    paths = []
    for name, task_data in [("original", original), ("11", a), ("17", b)]:
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps([task_data]), encoding="utf-8")
        paths.append(path)
    return paths


def test_proposal_is_not_original_even_when_both_reviewers_agree(tmp_path):
    base = task(12, 9, [("a", "ENT_COMARCA", 0, 7, None)])
    one = task(12, 5, [("a", "ENT_PROCESSO", 0, 7, "Incorreto")])
    two = task(12, 7, [("a", "ENT_PROCESSO", 0, 7, "Certo")])
    files = exports(tmp_path, base, one, two)
    snapshots = [p.read_bytes() for p in files]
    sheets, hashes = audit(*files)
    row = sheets["Consolidados"][0]
    assert row["status"] == "CONCORDANCIA_ALTERACAO"
    assert row["label_original"] == "ENT_COMARCA"
    assert row["label_proposta_concordante"] == "ENT_PROCESSO"
    assert row["original_inalterado"] is False
    assert [p.read_bytes() for p in files] == snapshots
    summary = write(sheets, hashes, tmp_path / "outputs")
    assert summary["counts"]["concordancia_alteracao"] == 1


def test_disagreeing_checkboxes_do_not_change_geometry_agreement(tmp_path):
    base = task(1, 9, [("a", "SEG_EMENTA", 0, 20, None)])
    one = task(1, 5, [("a", "SEG_EMENTA", 0, 20, "Certo")])
    two = task(1, 7, [("a", "SEG_EMENTA", 0, 20, "Incorreto")])
    sheets, _ = audit(*exports(tmp_path, base, one, two))
    assert sheets["Consolidados"][0]["status"] == "CONCORDANCIA_ORIGINAL"


def test_new_region_with_same_geometry_does_not_modify_original(tmp_path):
    base = task(4, 9, [("a", "ENT_COMARCA", 0, 5, None)])
    one = task(4, 5, [("a", "ENT_COMARCA", 0, 5, None),
                      ("new", "ENT_COMARCA", 0, 5, None)])
    two = task(4, 7, [("a", "ENT_COMARCA", 0, 5, None)])
    sheets, _ = audit(*exports(tmp_path, base, one, two))
    assert len(sheets["Consolidados"]) == 1
    assert sheets["Revisao_novas"][0]["mesma_geometria_original_ids"] == "a"
    assert sheets["Revisao_novas"][0]["adjudicada"] is False


def test_pending_teresa_not_counted_as_agreement(tmp_path):
    base = task(2, 9, [("a", "ENT_COMARCA", 0, 5, None)])
    one = task(2, 10, [("a", "ENT_COMARCA", 0, 5, None)])
    two = task(2, 7, [("a", "ENT_COMARCA", 0, 5, "Certo")])
    sheets, _ = audit(*exports(tmp_path, base, one, two))
    assert sheets["Revisao_originais"][0]["status"] == "PENDENTE_AVALIADOR"
    assert sheets["Consolidados"] == []


def test_tiago_replacement_uses_updated_by_when_choices_exist(tmp_path):
    base = task(2, 9, [("a", "ENT_COMARCA", 0, 5, None)])
    one = task(2, 10, [("a", "ENT_COMARCA", 0, 5, "Certo")], updated=3)
    two = task(2, 7, [("a", "ENT_COMARCA", 0, 5, "Certo")])
    sheets, _ = audit(*exports(tmp_path, base, one, two))
    assert sheets["Revisao_originais"][0]["avaliador_11_id"] == "3"
    assert len(sheets["Consolidados"]) == 1


def test_cross_review_new_regions_remain_pending(tmp_path):
    base = task(2, 9, [("a", "ENT_COMARCA", 0, 5, None)])
    one = task(2, 5, [("a", "ENT_COMARCA", 0, 5, None),
                      ("x", "SEG_EMENTA", 10, 20, None)])
    two = task(2, 7, [("a", "ENT_COMARCA", 0, 5, None),
                      ("y", "SEG_EMENTA", 10, 20, None)])
    sheets, _ = audit(*exports(tmp_path, base, one, two))
    assert len(sheets["Revisao_novas"]) == 1
    assert sheets["Revisao_novas"][0]["presente_11"]
    assert sheets["Revisao_novas"][0]["presente_17"]
    assert len(sheets["Consolidados"]) == 1


def test_duplicate_document_id_is_rejected(tmp_path):
    row = task(1, 9, [("a", "ENT_COMARCA", 0, 5, None)])
    path = tmp_path / "duplicates.json"
    path.write_text(json.dumps([row, row]), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate document"):
        load(path)
