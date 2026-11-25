"""Read-only adapters from Phase 1 document spans and Phase 2 audit rows.

Do not infer final gold from pending reviews. This module creates normalized
records for comparison and lineage inspection, not a train-ready corpus.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def _kind(label: str) -> str:
    if label.startswith("ENT_"):
        return "NER"
    if label.startswith("SEG_"):
        return "SEG"
    raise ValueError(f"Unknown task prefix for label: {label}")


def phase1_records(document_spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapt Phase 1 *validated* document_spans.jsonl without modifying sources."""
    result = []
    ids = set()
    for doc in document_spans:
        document_id, text = doc["document_id"], doc["text"]
        if document_id in ids:
            raise ValueError(f"Repeated Phase 1 document: {document_id}")
        ids.add(document_id)
        for task in ("NER", "SEG"):
            for item in doc["spans"][task]:
                start, end = item["start"], item["end"]
                label = item["label"]
                if _kind(label) != task or not (0 <= start < end <= len(text)):
                    raise ValueError(f"Invalid Phase 1 span in {document_id}")
                if not item.get("provenance"):
                    raise ValueError(f"Missing Phase 1 lineage in {document_id}")
                result.append({
                    "phase": "phase_1",
                    "document_id": str(document_id),
                    "idacordao": doc.get("idacordao"),
                    "region_id": item["logical_span_id"],
                    "task": task,
                    "label": label,
                    "start": start,
                    "end": end,
                    "text": text[start:end],
                    "status": "consolidated",
                    "source_status": "phase1_evaluator_final_logical_span",
                    "provenance": item["provenance"],
                })
    return result


def phase2_records(sheets: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Normalize both accepted and pending audit rows; no automatic gold promotion."""
    results = []
    for row in sheets["Revisao_originais"]:
        accepted = row["status"] in ("CONCORDANCIA_ORIGINAL", "CONCORDANCIA_AVALIACAO")
        if accepted:
            label = row["projeto_11_label"]
            start, end = row["projeto_11_start"], row["projeto_11_end"]
            text = ""  # source text must be resolved against the immutable document
        else:
            label = row["label_original"]
            start, end = row["start_original"], row["end_original"]
            text = row["texto_original"]
        results.append({
            "phase": "phase_2", "document_id": str(row["idacordao"]),
            "idacordao": str(row["idacordao"]),
            "region_id": row["region_id_original"],
            "task": _kind(label), "label": label,
            "start": start, "end": end, "text": text,
            "status": "consolidated" if accepted else "pending_review",
            "source_status": row["status"],
            "provenance": {
                "original_region_id": row["region_id_original"],
                "project_11_region_id": row["projeto_11_region_id"],
                "project_17_region_id": row["projeto_17_region_id"],
                "project_11_reviewer_id": row["projeto_11_avaliador_id"],
                "project_17_reviewer_id": row["projeto_17_avaliador_id"],
            },
        })
    for row in sheets["Revisao_novas"]:
        # A confirmed pair appears twice in this proposal worksheet; only the
        # consolidated canonical row below is accepted.
        if row["status"] != "PENDENTE_NOVA":
            continue
        results.append({
            "phase": "phase_2", "document_id": str(row["idacordao"]),
            "idacordao": str(row["idacordao"]),
            "region_id": row["region_id_nova"],
            "task": _kind(row["label"]), "label": row["label"],
            "start": row["start"], "end": row["end"], "text": row["texto"],
            "status": "pending_review", "source_status": row["status"],
            "provenance": {
                "project_id": row["projeto_avaliacao"],
                "reviewer_id": row["avaliador_id"],
                "reason": row["motivo"],
            },
        })
    for row in sheets["Consolidados"]:
        if row["status"] != "CONSOLIDADA_NOVA":
            continue
        results.append({
            "phase": "phase_2", "document_id": str(row["idacordao"]),
            "idacordao": str(row["idacordao"]),
            "region_id": row["canonical_region_id"],
            "task": _kind(row["label_proposta_concordante"]),
            "label": row["label_proposta_concordante"],
            "start": row["start_proposta_concordante"],
            "end": row["end_proposta_concordante"], "text": "",
            "status": "consolidated", "source_status": row["status"],
            "provenance": {
                "project_11_region_id": row["projeto_11_region_id"],
                "project_17_region_id": row["projeto_17_region_id"],
                "project_11_reviewer_id": row["projeto_11_avaliador_id"],
                "project_17_reviewer_id": row["projeto_17_avaliador_id"],
            },
        })
    return results


def resolve_text(records: list[dict[str, Any]],
                 documents: dict[str, str]) -> list[dict[str, Any]]:
    """Validate offsets against exact immutable text, never silently repair them."""
    resolved = []
    for item in records:
        if item["phase"] != "phase_2":
            resolved.append(item.copy())
            continue
        doc_id = item["document_id"]
        if doc_id not in documents:
            raise ValueError(f"Missing Phase 2 source document {doc_id}")
        full_text = documents[doc_id]
        start, end = item["start"], item["end"]
        if (type(start) is not int or type(end) is not int
                or not (0 <= start < end <= len(full_text))):
            raise ValueError(f"Invalid offsets in {doc_id}/{item['region_id']}")
        excerpt = full_text[start:end]
        if item["text"] and item["text"] != excerpt:
            raise ValueError(
                f"Span-text mismatch in {doc_id}/{item['region_id']} "
                f"(status={item['status']}, source_status={item['source_status']}, "
                f"start={start}, end={end}, source_length={len(item['text'])}, "
                f"document_slice_length={len(excerpt)}). "
                "Run python -m legal_nlp.datasets.span_text_diagnostics "
                "to inspect all mismatches without changing annotations."
            )
        resolved.append({**item, "text": excerpt})
    return resolved


def corpus_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter((r["phase"], r["task"], r["status"]) for r in rows)
    return {
        "total_records": len(rows),
        "by_phase_task_status": [
            {"phase": phase, "task": task, "status": status, "count": count}
            for (phase, task, status), count in sorted(counts.items())
        ],
        "training_ready": False,
        "reason": "Comparison/diagnostic view only; requires validated corpus version and frozen splits",
    }
