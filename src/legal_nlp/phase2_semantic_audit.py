"""Read-only semantic audit of Phase 2 Label Studio decisions by stable region ID.

Originals and reviewed exports are private. This module produces only local,
text-free diagnostics. No annotation, choice, comment, or offset is rewritten.
"""
from __future__ import annotations

import argparse
import csv
import json
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


def _load(path: Path) -> list[dict[str, Any]]:
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, list) or any(not isinstance(x, dict) for x in result):
        raise ValueError(f"Expected array of objects: {path}")
    return result


def _doc_id(task: dict[str, Any]) -> str:
    data = task.get("data")
    value = data.get("idacordao") if isinstance(data, dict) else None
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError("Missing data.idacordao")
    return str(value).strip()


def _regions(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    annotations = task.get("annotations")
    if not isinstance(annotations, list) or len(annotations) != 1:
        raise ValueError(f"Expected exactly one annotation in task {task.get('id')}")
    results = annotations[0].get("result")
    if not isinstance(results, list):
        raise ValueError("Annotation result must be a list")
    regions: dict[str, dict[str, Any]] = {}
    for item in results:
        if not isinstance(item, dict) or item.get("type") not in {"labels", "choices", "textarea"}:
            continue
        key = item.get("id")
        if not isinstance(key, str) or not key:
            raise ValueError("Missing region ID")
        region = regions.setdefault(key, {"labels": [], "choices": [], "textarea": []})
        region[item["type"]].append(item)
    return regions


def _signature(region: dict[str, Any]) -> tuple[Any, Any, tuple[str, ...]] | None:
    if len(region["labels"]) != 1:
        return None
    value = region["labels"][0].get("value") or {}
    labels = value.get("labels")
    if not isinstance(labels, list):
        return None
    return value.get("start"), value.get("end"), tuple(labels)


def _choice(region: dict[str, Any]) -> tuple[str, ...]:
    choices: list[str] = []
    for entry in region["choices"]:
        value = entry.get("value") or {}
        choices.extend(value.get("choices") or [])
    return tuple(choices)


def _comment_info(region: dict[str, Any]) -> tuple[int, bool]:
    comments = []
    for item in region["textarea"]:
        value = item.get("value") or {}
        comments.extend(value.get("text") or [])
    normalized = " ".join(
        "".join(ch for ch in unicodedata.normalize("NFKD", str(t)).casefold()
                if not unicodedata.combining(ch))
        for t in comments
    )
    return len(comments), "nova anotac" in normalized


def _change(before: tuple | None, after: tuple | None) -> str:
    if before is None or after is None:
        return "missing_or_ambiguous_label"
    label_changed = before[2] != after[2]
    offset_changed = before[:2] != after[:2]
    return ("label_and_offset" if label_changed and offset_changed else
            "label_only" if label_changed else "offset_only" if offset_changed else "unchanged")


def audit(original_path: str | Path, evaluation_path: str | Path,
          output_dir: str | Path) -> dict[str, Any]:
    original_path, evaluation_path = Path(original_path), Path(evaluation_path)
    output_dir = Path(output_dir)
    if original_path.resolve() == evaluation_path.resolve():
        raise ValueError("Input paths must differ")
    originals = _load(original_path)
    evaluations = _load(evaluation_path)
    by_doc = {}
    for task in originals:
        document = _doc_id(task)
        if document in by_doc:
            raise ValueError(f"Repeated original document: {document}")
        by_doc[document] = _regions(task)

    events: list[dict[str, Any]] = []
    review_by_doc: dict[str, dict[str, dict[str, Any]]] = {}
    tally = Counter()
    issues: list[dict[str, Any]] = []

    for task in evaluations:
        document, project = _doc_id(task), str(task.get("project"))
        if project not in {"11", "17"}:
            raise ValueError(f"Unknown evaluation project: {project}")
        if document not in by_doc:
            raise ValueError(f"Unmatched evaluated document: {document}")
        pair_key = document + ":" + project
        if pair_key in review_by_doc:
            raise ValueError(f"Duplicate document/project: {pair_key}")
        prior, current = by_doc[document], _regions(task)
        review_by_doc[pair_key] = current

        for region_id, region in current.items():
            if not region["labels"]:
                continue
            original = prior.get(region_id)
            before = _signature(original) if original else None
            after = _signature(region)
            state = _choice(region)
            comments, new_comment = _comment_info(region)
            is_new = original is None
            change = "new_region_id" if is_new else _change(before, after)
            if not state:
                status = "not_recorded"
            elif len(state) == 1 and state[0] in {"Certo", "Incorreto", "Limite impreciso"}:
                status = state[0]
            else:
                status = "multiple_or_unknown_choices"

            flags = []
            if status == "Certo" and not is_new and change != "unchanged":
                flags.append("CORRECT_WITH_CHANGED_SPAN")
            if status == "Incorreto" and not is_new and change not in {"label_only", "label_and_offset"}:
                flags.append("INCORRECT_WITHOUT_LABEL_CHANGE")
            if status == "Limite impreciso" and not is_new and change not in {"offset_only", "label_and_offset"}:
                flags.append("IMPRECISE_WITHOUT_OFFSET_CHANGE")
            if status == "not_recorded" and not is_new:
                flags.append("ORIGINAL_REGION_WITHOUT_CHOICE")
            if status == "multiple_or_unknown_choices":
                flags.append("AMBIGUOUS_CHOICE")
            if is_new:
                flags.append("NEW_REGION_ID_REQUIRES_CLASSIFICATION")
            if after is None:
                flags.append("AMBIGUOUS_REGION_LABEL")
            event = {
                "idacordao": document, "project": project, "region_id": region_id,
                "annotated_by": task.get("annotated_by"),
                "evaluated_by": task.get("evaluated_by"),
                "region_relation": "new_id" if is_new else "original_id",
                "choice": status, "change": change, "comment_entries": comments,
                "comment_mentions_new_annotation": new_comment,
                "original_start": before[0] if before else None,
                "original_end": before[1] if before else None,
                "original_labels": list(before[2]) if before else [],
                "reviewed_start": after[0] if after else None,
                "reviewed_end": after[1] if after else None,
                "reviewed_labels": list(after[2]) if after else [],
                "flags": flags,
            }
            events.append(event)
            tally["reviewed_regions"] += 1
            tally["relation:" + event["region_relation"]] += 1
            tally["choice:" + status] += 1
            tally["change:" + change] += 1
            tally["choice_change:" + status + "/" + change] += 1
            if comments:
                tally["regions_with_comments"] += 1
            if new_comment:
                tally["comments_marked_new_annotation"] += 1
            if flags:
                for code in flags:
                    tally["flag:" + code] += 1
                issues.append({k: event[k] for k in
                               ("idacordao", "project", "region_id", "choice", "change", "flags")})

        missing = sorted(set(prior) - set(current))
        for region_id in missing:
            if not prior[region_id]["labels"]:
                continue
            tally["missing_original_regions"] += 1
            issues.append({"idacordao": document, "project": project,
                           "region_id": region_id, "choice": "missing",
                           "change": "original_id_absent", "flags": ["ORIGINAL_REGION_ID_MISSING"]})

    comparisons = []
    for document in by_doc:
        left, right = (review_by_doc.get(document + ":11"),
                       review_by_doc.get(document + ":17"))
        if left is None or right is None:
            continue
        for region_id in sorted(set(by_doc[document]) & (set(left) | set(right))):
            if not by_doc[document][region_id]["labels"]:
                continue
            a, b = left.get(region_id), right.get(region_id)
            if a is None or b is None:
                relation = "missing_in_one_evaluation"
            elif _signature(a) == _signature(b) and _choice(a) == _choice(b):
                relation = "same_span_and_choice"
            elif _signature(a) == _signature(b):
                relation = "same_span_different_choice"
            elif _choice(a) == _choice(b):
                relation = "different_span_same_choice"
            else:
                relation = "different_span_and_choice"
            comparisons.append({
                "idacordao": document, "region_id": region_id,
                "comparison": relation, "choice_11": list(_choice(a)) if a else [],
                "choice_17": list(_choice(b)) if b else [],
                "span_change_between_reviews": (
                    _change(_signature(a), _signature(b)) if a and b else "not_comparable"
                ),
            })
            tally["review_comparison:" + relation] += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, records in (
        ("region_decisions.jsonl", events),
        ("review_queue.jsonl", issues),
        ("reviewer_comparisons.jsonl", comparisons),
    ):
        with (output_dir / filename).open("w", encoding="utf-8") as stream:
            for entry in records:
                stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "original_documents": len(originals),
        "evaluation_records": len(evaluations),
        "decision_regions": len(events),
        "comparison_regions": len(comparisons),
        "review_queue_entries": len(issues),
        "counts": dict(sorted(tally.items())),
        "policy": "Read-only by-region decision audit; new IDs and corrections are not automatically gold.",
    }
    (output_dir / "semantic_audit_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--evaluations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.original, args.evaluations, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
