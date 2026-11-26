"""Review-to-review geometry and checkbox disagreement classification.

The output statuses and reasons are legacy Phase 2 constants. No adjudication
is performed here; the function only classifies one original source region.
"""
from __future__ import annotations

from ..decisions import geometry


def classify_original_region(original, review_11, review_17,
                             decision_11: str, decision_17: str,
                             complete: bool) -> tuple[str, str]:
    same = (review_11 is not None and review_17 is not None
            and geometry(review_11) == geometry(review_17))
    conflict = (same and decision_11.removesuffix("_automatico")
                != decision_17.removesuffix("_automatico"))
    if not complete:
        return "PENDENTE_SUBSTITUICAO", "aguardando_substituicao"
    if not same:
        return "PENDENTE_GEOMETRIA", "ausencia_ou_divergencia_geometria"
    if conflict:
        return "DIVERGENCIA_CHECKBOX", "checkbox_divergente_geometria_igual"
    if geometry(original) == geometry(review_11):
        return "CONCORDANCIA_ORIGINAL", ""
    return "CONCORDANCIA_AVALIACAO", ""
