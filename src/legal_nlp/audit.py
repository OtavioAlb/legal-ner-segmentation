"""Read-only, local audit of imported Phase 1 records.

Report files contain identifiers, labels and diagnostics, but never source text,
annotated excerpts, reviewer comments or personal names.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def classify_mismatch(actual: str, expected: str) -> str:
    if actual == expected:
        return "exact"
    if actual.casefold() == expected.casefold():
        return "case_only"
    if actual.strip() == expected.strip():
        return "edge_whitespace"
    return "other"


def audit_phase1(dataset_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    dataset_dir, output_dir = Path(dataset_dir), Path(output_dir)
    documents = _read_jsonl(dataset_dir / "documents.jsonl")
    annotations = _read_jsonl(dataset_dir / "annotations.jsonl")
    docs_by_id = {doc["document_id"]: doc for doc in documents}
    labels = Counter()
    issues = Counter()
    flags = Counter()
    mismatch_types = Counter()
    unmatched_match_count = Counter()
    queue: list[dict[str, Any]] = []

    for ann in annotations:
        codes = ann.get("issues") or []
        review_flags = ann.get("review_flags") or []
        issues.update(codes)
        flags.update(review_flags)
        if "UNKNOWN_LABEL" in codes:
            labels[ann.get("label_original") or "<EMPTY>"] += 1

        original_id = ann.get("document_id")
        doc = docs_by_id.get(original_id)
        start, end = ann.get("start"), ann.get("end")
        excerpt = ann.get("span_text_source")
        mismatch_kind = None
        if "SPAN_TEXT_MISMATCH" in codes and doc:
            text = doc["text"]
            if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text) and excerpt is not None:
                mismatch_kind = classify_mismatch(text[start:end], excerpt)
                mismatch_types[mismatch_kind] += 1

        matching_ids: list[str] = []
        if "UNKNOWN_DOCUMENT" in codes and isinstance(excerpt, str) and excerpt:
            if isinstance(start, int) and isinstance(end, int) and start >= 0 and end > start:
                for candidate in documents:
                    text = candidate["text"]
                    if end <= len(text) and text[start:end] == excerpt:
                        matching_ids.append(candidate["document_id"])
            unmatched_match_count[len(matching_ids)] += 1

        if codes or review_flags:
            queue.append({
                "annotation_id": ann["annotation_id"],
                "source_row": ann["source_row"],
                "source_document_id": ann.get("source_document_id"),
                "document_id": original_id,
                "label_original": ann.get("label_original"),
                "task": ann.get("task"),
                "issues": codes,
                "review_flags": review_flags,
                "mismatch_type": mismatch_kind,
                "candidate_document_ids": matching_ids,
                "candidate_count": len(matching_ids) if "UNKNOWN_DOCUMENT" in codes else None,
                "adjudication_status": "pending_manual_review",
            })

    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "document_count": len(documents),
        "annotation_count": len(annotations),
        "annotations_without_issues": sum(not a.get("issues") for a in annotations),
        "annotations_with_issues": sum(bool(a.get("issues")) for a in annotations),
        "issue_counts": dict(sorted(issues.items())),
        "review_flag_counts": dict(sorted(flags.items())),
        "unknown_label_counts": dict(sorted(labels.items())),
        "mismatch_type_counts": dict(sorted(mismatch_types.items())),
        "unknown_document_candidate_counts": {
            str(count): total for count, total in sorted(unmatched_match_count.items())
        },
        "manual_review_queue_count": len(queue),
        "method": "exact source-offset/excerpt candidate matching; no automatic correction",
    }
    (output_dir / "audit_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(output_dir / "review_queue.jsonl", queue)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Phase 1 without modifying annotations")
    parser.add_argument("--dataset", type=Path, default=Path("data/interim/phase_1"))
    parser.add_argument("--output", type=Path, default=Path("data/interim/phase_1/audit"))
    args = parser.parse_args()
    print(json.dumps(audit_phase1(args.dataset, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
