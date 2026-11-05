"""Read-only span diagnostics for sanitized Phase 1 supervision.

No deduplication, overlap removal, label voting, or text modification.
Only within-task comparisons are made: NER/SEG overlaps are expected and
are not considered candidate conflicts in this report.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for row in records:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def diagnose_spans(
    input_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Analyze duplicates and overlaps; leave the sanitized view unchanged."""
    input_path, output_dir = Path(input_path), Path(output_dir)
    with input_path.open(encoding="utf-8") as source:
        records = [json.loads(line) for line in source if line.strip()]

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    annotation_ids: set[str] = set()
    for row in records:
        annotation_id = row["annotation_id"]
        document_id, task = row["document_id"], row["task"]
        start, end, label = row["start"], row["end"], row["label"]
        if annotation_id in annotation_ids:
            raise ValueError(f"Duplicate annotation_id: {annotation_id}")
        annotation_ids.add(annotation_id)
        if (not isinstance(document_id, str) or not document_id
                or task not in {"NER", "SEG"}
                or not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)
                or start < 0 or end <= start or not isinstance(label, str)
                or not label.startswith("ENT_" if task == "NER" else "SEG_")):
            raise ValueError(f"Invalid sanitized span: {annotation_id}")
        groups[(document_id, task)].append(row)

    exact_duplicates: list[dict[str, Any]] = []
    label_conflicts: list[dict[str, Any]] = []
    overlapping: list[dict[str, Any]] = []
    metrics: dict[str, Counter] = {"NER": Counter(), "SEG": Counter()}
    involved_ann_ids: dict[str, set[str]] = {"NER": set(), "SEG": set()}

    for (document_id, task), items in sorted(groups.items()):
        metric = metrics[task]
        metric["annotation_count"] += len(items)

        label_groups: dict[tuple[int, int, str], list[dict[str, Any]]] = defaultdict(list)
        geometry_groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            label_groups[(item["start"], item["end"], item["label"])].append(item)
            geometry_groups[(item["start"], item["end"])].append(item)
        metric["unique_labeled_span_count"] += len(label_groups)
        metric["unique_geometry_count"] += len(geometry_groups)

        for (start, end, label), copies in sorted(label_groups.items()):
            if len(copies) <= 1:
                continue
            ids = sorted(x["annotation_id"] for x in copies)
            annotators = sorted({
                x["annotator_id"] for x in copies
                if isinstance(x.get("annotator_id"), str) and x["annotator_id"]
            })
            exact_duplicates.append({
                "document_id": document_id,
                "task": task,
                "start": start, "end": end, "label": label,
                "annotation_ids": ids,
                "source_rows": sorted(x["source_row"] for x in copies),
                "annotator_ids": annotators,
                "annotator_identity_complete": len(annotators) == len(copies),
                "record_count": len(copies),
                "extra_annotations": len(copies) - 1,
            })
            metric["exact_duplicate_groups"] += 1
            metric["exact_duplicate_extra_annotations"] += len(copies) - 1

        for (start, end), copies in sorted(geometry_groups.items()):
            label_set = sorted({x["label"] for x in copies})
            if len(label_set) <= 1:
                continue
            label_conflicts.append({
                "document_id": document_id,
                "task": task,
                "start": start, "end": end,
                "labels": label_set,
                "annotation_ids_by_label": {
                    label: sorted(
                        x["annotation_id"] for x in copies if x["label"] == label
                    ) for label in label_set
                },
                "source_rows_by_label": {
                    label: sorted(
                        x["source_row"] for x in copies if x["label"] == label
                    ) for label in label_set
                },
            })
            metric["same_geometry_distinct_label_groups"] += 1

        # Compare unique labeled spans: repeated annotator records should not
        # multiply an overlap measurement. Exact-geometry label disagreements
        # are counted above rather than called boundary overlap.
        spans = sorted(label_groups)
        for i, first in enumerate(spans):
            a_start, a_end, a_label = first
            for second in spans[i + 1:]:
                b_start, b_end, b_label = second
                if b_start >= a_end:
                    break
                if (a_start, a_end) == (b_start, b_end):
                    continue
                if a_start >= b_end or b_start >= a_end:
                    continue
                nested = (
                    (a_start <= b_start and b_end <= a_end)
                    or (b_start <= a_start and a_end <= b_end)
                )
                kind = "nested" if nested else "crossing"
                metric["overlap_pairs"] += 1
                metric[f"overlap_{kind}_pairs"] += 1
                metric[
                    "overlap_same_label_pairs" if a_label == b_label
                    else "overlap_different_label_pairs"
                ] += 1
                first_ids = sorted(row["annotation_id"] for row in label_groups[first])
                second_ids = sorted(row["annotation_id"] for row in label_groups[second])
                involved_ann_ids[task].update(first_ids + second_ids)
                overlapping.append({
                    "document_id": document_id, "task": task, "kind": kind,
                    "first": {
                        "start": a_start, "end": a_end, "label": a_label,
                        "annotation_ids": first_ids,
                    },
                    "second": {
                        "start": b_start, "end": b_end, "label": b_label,
                        "annotation_ids": second_ids,
                    },
                })

    for task in ("NER", "SEG"):
        metrics[task]["annotations_involved_in_overlap"] = len(involved_ann_ids[task])

    summary = {
        "diagnostics_schema_version": "1.0.0",
        "input_annotation_count": len(records),
        "documents_with_annotations": len({k[0] for k in groups}),
        "overall_counts": {
            "exact_duplicate_groups": len(exact_duplicates),
            "exact_duplicate_extra_annotations": sum(
                group["extra_annotations"] for group in exact_duplicates
            ),
            "same_geometry_distinct_label_groups": len(label_conflicts),
            "overlap_pairs": len(overlapping),
        },
        "per_task_counts": {
            task: dict(sorted(metrics[task].items())) for task in ("NER", "SEG")
        },
        "policy": (
            "diagnostic only; exact duplicates and overlaps are not removed; "
            "no cross-task overlap comparison; no training dataset mutation"
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "exact_duplicate_groups.jsonl", exact_duplicates)
    _write_jsonl(output_dir / "same_span_label_conflicts.jsonl", label_conflicts)
    _write_jsonl(output_dir / "within_task_overlap_pairs.jsonl", overlapping)
    (output_dir / "span_diagnostics_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only within-task duplicate and overlap diagnostics"
    )
    parser.add_argument(
        "--input", type=Path,
        default=Path("data/interim/phase_1/sanitized/sanitized_annotations.jsonl"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/interim/phase_1/span_diagnostics"),
    )
    args = parser.parse_args()
    print(json.dumps(diagnose_spans(args.input, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
