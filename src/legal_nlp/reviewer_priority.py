"""Read-only reviewer-label provenance for near-boundary span candidates.

An evaluator's final corrected label prevails over THAT source annotation's
original label. A pair of independently reviewed spans can still be valid
multilabel annotation. Priority evidence never drops either span.
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
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _review_evidence(ann: dict[str, Any]) -> dict[str, Any]:
    status = ann.get("target_selection_status")
    original = (ann.get("fields_original") or {}).get("label")
    revised = (ann.get("fields_revised") or {}).get("label")
    changed = (
        status == "reviewed_final"
        and revised is not None
        and original != revised
    )
    return {
        "annotation_id": ann["annotation_id"],
        "source_row": ann.get("source_row"),
        "annotator_id": ann.get("annotator_id"),
        "target_selection_status": status,
        "label_original_before_review": original,
        "label_revised_by_evaluators": revised,
        "explicit_evaluator_label_change": changed,
        "review_agree_count": ann.get("review_agree_count"),
        "review_disagree_count": ann.get("review_disagree_count"),
        "disagreement_reviewers": ann.get("disagreement_reviewers") or [],
    }


def audit_reviewer_label_priority(
    annotations_path: str | Path,
    candidates_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Identify label-correction evidence without resolving independent spans."""
    annotations_path = Path(annotations_path)
    candidates_path = Path(candidates_path)
    output_dir = Path(output_dir)
    anns = _read_jsonl(annotations_path)
    ann_by_id: dict[str, dict[str, Any]] = {}
    for ann in anns:
        identifier = ann["annotation_id"]
        if identifier in ann_by_id:
            raise ValueError(f"Duplicate annotation ID: {identifier}")
        ann_by_id[identifier] = ann

    candidate_rows = _read_jsonl(candidates_path)
    output: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    cases_with_shared_annotator = 0

    for candidate in candidate_rows:
        left, right = candidate["first"], candidate["second"]
        if left["label"] == right["label"]:
            continue

        evidence: dict[str, list[dict[str, Any]]] = {}
        changed_counts: dict[str, int] = {}
        for key, group in (("first", left), ("second", right)):
            ids = group["annotation_ids"]
            if not ids:
                raise ValueError("Candidate group must have annotations")
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate annotation IDs within a candidate group")
            try:
                evidence[key] = [
                    _review_evidence(ann_by_id[annotation_id]) for annotation_id in ids
                ]
            except KeyError as exc:
                raise ValueError(
                    f"Missing original annotation for {exc.args[0]}"
                ) from exc
            # All input candidates came from the sanitized supervised view.
            if any(item["target_selection_status"] not in {
                "reviewed_final", "original_confirmed_by_reviewers"
            } for item in evidence[key]):
                raise ValueError("Candidate references a non-final annotation")
            changed_counts[key] = sum(
                item["explicit_evaluator_label_change"] for item in evidence[key]
            )

        first_changed = changed_counts["first"] > 0
        second_changed = changed_counts["second"] > 0
        if first_changed and second_changed:
            status = "competing_evaluator_label_corrections"
            suggested_priority_side = None
        elif first_changed or second_changed:
            status = "one_side_has_explicit_evaluator_label_correction"
            suggested_priority_side = "first" if first_changed else "second"
        else:
            status = "no_explicit_label_correction_to_prioritize"
            suggested_priority_side = None

        # The user's priority applies to the earlier ORIGINAL label in a
        # given annotation, not automatically to a competing separately
        # reviewed annotation from another annotator.
        shared_annotators = candidate.get("shared_annotator_ids") or []
        if shared_annotators:
            cases_with_shared_annotator += 1
        row = {
            "document_id": candidate["document_id"],
            "task": candidate["task"],
            "boundary_category": candidate["category"],
            "first_label": left["label"],
            "second_label": right["label"],
            "first_start": left["start"],
            "first_end": left["end"],
            "second_start": right["start"],
            "second_end": right["end"],
            "delta_start": candidate["delta_start"],
            "delta_end": candidate["delta_end"],
            "shared_annotator_ids": shared_annotators,
            "priority_evidence_status": status,
            "priority_evidence_side": suggested_priority_side,
            "first_review_evidence": evidence["first"],
            "second_review_evidence": evidence["second"],
            "resolution": "retain_both_pending_span_level_policy",
            "automatic_label_removal": False,
        }
        output.append(row)
        status_counts[status] += 1
        task_counts[row["task"]] += 1
        category_counts[row["boundary_category"]] += 1

    summary = {
        "review_priority_schema_version": "1.0.0",
        "input_candidate_pairs": len(candidate_rows),
        "different_label_candidate_pairs": len(output),
        "same_label_candidate_pairs_skipped": len(candidate_rows) - len(output),
        "cases_with_shared_annotator": cases_with_shared_annotator,
        "per_task_counts": dict(sorted(task_counts.items())),
        "per_category_counts": dict(sorted(category_counts.items())),
        "priority_evidence_status_counts": dict(sorted(status_counts.items())),
        "policy": (
            "evaluator corrections supersede original fields within each source "
            "annotation; independent final span labels remain valid candidates; "
            "no automatic winner, deletion, BIO conversion or LLM arbitration"
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "different_label_review_evidence.jsonl", output)
    (output_dir / "review_priority_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit evaluator precedence for different-label span candidates"
    )
    parser.add_argument(
        "--annotations", type=Path,
        default=Path("data/interim/phase_1/annotations.jsonl"),
    )
    parser.add_argument(
        "--candidates", type=Path,
        default=Path("data/interim/phase_1/span_diagnostics/near_boundary_candidates.jsonl"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/interim/phase_1/reviewer_priority"),
    )
    args = parser.parse_args()
    print(json.dumps(
        audit_reviewer_label_priority(args.annotations, args.candidates, args.output),
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
