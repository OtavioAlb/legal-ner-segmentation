"""Reproducible read-only audit. No source annotation is changed.

All reports are local outputs beneath data/interim; never commit them publicly.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from .ingestion import normalize_document_id


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def classify_mismatch(actual: str, expected: str) -> str:
    if actual == expected:
        return "exact"
    if actual.casefold() == expected.casefold():
        return "case_only"
    if actual.strip() == expected.strip():
        return "edge_whitespace"
    if unicodedata.normalize("NFKC", actual) == unicodedata.normalize("NFKC", expected):
        return "unicode_compatibility"
    if re.sub(r"\s+", " ", actual) == re.sub(r"\s+", " ", expected):
        return "whitespace_internal"
    return "other"


def _offset_reason(start: Any, end: Any, document: dict | None) -> str:
    if not isinstance(start, int) or isinstance(start, bool):
        return "missing_or_noninteger_start"
    if not isinstance(end, int) or isinstance(end, bool):
        return "missing_or_noninteger_end"
    if start < 0:
        return "negative_start"
    if start >= end:
        return "empty_or_reversed"
    if document and end > len(document["text"]):
        return "end_out_of_bounds"
    return "not_classified"


def _propose_label(label: str, known: set[str], aliases: dict[str, str]) -> dict[str, Any]:
    """Return diagnostic suggestions; none of these mappings is applied."""
    if label in aliases and aliases[label] in known:
        return {"category": "known_alias", "candidate": aliases[label]}
    if label in {"SEG_DECISAO_VOTO_VENCEDOR", "SEG_DECISAO_VOTO_VENCIDO"}:
        return {"category": "legacy_segmentation_class", "candidate": None}
    if label == "ENT_JUR_DECISAO":
        return {"category": "legacy_entity_class", "candidate": None}
    if "\n" in label or ":" in label:
        return {"category": "composite_or_free_text", "candidate": None}
    if not (label.startswith("ENT_") or label.startswith("SEG_") or label.startswith("SEGMENTO_")):
        return {"category": "not_structured_label", "candidate": None}
    candidates: list[str] = []
    if label.startswith("ENT_NORM_"):
        candidates.append(label.replace("ENT_NORM_", "ENT_NORMA_", 1))
    if label.startswith("SEGMENTO_"):
        candidates.append(label.replace("SEGMENTO_", "SEG_", 1))
    if label.startswith("SEG_"):
        candidates.extend([
            label.replace("JURISPRIDENCIA", "JURISPRUDENCIA"),
            label.replace("FUNDAMENTO_DECISA", "FUNDAMENTO_DECISAO"),
            label.replace("SEG_ARGUMENTAÇÃO", "SEG_ARGUMENTACAO"),
            label.replace("JURISPRUDÊNCIA", "JURISPRUDENCIA"),
        ])
    accepted = sorted({v for v in candidates if v in known})
    if len(accepted) == 1:
        return {"category": "possible_lexical_alias", "candidate": accepted[0]}
    return {"category": "unresolved_taxonomy", "candidate": None}


def _agreement_status(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "not_recorded"
    normalized = unicodedata.normalize("NFKD", str(value)).casefold()
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.strip()
    if normalized == "sim":
        return "agree"
    if normalized == "nao":
        return "disagree"
    return "other_not_interpreted"


def audit_phase1(
    dataset_dir: str | Path,
    output_dir: str | Path,
    labels_path: str | Path | None = None,
    aliases_path: str | Path | None = None,
) -> dict[str, Any]:
    dataset_dir, output_dir = Path(dataset_dir), Path(output_dir)
    docs = _read_jsonl(dataset_dir / "documents.jsonl")
    anns = _read_jsonl(dataset_dir / "annotations.jsonl")
    doc_by_id = {doc["document_id"]: doc for doc in docs}

    known: set[str] = set()
    aliases: dict[str, str] = {}
    if labels_path is not None:
        known = set(json.loads(Path(labels_path).read_text(encoding="utf-8"))["labels"])
    if aliases_path is not None:
        aliases = json.loads(Path(aliases_path).read_text(encoding="utf-8"))["aliases"]

    issues, flags, reviews = Counter(), Counter(), Counter()
    unknown_labels, mismatch_types, offsets = Counter(), Counter(), Counter()
    reviewer_opinions: dict[str, Counter] = {}
    orphan_candidate_counts = Counter()
    queue: list[dict[str, Any]] = []
    label_rows: dict[str, dict[str, Any]] = {}

    for ann in anns:
        codes = ann.get("issues") or []
        review_flags = ann.get("review_flags") or []
        issues.update(codes)
        flags.update(review_flags)
        reviews[ann.get("review_state") or "not_recorded"] += 1
        for reviewer, opinion in (ann.get("reviewer_opinions") or {}).items():
            reviewer_opinions.setdefault(reviewer, Counter())[
                _agreement_status((opinion or {}).get("agreement_raw"))
            ] += 1

        label = ann.get("label_original")
        if "UNKNOWN_LABEL" in codes:
            label = label or "<EMPTY>"
            unknown_labels[label] += 1
            if label not in label_rows:
                proposal = _propose_label(label, known, aliases)
                label_rows[label] = {
                    "label_original": label,
                    "category": proposal["category"],
                    "proposed_target": proposal["candidate"],
                    "decision": "pending_manual_review",
                }

        document_id = ann.get("document_id")
        doc = doc_by_id.get(document_id)
        start, end = ann.get("start"), ann.get("end")
        excerpt = ann.get("span_text_source")
        mismatch_kind = None
        if "SPAN_TEXT_MISMATCH" in codes and doc and isinstance(excerpt, str):
            if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(doc["text"]):
                mismatch_kind = classify_mismatch(doc["text"][start:end], excerpt)
                mismatch_types[mismatch_kind] += 1

        offset_reason = None
        if "INVALID_OFFSETS" in codes or "END_OUT_OF_BOUNDS" in codes:
            offset_reason = _offset_reason(start, end, doc)
            offsets[offset_reason] += 1

        matching_ids: list[str] = []
        if "UNKNOWN_DOCUMENT" in codes or "AMBIGUOUS_DOCUMENT_ID" in codes:
            if isinstance(excerpt, str) and excerpt and isinstance(start, int) and isinstance(end, int):
                if start >= 0 and end > start:
                    matching_ids = [
                        candidate["document_id"]
                        for candidate in docs
                        if end <= len(candidate["text"])
                        and candidate["text"][start:end] == excerpt
                    ]
            orphan_candidate_counts[len(matching_ids)] += 1

        if codes or review_flags or ann.get("review_state") in {
            "revised_incomplete", "revised_all_empty", "no_complete_review_schema"
        }:
            queue.append({
                "annotation_id": ann["annotation_id"],
                "source_row": ann["source_row"],
                "source_document_id": ann.get("source_document_id"),
                "document_id": document_id,
                "label_original": ann.get("label_original"),
                "task": ann.get("task"),
                "issues": codes,
                "review_flags": review_flags,
                "review_state": ann.get("review_state"),
                "mismatch_type": mismatch_kind,
                "offset_reason": offset_reason,
                "candidate_document_ids": matching_ids,
                "candidate_count": len(matching_ids)
                if "UNKNOWN_DOCUMENT" in codes or "AMBIGUOUS_DOCUMENT_ID" in codes else None,
                "adjudication_status": "pending_manual_review",
            })

    for label, entry in label_rows.items():
        entry["count"] = unknown_labels[label]

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "review_queue.jsonl", queue)
    _write_jsonl(
        output_dir / "unknown_labels_review.jsonl",
        sorted(label_rows.values(), key=lambda item: (-item["count"], item["label_original"])),
    )

    report = {
        "document_count": len(docs),
        "annotation_count": len(anns),
        "annotations_without_issues": sum(not ann.get("issues") for ann in anns),
        "annotations_with_issues": sum(bool(ann.get("issues")) for ann in anns),
        "review_state_counts": dict(sorted(reviews.items())),
        "issue_counts": dict(sorted(issues.items())),
        "review_flag_counts": dict(sorted(flags.items())),
        "reviewer_agreement_counts": {
            reviewer: dict(sorted(counts.items()))
            for reviewer, counts in sorted(reviewer_opinions.items())
        },
        "unknown_label_counts": dict(sorted(unknown_labels.items())),
        "unknown_label_category_counts": dict(sorted(
            Counter(
                entry["category"] for entry in label_rows.values()
                for _ in range(entry["count"])
            ).items()
        )),
        "mismatch_type_counts": dict(sorted(mismatch_types.items())),
        "invalid_offset_reason_counts": dict(sorted(offsets.items())),
        "unknown_document_candidate_counts": {
            str(count): total for count, total in sorted(orphan_candidate_counts.items())
        },
        "manual_review_queue_count": len(queue),
        "method": "diagnostic suggestions only; review fields are authoritative without fallback",
    }
    (output_dir / "audit_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Phase 1 without modifying annotations")
    parser.add_argument("--dataset", type=Path, default=Path("data/interim/phase_1"))
    parser.add_argument("--output", type=Path, default=Path("data/interim/phase_1/audit"))
    parser.add_argument("--labels", type=Path, default=Path("configs/labels.json"))
    parser.add_argument("--aliases", type=Path, default=Path("configs/label_aliases.json"))
    args = parser.parse_args()
    print(json.dumps(
        audit_phase1(args.dataset, args.output, args.labels, args.aliases),
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
