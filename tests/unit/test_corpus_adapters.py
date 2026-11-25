"""Synthetic-only checks for canonical phase adapters."""
import pytest

from legal_nlp.datasets.corpus_adapters import (
    corpus_summary, phase1_records, phase2_records, resolve_text,
)


def test_phase1_validated_spans_retain_text_and_lineage():
    documents = [{
        "document_id": "first", "idacordao": "10", "text": "Decisão sobre IA",
        "spans": {
            "NER": [{
                "logical_span_id": "ls1", "label": "ENT_TERMO_IA", "start": 14,
                "end": 16, "provenance": [{"annotation_id": "a"}],
            }],
            "SEG": [],
        }
    }]
    out = phase1_records(documents)
    assert out[0]["text"] == "IA"
    assert out[0]["status"] == "consolidated"
    assert out[0]["provenance"] == [{"annotation_id": "a"}]


def test_phase1_rejects_missing_lineage():
    with pytest.raises(ValueError, match="Missing Phase 1 lineage"):
        phase1_records([{
            "document_id": "a", "text": "abc",
            "spans": {"NER": [{"logical_span_id": "a", "label": "ENT_A",
                               "start": 0, "end": 2, "provenance": []}], "SEG": []},
        }])


def test_phase2_pending_and_consolidated_new_are_not_double_counted():
    original = {
        "idacordao": "42", "region_id_original": "base",
        "label_original": "ENT_COMARCA", "start_original": 0, "end_original": 3,
        "texto_original": "ABC", "status": "DIVERGENCIA_CHECKBOX",
        "projeto_11_region_id": "base", "projeto_17_region_id": "base",
        "projeto_11_avaliador_id": "7", "projeto_17_avaliador_id": "5",
    }
    new = {
        "idacordao": "42", "status": "CONSOLIDADA_NOVA",
        "region_id_nova": "r11", "label": "ENT_CLASSE",
    }
    consolidated = {
        "idacordao": "42", "status": "CONSOLIDADA_NOVA",
        "canonical_region_id": "new_hash", "label_proposta_concordante": "SEG_EMENTA",
        "start_proposta_concordante": 3, "end_proposta_concordante": 6,
        "projeto_11_region_id": "r11", "projeto_17_region_id": "r17",
        "projeto_11_avaliador_id": "7", "projeto_17_avaliador_id": "5",
    }
    rows = phase2_records({
        "Revisao_originais": [original],
        "Revisao_novas": [new, {**new, "region_id_nova": "r17"}],
        "Consolidados": [consolidated],
    })
    assert len(rows) == 2
    assert {r["status"] for r in rows} == {"consolidated", "pending_review"}
    assert resolve_text(rows, {"42": "ABCDEF"})[1]["text"] == "DEF"
    assert corpus_summary(rows)["training_ready"] is False


def test_phase2_source_mismatch_is_detected_not_repaired():
    original = {
        "idacordao": "42", "region_id_original": "base",
        "label_original": "ENT_COMARCA", "start_original": 0, "end_original": 3,
        "texto_original": "WRONG", "status": "PENDENTE_GEOMETRIA",
        "projeto_11_region_id": "", "projeto_17_region_id": "base",
        "projeto_11_avaliador_id": "7", "projeto_17_avaliador_id": "5",
    }
    records = phase2_records({
        "Revisao_originais": [original], "Revisao_novas": [],
        "Consolidados": [],
    })
    with pytest.raises(ValueError, match="Span-text mismatch"):
        resolve_text(records, {"42": "ABC"})
