"""Synthetic tests for checkbox conflict isolation and immutable Phase-2 originals."""
import json

from legal_nlp.phase2_audit_v2 import audit, decision, columns


def task(doc, user, regions, updated=None):
    entries = []
    for rid, label, start, end, choice in regions:
        entries.append({"id": rid, "type": "labels", "value": {
            "labels": [label], "start": start, "end": end, "text": "synthetic"}})
        if choice:
            entries.append({"id": rid, "type": "choices",
                            "value": {"choices": [choice]}})
    return {"id": doc, "data": {"idacordao": doc},
            "updated_by": updated if updated is not None else user,
            "annotations": [{"completed_by": user, "result": entries}]}


def files(tmp_path, original, left, right):
    paths = []
    for filename, entry in (("original", original), ("left", left), ("right", right)):
        path = tmp_path / (filename + ".json")
        path.write_text(json.dumps([entry]), encoding="utf-8")
        paths.append(path)
    return paths


def test_identical_geometry_conflicting_explicit_choices_isolated(tmp_path):
    original = task(1, 8, [("a", "ENT_COMARCA", 0, 12, None)])
    left = task(1, 7, [("a", "ENT_COMARCA", 0, 12, "Certo")])
    right = task(1, 5, [("a", "ENT_COMARCA", 0, 12, "Incorreto")])
    paths = files(tmp_path, original, left, right)
    before = [path.read_bytes() for path in paths]
    sheets, metrics, _ = audit(*paths)
    assert metrics["isolados_checkbox_divergente"] == 1
    assert metrics["consolidados_estruturais_sem_conflito_checkbox"] == 0
    assert sheets["Divergencia_checkbox"][0]["label_original"] == "ENT_COMARCA"
    assert all(path.read_bytes() == data for path, data in zip(paths, before))


def test_identical_reviewers_changes_stored_as_proposal(tmp_path):
    original = task(1, 8, [("a", "ENT_COMARCA", 0, 12, None)])
    left = task(1, 7, [("a", "ENT_PROCESSO", 0, 12, "Incorreto")])
    right = task(1, 5, [("a", "ENT_PROCESSO", 0, 12, "Incorreto")])
    sheets, metrics, _ = audit(*files(tmp_path, original, left, right))
    assert metrics["concordancia_alteracao"] == 1
    row = sheets["Consolidados"][0]
    assert row["label_original"] == "ENT_COMARCA"
    assert row["label_proposta_concordante"] == "ENT_PROCESSO"


def test_auto_choice_does_not_override_explicit_negative(tmp_path):
    original = task(1, 8, [("a", "ENT_COMARCA", 0, 12, None)])
    left = task(1, 7, [("a", "ENT_COMARCA", 0, 12, None)])
    right = task(1, 5, [("a", "ENT_COMARCA", 0, 12, "Incorreto")])
    sheets, _, _ = audit(*files(tmp_path, original, left, right))
    row = sheets["Divergencia_checkbox"][0]
    assert row["projeto_11_decisao"] == "correto_automatico"
    assert row["projeto_17_decisao"] == "incorreto"


def test_new_region_manual_even_if_no_checkbox(tmp_path):
    original = task(1, 8, [("a", "ENT_COMARCA", 0, 12, None)])
    left = task(1, 7, [("a", "ENT_COMARCA", 0, 12, "Certo"),
                        ("new_11", "SEG_EMENTA", 20, 35, None)])
    right = task(1, 5, [("a", "ENT_COMARCA", 0, 12, "Certo"),
                         ("new_17", "SEG_EMENTA", 20, 35, None)])
    sheets, metrics, _ = audit(*files(tmp_path, original, left, right))
    assert metrics["novas_coincidentes"] == 1
    assert len(sheets["Revisao_novas"]) == 2
    assert {row["decisao"] for row in sheets["Revisao_novas"]} == {"nova_regiao"}
    assert {row["projeto_avaliacao"] for row in sheets["Revisao_novas"]} == {11, 17}
    assert len(sheets["Consolidados"]) == 2
    new = next(row for row in sheets["Consolidados"] if row["status"] == "CONSOLIDADA_NOVA")
    assert new["projeto_11_region_id"] == "new_11"
    assert new["projeto_17_region_id"] == "new_17"
    assert new["canonical_region_id"].startswith("new_")
    assert {row["canonical_region_id"] for row in sheets["Revisao_novas"]} == {new["canonical_region_id"]}
    assert metrics["novas_consolidadas"] == 1


