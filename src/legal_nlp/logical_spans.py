"""Lossless logical-span grouping for evaluator-final Phase 1 annotations.

Grouping merges exact same (document, task, start, end, label) copies into a
logical span with all source annotation provenance. Near-boundary variants
and same-geometry different-label spans remain independent logical spans.
This is not overlap adjudication and does not produce BIO tags.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _logical_span_id(key: tuple[str, str, int, int, str]) -> str:
    encoded = json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "ls_" + hashlib.sha256(encoded).hexdigest()[:24]


def build_logical_spans(
    sanitized_path: str | Path,
    annotations_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Consolidate only exact labeled-span duplicates, preserving provenance."""
    sanitized_path = Path(sanitized_path)
    annotations_path = Path(annotations_path)
    output_dir = Path(output_dir)

    originals: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(annotations_path):
        annotation_id = row["annotation_id"]
        if annotation_id in originals:
            raise ValueError(f"Duplicate source annotation ID: {annotation_id}")
        originals[annotation_id] = row

    groups: dict[tuple[str, str, int, int, str], list[dict[str, Any]]] = defaultdict(list)
    seen_ids: set[str] = set()
    input_count_by_task: Counter[str] = Counter()
    for item in _read_jsonl(sanitized_path):
        annotation_id = item["annotation_id"]
        if annotation_id in seen_ids:
            raise ValueError(f"Duplicate sanitized annotation ID: {annotation_id}")
        seen_ids.add(annotation_id)
        if annotation_id not in originals:
            raise ValueError(f"Missing provenance for annotation: {annotation_id}")
        source = originals[annotation_id]
        status = source.get("target_selection_status")
        expected_truth = (
            "evaluator_reviewed_fields" if status == "reviewed_final"
            else "original_confirmed_by_reviewers"
            if status == "original_confirmed_by_reviewers" else None
        )
        if expected_truth is None or item.get("source_of_truth") != expected_truth:
            raise ValueError(f"Invalid evaluator precedence: {annotation_id}")
        if (item.get("source_row") != source.get("source_row")
                or item.get("annotator_id") != source.get("annotator_id")):
            raise ValueError(f"Broken annotation provenance: {annotation_id}")
        document_id, task = item["document_id"], item["task"]
        start, end, label = item["start"], item["end"], item["label"]
        if (not isinstance(document_id, str) or not document_id
                or task not in {"NER", "SEG"}
                or not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)
                or start < 0 or end <= start
                or not isinstance(label, str)
                or not label.startswith("ENT_" if task == "NER" else "SEG_")):
            raise ValueError(f"Invalid sanitized span: {annotation_id}")
        groups[(document_id, task, start, end, label)].append(item)
        input_count_by_task[task] += 1

    logical_spans: list[dict[str, Any]] = []
    output_count_by_task: Counter[str] = Counter()
    multi_source_groups = 0
    seen_logical_ids: set[str] = set()
    for key, items in sorted(groups.items()):
        document_id, task, start, end, label = key
        logical_id = _logical_span_id(key)
        if logical_id in seen_logical_ids:
            raise ValueError("Logical span hash collision")
        seen_logical_ids.add(logical_id)
        provenance: list[dict[str, Any]] = []
        annotators: set[str] = set()
        correction_count = 0
        for item in sorted(items, key=lambda row: (row["source_row"], row["annotation_id"])):
            source = originals[item["annotation_id"]]
            status = source["target_selection_status"]
            original_label = (source.get("fields_original") or {}).get("label")
            corrected_label = (source.get("fields_revised") or {}).get("label")
            changed = (
                status == "reviewed_final"
                and corrected_label is not None
                and corrected_label != original_label
            )
            correction_count += int(changed)
            if isinstance(item.get("annotator_id"), str) and item["annotator_id"]:
                annotators.add(item["annotator_id"])
            provenance.append({
                "annotation_id": item["annotation_id"],
                "source_row": item["source_row"],
                "annotator_id": item.get("annotator_id"),
                "selection_status": status,
                "source_of_truth": item["source_of_truth"],
                "label_original": original_label,
                "label_evaluator_revised": corrected_label,
                "explicit_evaluator_label_change": changed,
                "review_agree_count": source.get("review_agree_count"),
                "review_disagree_count": source.get("review_disagree_count"),
                "text_equivalence": item.get("text_equivalence"),
                "sanitization_rule_ids": item.get("sanitization_rule_ids", []),
            })
        if len(items) > 1:
            multi_source_groups += 1
        logical_spans.append({
            "logical_span_id": logical_id,
            "document_id": document_id,
            "task": task,
            "start": start,
            "end": end,
            "label": label,
            "source_annotation_count": len(items),
            "annotator_ids": sorted(annotators),
            "explicit_evaluator_label_change_count": correction_count,
            "provenance": provenance,
        })
        output_count_by_task[task] += 1

    original_count = sum(input_count_by_task.values())
    grouped_count = len(logical_spans)
    if original_count != sum(x["source_annotation_count"] for x in logical_spans):
        raise AssertionError("Consolidation must account for all input annotations")

    summary = {
        "logical_span_schema_version": "1.0.0",
        "input_annotation_count": original_count,
        "logical_span_count": grouped_count,
        "exact_duplicate_extra_annotations": original_count - grouped_count,
        "groups_with_multiple_source_annotations": multi_source_groups,
        "document_count": len({x["document_id"] for x in logical_spans}),
        "input_annotation_count_by_task": dict(sorted(input_count_by_task.items())),
        "logical_span_count_by_task": dict(sorted(output_count_by_task.items())),
        "policy": (
            "exact group key=(document_id,task,start,end,label); evaluator-final "
            "annotation already selected upstream; retain provenance and independent "
            "different-label/near-boundary spans; no deletion, label arbitration, "
            "overlap pruning or BIO conversion"
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "logical_spans.jsonl", logical_spans)
    (output_dir / "logical_spans_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build lossless logical spans from sanitized evaluator-final annotations"
    )
    parser.add_argument(
        "--sanitized", type=Path,
        default=Path("data/interim/phase_1/sanitized/sanitized_annotations.jsonl"),
    )
    parser.add_argument(
        "--annotations", type=Path,
        default=Path("data/interim/phase_1/annotations.jsonl"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/interim/phase_1/logical_spans"),
    )
    args = parser.parse_args()
    print(json.dumps(
        build_logical_spans(args.sanitized, args.annotations, args.output),
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
