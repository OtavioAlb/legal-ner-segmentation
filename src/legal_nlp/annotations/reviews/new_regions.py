"""Deterministic status classification for proposed regions in Phase 2.

A new region remains a manual proposal unless the existing consolidation
algorithm independently establishes an eligible exact cross-review pair.
"""
from __future__ import annotations


def classify_new_proposal(*, consolidated: bool, complete: bool,
                          same_in_other: bool, count_here: int,
                          count_other: int, duplicates_original: bool,
                          same_reviewer: bool) -> tuple[str, str]:
    if consolidated:
        return "CONSOLIDADA_NOVA", ""
    if not complete:
        return "PENDENTE_NOVA", "nova_aguardando_substituicao"
    if same_in_other and (count_here != 1 or count_other != 1):
        return "PENDENTE_NOVA", "nova_ambigua_ids_duplicados"
    if same_in_other and duplicates_original:
        return "PENDENTE_NOVA", "nova_duplicada_do_original"
    if same_in_other and same_reviewer:
        return "PENDENTE_NOVA", "nova_sem_avaliadores_distintos"
    if same_in_other:
        return "PENDENTE_NOVA", "nova_coincidente_pendente"
    return "PENDENTE_NOVA", "nova_unilateral_pendente"