def test_tiago_replacement_name_and_order(tmp_path):
    original = task(1, 8, [("a", "ENT_COMARCA", 0, 12, None)])
    left = task(1, 10, [("a", "ENT_COMARCA", 0, 12, "Certo")], updated=3)
    right = task(1, 5, [("a", "ENT_COMARCA", 0, 12, "Certo")])
    sheets, _, _ = audit(*files(tmp_path, original, left, right))
    row = sheets["Consolidados"][0]
    assert row["projeto_11_avaliador_nome"] == "substituição"
    keys = columns("Consolidados", sheets["Consolidados"])
    assert keys.index("anotador_original_nome") < keys.index("projeto_11_avaliador_id")
    assert keys.index("projeto_11_observacao") < keys.index("projeto_17_avaliador_id")


def test_both_missing_choices_are_auto_classified():
    old = {"label": "ENT_COMARCA", "start": 0, "end": 12}
    assert decision(old, old, None) == "correto_automatico"
    assert decision(old, {**old, "label": "ENT_PROCESSO"}, None) == "incorreto_automatico"
    assert decision(old, {**old, "end": 13}, None) == "limite_impreciso_automatico"
    assert decision(None, old, None) == "nova_regiao"


def test_no_redundant_raw_checkbox_and_new_region_has_one_evaluator(tmp_path):
    original = task(1, 8, [("a", "ENT_COMARCA", 0, 12, None)])
    left = task(1, 7, [("a", "ENT_COMARCA", 0, 12, "Certo"),
                        ("new_11", "SEG_EMENTA", 20, 35, None)])
    right = task(1, 5, [("a", "ENT_COMARCA", 0, 12, "Incorreto")])
    sheets, metrics, _ = audit(*files(tmp_path, original, left, right))
    columns_orig = columns("Divergencia_checkbox", sheets["Divergencia_checkbox"])
    assert not any("checkbox_original" in key for key in columns_orig)
    proposal = sheets["Revisao_novas"][0]
    assert proposal["projeto_avaliacao"] == 11
    assert proposal["avaliador_id"] == "7"
    assert proposal["region_id_nova"] == "new_11"
    assert not any(key.startswith("projeto_11_") or key.startswith("projeto_17_") for key in proposal)
    assert metrics["isolados_checkbox_divergente"] == 1


def test_duplicate_new_proposal_same_project_blocks_consolidation(tmp_path):
    original = task(1, 8, [("a", "ENT_COMARCA", 0, 12, None)])
    left = task(1, 7, [("a", "ENT_COMARCA", 0, 12, "Certo"),
                        ("x", "SEG_EMENTA", 20, 35, None),
                        ("x2", "SEG_EMENTA", 20, 35, None)])
    right = task(1, 5, [("a", "ENT_COMARCA", 0, 12, "Certo"),
                         ("y", "SEG_EMENTA", 20, 35, None)])
    sheets, metrics, _ = audit(*files(tmp_path, original, left, right))
    assert metrics["novas_consolidadas"] == 0
    assert len(sheets["Consolidados"]) == 1
    assert all(row["status"] == "PENDENTE_NOVA" for row in sheets["Revisao_novas"])


def test_new_proposal_existing_in_original_is_not_consolidated(tmp_path):
    original = task(1, 8, [("a", "ENT_COMARCA", 0, 12, None)])
    left = task(1, 7, [("a", "ENT_COMARCA", 0, 12, "Certo"),
                        ("new1", "ENT_COMARCA", 0, 12, None)])
    right = task(1, 5, [("a", "ENT_COMARCA", 0, 12, "Certo"),
                         ("new2", "ENT_COMARCA", 0, 12, None)])
    sheets, metrics, _ = audit(*files(tmp_path, original, left, right))
    assert metrics["novas_consolidadas"] == 0
    assert all(row["motivo"] == "nova_duplicada_do_original" for row in sheets["Revisao_novas"])


def test_canonical_id_stable_under_new_region_id_change(tmp_path):
    base = task(1, 8, [("a", "ENT_COMARCA", 0, 12, None)])
    def run(left_id, right_id):
        left = task(1, 7, [("a", "ENT_COMARCA", 0, 12, "Certo"),
                            (left_id, "SEG_EMENTA", 20, 35, None)])
        right = task(1, 5, [("a", "ENT_COMARCA", 0, 12, "Certo"),
                             (right_id, "SEG_EMENTA", 20, 35, None)])
        sheets, _, _ = audit(*files(tmp_path, base, left, right))
        return next(row for row in sheets["Consolidados"]
                    if row["status"] == "CONSOLIDADA_NOVA")
    one, two = run("first", "second"), run("changed", "different")
    assert one["canonical_region_id"] == two["canonical_region_id"]
    assert one["projeto_11_region_id"] != two["projeto_11_region_id"]
    assert one["projeto_17_region_id"] != two["projeto_17_region_id"]
