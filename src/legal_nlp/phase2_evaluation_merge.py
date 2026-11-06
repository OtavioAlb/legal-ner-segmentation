"""Merge Label Studio evaluation exports, enriching each with original annotator.

This is structural consolidation only: no span, label, reviewer vote, or
offset is modified. Both evaluations remain separate records for one acórdão.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError(f"Expected JSON array of objects: {path}")
    return data


def _idacordao(task: dict[str, Any]) -> str:
    data = task.get("data")
    raw = data.get("idacordao") if isinstance(data, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ValueError(f"Missing/invalid idacordao in task {task.get('id')}")
    value = str(raw).strip()
    if not value:
        raise ValueError(f"Blank idacordao in task {task.get('id')}")
    return value


def _single_completed_by(task: dict[str, Any], context: str) -> int:
    annotations = task.get("annotations")
    if not isinstance(annotations, list) or len(annotations) != 1:
        raise ValueError(f"{context} must have exactly one annotation for idacordao={_idacordao(task)}")
    annotation = annotations[0]
    if not isinstance(annotation, dict) or annotation.get("was_cancelled"):
        raise ValueError(f"{context} contains missing/cancelled annotation for {_idacordao(task)}")
    user_id = annotation.get("completed_by")
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise ValueError(f"{context} has missing/invalid completed_by for {_idacordao(task)}")
    return user_id


def merge_evaluation_exports(
    annotations_path: str | Path,
    evaluation_paths: list[str | Path],
    output_path: str | Path,
    report_path: str | Path | None = None,
    expected_original_documents: int | None = None,
) -> dict[str, Any]:
    """Produce 1 record per evaluation (not 1 per decision), sorted by annotator.

    Only adds top-level annotated_by/evaluated_by. Preserves original JSON
    evaluation fields, including annotations, predictions, data and metadata.
    """
    annotations_path = Path(annotations_path)
    evaluation_paths = [Path(p) for p in evaluation_paths]
    output_path = Path(output_path)
    report_path = Path(report_path) if report_path is not None else output_path.with_suffix(".report.json")
    if len(evaluation_paths) != 2 or len(set(evaluation_paths)) != 2:
        raise ValueError("Exactly two distinct evaluation exports are required")
    if len({annotations_path.resolve(), output_path.resolve(), report_path.resolve(),
            *(x.resolve() for x in evaluation_paths)}) != 5:
        raise ValueError("Input and output paths must all be distinct")
    originals = _load_json_array(annotations_path)
    orig_by_acordao: dict[str, dict[str, Any]] = {}
    for source in originals:
        idacordao = _idacordao(source)
        if idacordao in orig_by_acordao:
            raise ValueError(f"Duplicate original idacordao: {idacordao}")
        orig_by_acordao[idacordao] = source
        _single_completed_by(source, "Original")
    if expected_original_documents is not None and len(orig_by_acordao) != expected_original_documents:
        raise ValueError(
            f"Expected {expected_original_documents} original acórdãos; got {len(orig_by_acordao)}"
        )

    output: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    original_annotator_counts: Counter[int] = Counter()
    evaluator_counts: Counter[int] = Counter()
    evaluations_per_document: Counter[str] = Counter()
    pairs: set[tuple[str, int]] = set()
    missing: list[str] = []
    text_mismatches: list[str] = []
    for path in evaluation_paths:
        evaluation_tasks = _load_json_array(path)
        for task in evaluation_tasks:
            idacordao = _idacordao(task)
            original = orig_by_acordao.get(idacordao)
            if original is None:
                missing.append(idacordao)
                continue
            if task.get("data", {}).get("acordao") != original.get("data", {}).get("acordao"):
                text_mismatches.append(idacordao)
                continue
            annotated_by = _single_completed_by(original, "Original")
            evaluated_by = _single_completed_by(task, "Evaluation")
            if annotated_by == evaluated_by:
                raise ValueError(f"Self-evaluation detected: {idacordao}")
            if (idacordao, evaluated_by) in pairs:
                raise ValueError(f"Repeated evaluation by same reviewer: {idacordao}/{evaluated_by}")
            if "annotated_by" in task or "evaluated_by" in task:
                raise ValueError(f"Evaluation already has enrichment fields: {idacordao}")
            pairs.add((idacordao, evaluated_by))
            row = dict(task)
            row["annotated_by"] = annotated_by
            row["evaluated_by"] = evaluated_by
            output.append(row)
            source_counts[path.name] += 1
            original_annotator_counts[annotated_by] += 1
            evaluator_counts[evaluated_by] += 1
            evaluations_per_document[idacordao] += 1

    if missing or text_mismatches:
        raise ValueError(
            "Cannot safely merge: "
            f"unmatched={sorted(set(missing))}, text_mismatches={sorted(set(text_mismatches))}"
        )
    if any(n > 2 for n in evaluations_per_document.values()):
        raise ValueError("More than two evaluations for a single acórdão")
    output.sort(key=lambda x: (x["annotated_by"], _idacordao(x), x["evaluated_by"]))
    coverage = dict(sorted(Counter(evaluations_per_document.values()).items()))
    summary = {
        "schema_version": "1.0.0",
        "original_acordaos": len(originals),
        "original_unique_acordaos": len(orig_by_acordao),
        "evaluation_records_merged": len(output),
        "evaluated_unique_acordaos": len(evaluations_per_document),
        "acordaos_with_two_evaluations": coverage.get(2, 0),
        "acordaos_with_one_evaluation": coverage.get(1, 0),
        "acordaos_without_evaluations": len(orig_by_acordao) - len(evaluations_per_document),
        "source_evaluation_record_counts": dict(sorted(source_counts.items())),
        "evaluation_records_by_original_annotator": dict(sorted(original_annotator_counts.items())),
        "evaluation_records_by_evaluator": dict(sorted(evaluator_counts.items())),
        "text_mismatches": 0,
        "unmatched_evaluation_records": 0,
        "duplicate_reviewer_per_acordao": 0,
        "original_sha256": hashlib.sha256(annotations_path.read_bytes()).hexdigest(),
        "evaluation_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in evaluation_paths
        },
        "policy": (
            "One output record per evaluation; join on data.idacordao; annotated_by "
            "from original annotations[0].completed_by; evaluated_by from evaluated "
            "annotations[0].completed_by; original evaluation structure untouched; "
            "missing second evaluation is accepted"
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge two Phase 2 evaluation JSON exports")
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--evaluation-1", type=Path, required=True)
    parser.add_argument("--evaluation-2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--expected-original-documents", type=int, default=35)
    args = parser.parse_args()
    result = merge_evaluation_exports(
        args.annotations,
        [args.evaluation_1, args.evaluation_2],
        args.output,
        args.report,
        expected_original_documents=args.expected_original_documents,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
