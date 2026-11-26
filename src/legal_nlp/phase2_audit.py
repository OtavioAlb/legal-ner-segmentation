"""Read-only technical and comparison audit of Label Studio Phase 2 exports.

Private source documents remain local. Diagnostics exclude full texts and
selected text spans. Comparisons are descriptive, never gold adjudication.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .audit import classify_mismatch


def _load_array(path: Path) -> list[dict[str, Any]]:
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, list) or any(not isinstance(x, dict) for x in obj):
        raise ValueError(f"Expected JSON array of objects: {path}")
    return obj


def _decision_id(row: dict[str, Any]) -> str:
    data = row.get("data")
    value = data.get("idacordao") if isinstance(data, dict) else None
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError("Missing or invalid data.idacordao")
    return str(value).strip()


def _user_id(annotation: dict[str, Any] | None) -> int | None:
    value = annotation.get("completed_by") if annotation else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _parse_spans(
    row: dict[str, Any], known: set[str], stage: str,
    issues: list[dict[str, Any]], counts: Counter[str], label_counts: Counter[str],
) -> tuple[set[tuple[str, str, int, int]], dict[str, set[tuple[str, str, int, int]]]]:
    doc_id = _decision_id(row)
    project = row.get("project") if stage == "evaluation" else "original"
    task_id = row.get("id")
    text = row.get("data", {}).get("acordao")
    if not isinstance(text, str):
        text = None
        _issue(issues, "MISSING_DOCUMENT_TEXT", "error", doc_id, project, stage, task_id)
    annotations = row.get("annotations")
    if not isinstance(annotations, list) or len(annotations) != 1 or not isinstance(annotations[0], dict):
        _issue(issues, "INVALID_ANNOTATION_COUNT", "error", doc_id, project, stage, task_id)
        return set(), {"NER": set(), "SEG": set()}
    annotation = annotations[0]
    if annotation.get("was_cancelled"):
        _issue(issues, "CANCELLED_ANNOTATION", "error", doc_id, project, stage, task_id)
    results = annotation.get("result")
    if not isinstance(results, list):
        _issue(issues, "RESULT_NOT_ARRAY", "error", doc_id, project, stage, task_id)
        return set(), {"NER": set(), "SEG": set()}
    signatures: set[tuple[str, str, int, int]] = set()
    by_task: dict[str, set[tuple[str, str, int, int]]] = {"NER": set(), "SEG": set()}
    boundaries: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    raw_labels = 0
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            _issue(issues, "INVALID_RESULT_ITEM", "error", doc_id, project, stage, task_id, index)
            continue
        kind = item.get("type")
        if kind != "labels":
            counts[f"result_type:{kind}"] += 1
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            _issue(issues, "INVALID_LABEL_VALUE", "error", doc_id, project, stage, task_id, index)
            continue
        labels = value.get("labels")
        if not isinstance(labels, list) or not labels or any(not isinstance(x, str) or not x for x in labels):
            _issue(issues, "MISSING_LABEL", "error", doc_id, project, stage, task_id, index)
            continue
        raw_labels += len(labels)
        start, end = value.get("start"), value.get("end")
        valid_offset = (isinstance(start, int) and not isinstance(start, bool)
                        and isinstance(end, int) and not isinstance(end, bool)
                        and text is not None and 0 <= start < end <= len(text))
        if not valid_offset:
            _issue(issues, "INVALID_OFFSETS", "error", doc_id, project, stage, task_id, index)
        declared = value.get("text")
        if valid_offset and not isinstance(declared, str):
            _issue(issues, "MISSING_SPAN_TEXT", "warning", doc_id, project, stage, task_id, index)
        mismatch = (
            classify_mismatch(text[start:end], declared)
            if valid_offset and isinstance(declared, str) else None
        )
        if mismatch and mismatch != "exact":
            _issue(issues, "SPAN_TEXT_MISMATCH", "error", doc_id, project, stage, task_id,
                   index, mismatch_type=mismatch)
            counts[f"text_mismatch:{mismatch}"] += 1
        for label in labels:
            label_counts[label] += 1
            task = "NER" if label.startswith("ENT_") else "SEG" if label.startswith("SEG_") else "UNKNOWN"
            counts[f"label_task:{task}"] += 1
            if label not in known:
                _issue(issues, "UNKNOWN_LABEL", "error", doc_id, project, stage, task_id,
                       index, label=label)
            if valid_offset and label in known and (mismatch in (None, "exact")):
                signature = (task, label, start, end)
                if signature in signatures:
                    _issue(issues, "EXACT_DUPLICATE_SPAN", "warning", doc_id, project,
                           stage, task_id, index, label=label)
                signatures.add(signature)
                by_task[task].add(signature)
                boundaries[(task, start, end)].add(label)
    if raw_labels == 0:
        _issue(issues, "EMPTY_LABEL_RESULTS", "warning", doc_id, project, stage, task_id)
    for (task, start, end), labels in boundaries.items():
        if len(labels) > 1:
            _issue(issues, "SAME_BOUNDARY_DIFFERENT_LABEL", "warning", doc_id,
                   project, stage, task_id, task=task, start=start, end=end)
    counts[f"{stage}_labeled_items"] += raw_labels
    counts[f"{stage}_valid_unique_spans"] += len(signatures)
    return signatures, by_task


def _issue(
    issues: list[dict[str, Any]], code: str, severity: str, doc_id: str,
    project: Any, stage: str, task_id: Any, result_index: int | None = None,
    **extra: Any,
) -> None:
    issues.append({"code": code, "severity": severity, "idacordao": doc_id,
                   "project": project, "stage": stage, "task_id": task_id,
                   "result_index": result_index, **extra})


def _compare(
    doc_id: str, scope: str, left: dict[str, set[tuple[str, str, int, int]]],
    right: dict[str, set[tuple[str, str, int, int]]],
    project: Any,
) -> list[dict[str, Any]]:
    output = []
    for task in ("NER", "SEG"):
        a, b = left[task], right[task]
        output.append({"idacordao": doc_id, "comparison": scope, "project": project,
                       "task": task, "left_spans": len(a), "right_spans": len(b),
                       "unchanged": len(a & b), "only_left": len(a - b),
                       "only_right": len(b - a)})
    return output


def audit_phase2(
    originals_file: str | Path, resolved_file: str | Path,
    labels_file: str | Path, output_dir: str | Path,
) -> dict[str, Any]:
    originals_file, resolved_file, labels_file = map(Path,
                                                    (originals_file, resolved_file, labels_file))
    output_dir = Path(output_dir)
    if len({originals_file.resolve(), resolved_file.resolve(), labels_file.resolve()}) != 3:
        raise ValueError("Input paths must be distinct")
    originals, evaluations = _load_array(originals_file), _load_array(resolved_file)
    labels_data = json.loads(labels_file.read_text(encoding="utf-8-sig"))
    known = labels_data.get("labels")
    if not isinstance(known, list) or not all(isinstance(label, str) for label in known):
        raise ValueError("Invalid canonical labels schema")
    known_set = set(known)
    issues: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    original_map = {}
    original_spans = {}
    for row in originals:
        doc_id = _decision_id(row)
        if doc_id in original_map:
            raise ValueError(f"Duplicate original decision ID: {doc_id}")
        original_map[doc_id] = row
        _, original_spans[doc_id] = _parse_spans(row, known_set, "original", issues,
                                                 counts, label_counts)
    by_document: dict[str, list[tuple[Any, dict[str, set]]]] = defaultdict(list)
    comparisons = []
    project_counts: Counter[str] = Counter()
    seen_project = set()
    for row in evaluations:
        doc_id = _decision_id(row)
        project = row.get("project")
        project_counts[str(project)] += 1
        pair = (doc_id, str(project))
        if pair in seen_project:
            _issue(issues, "DUPLICATE_DOCUMENT_PROJECT", "error", doc_id,
                   project, "evaluation", row.get("id"))
        seen_project.add(pair)
        if str(project) not in {"11", "17"}:
            _issue(issues, "UNKNOWN_PROJECT", "error", doc_id, project,
                   "evaluation", row.get("id"))
        _, evaluated_spans = _parse_spans(row, known_set, "evaluation", issues,
                                          counts, label_counts)
        original = original_map.get(doc_id)
        if original is None:
            _issue(issues, "MISSING_ORIGINAL_DOCUMENT", "error", doc_id, project,
                   "evaluation", row.get("id"))
            continue
        if row.get("data", {}).get("acordao") != original.get("data", {}).get("acordao"):
            _issue(issues, "DOCUMENT_TEXT_MISMATCH", "error", doc_id, project,
                   "evaluation", row.get("id"))
            continue
        original_annotations = original.get("annotations")
        evaluation_annotations = row.get("annotations")
        orig_annotation = (original_annotations[0] if isinstance(original_annotations, list)
                           and len(original_annotations) == 1 and isinstance(original_annotations[0], dict)
                           else None)
        eval_annotation = (evaluation_annotations[0] if isinstance(evaluation_annotations, list)
                           and len(evaluation_annotations) == 1 and isinstance(evaluation_annotations[0], dict)
                           else None)
        if row.get("annotated_by") != _user_id(orig_annotation):
            _issue(issues, "ANNOTATOR_ID_MISMATCH", "error", doc_id, project,
                   "evaluation", row.get("id"))
        if row.get("evaluated_by") != _user_id(eval_annotation):
            _issue(issues, "EVALUATOR_ID_MISMATCH", "error", doc_id, project,
                   "evaluation", row.get("id"))
        if row.get("identity_validation_status") != "assignment_consistent":
            _issue(issues, "IDENTITY_ASSIGNMENT_NOT_CONSISTENT", "warning", doc_id,
                   project, "evaluation", row.get("id"))
        comparisons.extend(_compare(doc_id, "original_vs_evaluation",
                                    original_spans[doc_id], evaluated_spans, project))
        by_document[doc_id].append((project, evaluated_spans))
    for doc_id, reviews in by_document.items():
        if len(reviews) == 2 and reviews[0][0] != reviews[1][0]:
            comparisons.extend(_compare(doc_id, "evaluation_vs_evaluation",
                                        reviews[0][1], reviews[1][1], "11_vs_17"))
    coverage = Counter(len(v) for v in by_document.values())
    for doc_id in original_map:
        if doc_id not in by_document:
            coverage[0] += 1
    issue_counts = Counter(row["code"] for row in issues)
    severity_counts = Counter(row["severity"] for row in issues)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "review_queue.jsonl", issues)
    _write_jsonl(output_dir / "span_comparisons.jsonl", comparisons)
    comparison_fields = ["idacordao", "comparison", "project", "task", "left_spans",
                         "right_spans", "unchanged", "only_left", "only_right"]
    _write_csv(output_dir / "span_comparisons.csv", comparisons, comparison_fields)
    summary = {
        "schema_version": "1.0.0", "original_documents": len(originals),
        "evaluations": len(evaluations), "evaluated_documents": len(by_document),
        "project_counts": dict(sorted(project_counts.items())),
        "evaluation_coverage": {str(n): coverage[n] for n in (0, 1, 2) },
        "unexpected_evaluations_per_document": {str(n): c for n, c in coverage.items() if n > 2},
        "issue_counts": dict(sorted(issue_counts.items())),
        "issue_severity_counts": dict(sorted(severity_counts.items())),
        "label_task_counts": {task: counts[f"label_task:{task}"] for task in ("NER", "SEG", "UNKNOWN")},
        "original_labeled_items": counts["original_labeled_items"],
        "evaluation_labeled_items": counts["evaluation_labeled_items"],
        "original_valid_unique_spans": counts["original_valid_unique_spans"],
        "evaluation_valid_unique_spans": counts["evaluation_valid_unique_spans"],
        "non_label_result_types": {k.split(":", 1)[1]: v for k, v in counts.items()
                                   if k.startswith("result_type:")},
        "mismatch_type_counts": {k.split(":", 1)[1]: v for k, v in counts.items()
                                 if k.startswith("text_mismatch:")},
        "comparison_record_counts": dict(sorted(Counter(row["comparison"] for row in comparisons).items())),
        "comparison_totals": {name: {field: sum(row[field] for row in comparisons if row["comparison"] == name)
                                    for field in ("unchanged", "only_left", "only_right")}
                              for name in ("original_vs_evaluation", "evaluation_vs_evaluation")},
        "input_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (originals_file, resolved_file, labels_file)},
        "policy": "read-only technical diagnostics; no adjudication; only validated exact span signatures compared",
    }
    (output_dir / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--evaluations", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=Path("configs/labels.json"))
    parser.add_argument("--output", type=Path, default=Path("data/interim/phase_2/audit"))
    args = parser.parse_args()
    print(json.dumps(audit_phase2(args.original, args.evaluations, args.labels, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
