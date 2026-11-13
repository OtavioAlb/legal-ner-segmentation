"""Audit missing reviewer decisions deterministically against original Label Studio regions.

No semantic adjudication; no changes to source exports.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("Expected list of Label Studio tasks")
    return data


def annotation(task):
    active = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
    if len(active) != 1:
        raise ValueError(f"Expected one active annotation: {task.get('id')}")
    return active[0]


def docid(task):
    value = task.get("data", {}).get("idacordao")
    if value is None or isinstance(value, bool):
        raise ValueError("Invalid document ID")
    return str(value)


def regions(task):
    labels, choices = {}, {}
    for item in annotation(task).get("result", []):
        rid, kind = item.get("id"), item.get("type")
        if kind not in {"labels", "choices"}:
            continue
        if not rid:
            raise ValueError("Missing region ID")
        val = item.get("value", {})
        if kind == "labels":
            if rid in labels:
                raise ValueError(f"Repeated region ID: {rid}")
            kinds = val.get("labels", [])
            start, end = val.get("start"), val.get("end")
            if (len(kinds) != 1 or not isinstance(kinds[0], str)
                    or type(start) is not int or type(end) is not int
                    or start < 0 or start >= end):
                raise ValueError(f"Invalid span: {rid}")
            labels[rid] = {"label": kinds[0], "start": start, "end": end}
        elif kind == "choices":
            if rid in choices:
                raise ValueError(f"Repeated choice: {rid}")
            selection = val.get("choices")
            if not isinstance(selection, list) or len(selection) != 1:
                raise ValueError(f"Ambiguous choice: {rid}")
            choices[rid] = selection[0]
    return labels, choices


def classify(original, evaluated, explicit_choice=None):
    if original is None:
        return "nova_regiao"
    if explicit_choice is not None:
        return explicit_choice
    if original["label"] != evaluated["label"]:
        return "incorreto_automatico"
    if (original["start"], original["end"]) != (evaluated["start"], evaluated["end"]):
        return "limite_impreciso_automatico"
    return "correto_automatico"


def audit_reviewer(original_tasks, review_projects, reviewer_id):
    originals = {}
    for task in original_tasks:
        identifier = docid(task)
        if identifier in originals:
            raise ValueError(f"Repeated original document: {identifier}")
        originals[identifier] = task
    rows, docs, review_counts = [], set(), Counter()
    for project, tasks in sorted(review_projects.items()):
        seen = set()
        for task in tasks:
            identifier = docid(task)
            if identifier in seen:
                raise ValueError(f"Repeated document {identifier} in project {project}")
            seen.add(identifier)
            if int(annotation(task).get("completed_by", -1)) != reviewer_id:
                continue
            if identifier not in originals:
                raise ValueError(f"Missing original: {identifier}")
            docs.add(identifier)
            review_counts[str(project)] += 1
            original, _ = regions(originals[identifier])
            evaluated, choices = regions(task)
            for rid in sorted(set(original) | set(evaluated)):
                old, new = original.get(rid), evaluated.get(rid)
                decision = ("nao_avaliada" if new is None else
                            classify(old, new, choices.get(rid)))
                rows.append({
                    "idacordao": identifier, "projeto": project,
                    "avaliador_id": reviewer_id, "region_id": rid,
                    "decision": decision,
                    "label_original": old["label"] if old else "",
                    "start_original": old["start"] if old else "",
                    "end_original": old["end"] if old else "",
                    "label_avaliado": new["label"] if new else "",
                    "start_avaliado": new["start"] if new else "",
                    "end_avaliado": new["end"] if new else "",
                    "label_alterado": bool(old and new and old["label"] != new["label"]),
                    "offset_alterado": bool(old and new and
                        (old["start"], old["end"]) != (new["start"], new["end"])),
                    "choice_explicita": choices.get(rid, ""),
                })
    rows.sort(key=lambda r: (r["projeto"], r["idacordao"], r["region_id"]))
    summary = {
        "reviewer_id": reviewer_id,
        "documents": len(docs),
        "reviews_by_project": dict(sorted(review_counts.items())),
        "total_regions": len(rows),
        "decision_counts": dict(sorted(Counter(x["decision"] for x in rows).items())),
        "policy": "Match by document/region ID; preserve explicit decisions; new regions are manual; do not infer semantic correctness",
    }
    return rows, summary


def run(original, evaluation_11, evaluation_17, output, reviewer_id):
    paths = {"original": Path(original), "evaluation_11": Path(evaluation_11),
             "evaluation_17": Path(evaluation_17)}
    inputs = {key: load(path) for key, path in paths.items()}
    rows, summary = audit_reviewer(
        inputs["original"],
        {11: inputs["evaluation_11"], 17: inputs["evaluation_17"]},
        reviewer_id,
    )
    summary["input_sha256"] = {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in paths.items()
    }
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    columns = [
        "idacordao", "projeto", "avaliador_id", "region_id", "decision",
        "label_original", "start_original", "end_original",
        "label_avaliado", "start_avaliado", "end_avaliado",
        "label_alterado", "offset_alterado", "choice_explicita",
    ]
    with (destination / "reviewer_deterministic_decisions.csv").open(
            "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    (destination / "reviewer_deterministic_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True)
    parser.add_argument("--evaluation-11", required=True)
    parser.add_argument("--evaluation-17", required=True)
    parser.add_argument("--reviewer-id", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(
        run(args.original, args.evaluation_11, args.evaluation_17,
            args.output, args.reviewer_id),
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
