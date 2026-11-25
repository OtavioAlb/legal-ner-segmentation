"""Legacy-compatible geometry and checkbox decision rules for Phase 2."""
from __future__ import annotations

def geometry(r):
    return (r["label"], r["start"], r["end"]) if r else None


def decision(original, evaluated, explicit):
    if evaluated is None:
        return "nao_avaliada"
    if original is None:
        return "nova_regiao"
    if explicit:
        return {"certo": "correto", "incorreto": "incorreto",
                "limite impreciso": "limite_impreciso"}.get(
                    explicit.strip().casefold(), "julgamento_desconhecido")
    if original["label"] != evaluated["label"]:
        return "incorreto_automatico"
    if geometry(original) != geometry(evaluated):
        return "limite_impreciso_automatico"
    return "correto_automatico"


