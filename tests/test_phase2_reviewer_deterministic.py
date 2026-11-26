"""Regression tests for deterministic reviewer comparisons; synthetic data only."""
from legal_nlp.phase2_reviewer_deterministic import audit_reviewer, classify


def span(rid, label, start, end, choice=None):
    entries = [{"id": rid, "type": "labels",
                "value": {"labels": [label], "start": start, "end": end}}]
    if choice:
        entries.append({"id": rid, "type": "choices",
                        "value": {"choices": [choice]}})
    return entries


def task(doc, reviewer, results):
    return {"data": {"idacordao": doc},
            "annotations": [{"completed_by": reviewer, "result": results}]}


def test_classification_rules():
    original = {"label": "ENT_COMARCA", "start": 0, "end": 10}
    assert classify(original, dict(original)) == "correto_automatico"
    assert classify(original, {"label": "ENT_PROCESSO", "start": 0, "end": 10}) == "incorreto_automatico"
    assert classify(original, {"label": "ENT_COMARCA", "start": 2, "end": 10}) == "limite_impreciso_automatico"
    assert classify(original, {"label": "ENT_PROCESSO", "start": 2, "end": 10}) == "incorreto_automatico"
    assert classify(None, dict(original)) == "nova_regiao"
    assert classify(original, dict(original), "Incorreto") == "Incorreto"


def test_teresa_style_review_keeps_new_as_manual_and_absence_unreviewed():
    original = [task(16898292, 9,
                     span("a", "ENT_COMARCA", 1, 10) +
                     span("missing", "ENT_PROCESSO", 11, 19))]
    review = [task(16898292, 10,
                   span("a", "ENT_COMARCA", 1, 10) +
                   span("new", "ENT_NORMA_LEI", 20, 35))]
    rows, summary = audit_reviewer(original, {17: review}, 10)
    assert summary["decision_counts"] == {
        "correto_automatico": 1, "nao_avaliada": 1, "nova_regiao": 1,
    }
    assert {r["region_id"]: r["decision"] for r in rows} == {
        "a": "correto_automatico",
        "missing": "nao_avaliada",
        "new": "nova_regiao",
    }
    assert all(r["avaliador_id"] == 10 for r in rows)


def test_other_reviewer_is_ignored():
    originals = [task(1, 7, span("a", "ENT_COMARCA", 0, 4))]
    review = [task(1, 5, span("a", "ENT_COMARCA", 0, 4))]
    rows, summary = audit_reviewer(originals, {11: review}, 10)
    assert rows == []
    assert summary["total_regions"] == 0
