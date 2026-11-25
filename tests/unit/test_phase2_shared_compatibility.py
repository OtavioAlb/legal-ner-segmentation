"""Regression contract for legacy Phase 2 exports after shared extraction.

Only synthetic Label Studio tasks are used. The legacy imports must remain stable.
"""
import json

import pytest

from legal_nlp.annotations.decisions import decision, geometry
from legal_nlp.annotations.identity import NAMES, identity
from legal_nlp.io.label_studio import annotation, extract, load
from legal_nlp import phase2_audit_v2 as legacy
from legal_nlp.phase2_checkbox_review import reviewer_name


def task(reviewer=7, updated=7, with_checkbox=True):
    entries = [
        {"id": "r1", "type": "labels",
         "value": {"labels": ["ENT_COMARCA"], "start": 2, "end": 9,
                   "text": "comarca"}},
        {"id": "r1", "type": "textarea",
         "value": {"text": ["primeiro", "segundo"]}},
    ]
    if with_checkbox:
        entries.append({"id": "r1", "type": "choices",
                        "value": {"choices": ["Limite impreciso"]}})
    return {
        "id": 123,
        "updated_by": updated,
        "data": {"idacordao": 190001},
        "annotations": [
            {"completed_by": reviewer, "was_cancelled": False, "result": entries}
        ],
    }


def test_legacy_names_are_exact_shared_functions():
    assert legacy.load is load
    assert legacy.annotation is annotation
    assert legacy.extract is extract
    assert legacy.identity is identity
    assert legacy.geometry is geometry
    assert legacy.decision is decision
    assert legacy.NAMES is NAMES


def test_loader_and_extractor_preserve_public_shape(tmp_path):
    path = tmp_path / "label_studio.json"
    t = task()
    path.write_text(json.dumps([t], ensure_ascii=False), encoding="utf-8")
    assert load(path) == {"190001": t}
    spans, choices, comments = extract(t)
    assert spans == {
        "r1": {"label": "ENT_COMARCA", "start": 2, "end": 9, "text": "comarca"}
    }
    assert choices == {"r1": "Limite impreciso"}
    assert comments == {"r1": "primeiro | segundo"}


def test_source_duplicate_documents_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps([task(), task()]), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate document"):
        load(path)


def test_reviewer_replacement_preserves_legacy_rule():
    replacement = task(reviewer=10, updated=3, with_checkbox=True)
    assert identity(replacement) == ("3", "substituição", True)
    assert reviewer_name("10") == "Teresa"
    assert reviewer_name("3") == "Tiago"
    not_completed = task(reviewer=10, updated=3, with_checkbox=False)
    assert identity(not_completed) == ("10", "Teresa", False)


def test_automatic_decisions_preserve_semantics():
    original = {"label": "ENT_COMARCA", "start": 2, "end": 9}
    assert decision(original, original, None) == "correto_automatico"
    assert decision(original, {**original, "label": "ENT_RELATOR"}, None) == (
        "incorreto_automatico"
    )
    assert decision(original, {**original, "end": 10}, None) == (
        "limite_impreciso_automatico"
    )
    assert decision(original, original, "Incorreto") == "incorreto"
    assert decision(None, original, None) == "nova_regiao"
    assert decision(original, None, None) == "nao_avaliada"
