"""Pure-rule regression tests for Phase 2: no private judicial data."""
import pytest

from legal_nlp.annotations.reviews.checkbox import divergence_problem
from legal_nlp.annotations.reviews.geometry import classify_original_region
from legal_nlp.annotations.reviews.new_regions import classify_new_proposal
from legal_nlp.phase2_checkbox_review import divergence_problem as legacy_checkbox


def span(label="ENT_COMARCA", start=2, end=9):
    return {"label": label, "start": start, "end": end}


def test_checkbox_legacy_alias_and_independent_diagnosis():
    assert legacy_checkbox is divergence_problem
    old = span()
    assert divergence_problem(old, old, "Limite impreciso") == "limite igual original"
    assert divergence_problem(old, old, "Incorreto") == "label igual original"
    assert divergence_problem(old, span(label="ENT_RELATOR"), "Certo") == (
        "checkbox certo com label diferente do original"
    )
    assert divergence_problem(old, span(end=10), "Certo") == (
        "checkbox certo com limite diferente do original"
    )
    assert divergence_problem(old, span(label="ENT_RELATOR", end=10), "Certo") == (
        "checkbox certo com label e limite diferentes do original"
    )
    assert divergence_problem(old, old, "Certo") is None


@pytest.mark.parametrize(
    "left,right,left_decision,right_decision,complete,expected",
    [
        (span(), span(), "correto", "correto", False,
         ("PENDENTE_SUBSTITUICAO", "aguardando_substituicao")),
        (span(), span(end=10), "correto", "limite_impreciso", True,
         ("PENDENTE_GEOMETRIA", "ausencia_ou_divergencia_geometria")),
        (None, span(), "nao_avaliada", "correto", True,
         ("PENDENTE_GEOMETRIA", "ausencia_ou_divergencia_geometria")),
        (span(), span(), "correto_automatico", "incorreto", True,
         ("DIVERGENCIA_CHECKBOX", "checkbox_divergente_geometria_igual")),
        (span(), span(), "correto_automatico", "correto", True,
         ("CONCORDANCIA_ORIGINAL", "")),
        (span(label="ENT_RELATOR"), span(label="ENT_RELATOR"),
         "incorreto", "incorreto", True, ("CONCORDANCIA_AVALIACAO", "")),
    ],
)
def test_cross_review_status_priority(left, right, left_decision, right_decision,
                                      complete, expected):
    assert classify_original_region(
        span(), left, right, left_decision, right_decision, complete
    ) == expected


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"consolidated": True}, ("CONSOLIDADA_NOVA", "")),
        ({"complete": False}, ("PENDENTE_NOVA", "nova_aguardando_substituicao")),
        ({"count_here": 2}, ("PENDENTE_NOVA", "nova_ambigua_ids_duplicados")),
        ({"duplicates_original": True}, ("PENDENTE_NOVA", "nova_duplicada_do_original")),
        ({"same_reviewer": True}, ("PENDENTE_NOVA", "nova_sem_avaliadores_distintos")),
        ({}, ("PENDENTE_NOVA", "nova_coincidente_pendente")),
        ({"same_in_other": False}, ("PENDENTE_NOVA", "nova_unilateral_pendente")),
    ],
)
def test_new_region_reason_priority(overrides, expected):
    args = dict(consolidated=False, complete=True, same_in_other=True,
                count_here=1, count_other=1, duplicates_original=False,
                same_reviewer=False)
    args.update(overrides)
    assert classify_new_proposal(**args) == expected


def test_new_region_without_second_reviewer_remains_pending():
    assert classify_new_proposal(
        consolidated=False, complete=True, same_in_other=False,
        count_here=1, count_other=0, duplicates_original=False,
        same_reviewer=False,
    ) == ("PENDENTE_NOVA", "nova_unilateral_pendente")
