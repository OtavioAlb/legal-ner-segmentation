"""Synthetic fixtures only: new-region triage semantics."""
from legal_nlp.phase2_new_region_triage import triage


def _task(project, results):
    return {"project": project,
            "data": {"idacordao": 12345, "acordao": "alpha beta"},
            "annotations": [{"completed_by": 1, "result": results}]}


def _label(key, start, end, name):
    return {"id": key, "type": "labels",
            "value": {"start": start, "end": end, "labels": [name]}}


def _choice(key, answer):
    return {"id": key, "type": "choices",
            "value": {"choices": [answer]}}


def _comment(key, txt):
    return {"id": key, "type": "textarea", "value": {"text": [txt]}}


def test_distinguishes_explicit_addition_with_candidate():
    source = [_task(6, [_label("old", 0, 5, "ENT_CLASSE")])]
    review = [_task(11, [
        _label("old", 0, 5, "ENT_CLASSE"),
        _choice("old", "Incorreto"),
        _label("new", 0, 5, "ENT_ASSUNTO"),
        _comment("new", "Nova anotação"),
    ])]
    report, regions, shared, ambiguous = triage(source, review)
    assert report["counts"]["explicit_new_with_candidate"] == 1
    assert regions[0]["candidate_count"] == 1
    assert not shared
    assert not ambiguous


def test_cross_review_new_regions_match_without_shared_id():
    source = [_task(6, [_label("old", 0, 5, "ENT_CLASSE")])]
    review = [
        _task(11, [_label("old", 0, 5, "ENT_CLASSE"),
                   _choice("old", "Certo"),
                   _label("new-A", 6, 10, "ENT_ASSUNTO")]),
        _task(17, [_label("old", 0, 5, "ENT_CLASSE"),
                   _choice("old", "Certo"),
                   _label("new-B", 6, 10, "ENT_ASSUNTO")]),
    ]
    report, _, shared, ambiguous = triage(source, review)
    assert report["counts"]["exact_cross_review_new_region_pairs"] == 1
    assert shared[0]["project_11_region_ids"] == ["new-A"]
    assert shared[0]["project_17_region_ids"] == ["new-B"]
    assert not ambiguous
