"""Diagnostic reconciliation for ID-linked Phase 2 reviews, without adjudication.

Input texts stay local. Reports contain identifiers and metadata only, never
document text, annotation excerpts, comments or user names.
"""
from __future__ import annotations

import argparse
import csv
import json
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


def read_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list) or any(not isinstance(x, dict) for x in data):
        raise ValueError(f"Expected JSON array of objects: {path}")
    return data


def doc_id(task: dict[str, Any]) -> str:
    data = task.get("data")
    value = data.get("idacordao") if isinstance(data, dict) else None
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError("Missing data.idacordao")
    return str(value).strip()


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).casefold()
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def regions(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    annotations = task.get("annotations")
    if not isinstance(annotations, list) or len(annotations) != 1:
        raise ValueError("Expected exactly one annotation per task")
    result = annotations[0].get("result")
    if not isinstance(result, list):
        raise ValueError("Invalid annotation result list")
    found: dict[str, dict[str, Any]] = {}
    for item in result:
        if not isinstance(item, dict) or item.get("type") not in {"labels", "choices", "textarea"}:
            continue
        key = item.get("id")
        if not isinstance(key, str) or not key:
            raise ValueError("Invalid region ID")
        found.setdefault(key, {"labels": [], "choices": [], "textarea": []})[item["type"]].append(item)
    return found


def labeled(group: dict[str, Any] | None) -> tuple[tuple[str, ...], int, int] | None:
    if not group or len(group["labels"]) != 1:
        return None
    val = group["labels"][0].get("value") or {}
    labels = val.get("labels")
    start, end = val.get("start"), val.get("end")
    if not isinstance(labels, list) or not labels or not all(isinstance(x, str) for x in labels):
        return None
    if not all(isinstance(x, int) and not isinstance(x, bool) for x in (start, end)):
        return None
    return tuple(labels), start, end


def choice(group: dict[str, Any] | None) -> str | None:
    if not group:
        return None
    values = []
    for result in group["choices"]:
        value = result.get("value") or {}
        if isinstance(value, dict) and isinstance(value.get("choices"), list):
            values.extend(normalize(str(x)) for x in value["choices"])
    if len(values) != 1:
        return None
    return values[0] if values[0] in {"certo", "incorreto", "limite impreciso"} else None


def marked_new(group: dict[str, Any]) -> bool:
    for item in group["textarea"]:
        values = (item.get("value") or {}).get("text") or []
        if not isinstance(values, list):
            values = [values]
        if any("nova anotac" in normalize(str(v)) for v in values):
            return True
    return False


def _comparison(a: dict[str, Any] | None, b: dict[str, Any] | None) -> str:
    if not a or not b or not a["labels"] or not b["labels"]:
        return "region_missing_in_one_review"
    first, second = choice(a), choice(b)
    if first is None and second is None:
        return "both_choices_missing"
    if first is None or second is None:
        return "one_choice_missing"
    return "explicit_choice_agreement" if first == second else "explicit_choice_disagreement"


def _overlap(a: tuple[tuple[str, ...], int, int],
             b: tuple[tuple[str, ...], int, int]) -> bool:
    return max(a[1], b[1]) < min(a[2], b[2])


def _candidate_relation(a: tuple, b: tuple) -> str | None:
    if a == b:
        return "duplicate_original_span"
    if a[1:] == b[1:]:
        return "same_offsets_different_label"
    if not _overlap(a, b):
        return None
    if a[0] == b[0]:
        return "overlapping_same_label_different_offsets"
    return "overlapping_different_label_and_offsets"


def reconcile(
    originals: list[dict[str, Any]], evaluations: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    base = {}
    for task in originals:
        key = doc_id(task)
        if key in base:
            raise ValueError("Duplicate original decision")
        base[key] = regions(task)
    reviews = {}
    stats = Counter()
    candidate_rows = []
    for task in evaluations:
        doc, project = doc_id(task), str(task.get("project"))
        if doc not in base or project not in {"11", "17"}:
            raise ValueError("Unknown document or project")
        key = (doc, project)
        if key in reviews:
            raise ValueError("Duplicate document/project evaluation")
        current = regions(task)
        reviews[key] = current
        old = base[doc]
        old_labels = {key: labeled(value) for key, value in old.items()}
        old_labels = {key: value for key, value in old_labels.items() if value is not None}
        now = {key: labeled(group) for key, group in current.items()}
        now = {key: value for key, value in now.items() if value is not None}
        stats[f"project_{project}_evaluations"] += 1
        for rid, signature in now.items():
            if rid in old_labels:
                stats["matched_original_region_ids"] += 1
                c = choice(current[rid])
                stats["original_region_choices_explicit" if c else "original_region_choices_missing"] += 1
            else:
                stats["new_region_ids"] += 1
                marker = marked_new(current[rid])
                stats["new_region_explicit_comment" if marker else "new_region_without_marker"] += 1
                candidates = []
                for oid, original_signature in old_labels.items():
                    existing = current.get(oid)
                    state = choice(existing)
                    original_id_missing = labeled(existing) is None
                    if state not in {"incorreto", "limite impreciso"} and not original_id_missing:
                        continue
                    relation = _candidate_relation(original_signature, signature)
                    if relation:
                        candidates.append({"original_region_id": oid, "relation": relation,
                                           "original_choice": state,
                                           "original_id_missing": original_id_missing})
                count = len(candidates)
                stats["new_regions_with_candidate" if count else "new_regions_without_candidate"] += 1
                if count > 1:
                    stats["new_regions_with_multiple_candidates"] += 1
                for item in candidates:
                    stats["candidate_" + item["relation"]] += 1
                candidate_rows.append({
                    "idacordao": doc, "project": project, "new_region_id": rid,
                    "explicit_new_annotation_comment": marker,
                    "candidate_count": count, "candidate_links": candidates,
                    "status": "requires_manual_classification",
                })

    comparisons = []
    docs_with_two = 0
    for doc, prior in base.items():
        a, b = reviews.get((doc, "11")), reviews.get((doc, "17"))
        if a is None or b is None:
            continue
        docs_with_two += 1
        for rid, group in prior.items():
            if labeled(group) is None:
                continue
            ga, gb = a.get(rid), b.get(rid)
            status = _comparison(ga, gb)
            stats[status] += 1
            sig_a, sig_b = labeled(ga), labeled(gb)
            comparisons.append({
                "idacordao": doc, "original_region_id": rid,
                "status": status,
                "choice_project_11": choice(ga) or "missing",
                "choice_project_17": choice(gb) or "missing",
                "same_label": sig_a is not None and sig_b is not None and sig_a[0] == sig_b[0],
                "same_offsets": sig_a is not None and sig_b is not None and sig_a[1:] == sig_b[1:],
            })
    stats["documents_with_two_reviews"] = docs_with_two
    report = {
        "schema_version": "1.0.0",
        "original_documents": len(base),
        "evaluation_records": len(evaluations),
        "counts": dict(sorted(stats.items())),
        "policy": "Read-only evidence; missing choices are not agreement; region IDs are scoped by document.",
    }
    return report, candidate_rows, comparisons


def run(original_path: Path, evaluated_path: Path, out_dir: Path) -> dict[str, Any]:
    report, candidates, comparisons = reconcile(read_json(original_path), read_json(evaluated_path))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reconciliation_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (out_dir / "candidate_new_regions.jsonl").open("w", encoding="utf-8") as stream:
        for record in candidates:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    fields = ["idacordao", "original_region_id", "status",
              "choice_project_11", "choice_project_17", "same_label", "same_offsets"]
    with (out_dir / "paired_choice_review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(comparisons)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--evaluations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.original.resolve() == args.evaluations.resolve():
        parser.error("Inputs must be distinct")
    print(json.dumps(run(args.original, args.evaluations, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
