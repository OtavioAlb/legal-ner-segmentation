"""Conservative deterministic Phase 2 Label Studio provenance audit.

One row per (acordao, region_id). No automatic gold-label decisions.
Review absence is NEVER agreement. Geometry is diagnostic, not identity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_tasks(path):
    tasks = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(tasks, list):
        raise ValueError("Expected list of Label Studio tasks")
    docs = {}
    for task in tasks:
        doc = str(task["data"]["idacordao"])
        if doc in docs:
            raise ValueError(f"Repeated document in export: {doc}")
        active = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
        if len(active) != 1:
            raise ValueError(f"Expected one active annotation for {doc}")
        docs[doc] = task
    return docs


def regions(task):
    if task is None:
        return {}
    entries = defaultdict(lambda: defaultdict(list))
    for entry in task["annotations"][0].get("result", []):
        if entry.get("type") in {"labels", "choices", "textarea"}:
            rid = entry.get("id")
            if not rid:
                raise ValueError("Missing region ID")
            entries[str(rid)][entry["type"]].append(entry.get("value") or {})
    out = {}
    for rid, fields in entries.items():
        if len(fields["labels"]) > 1 or len(fields["choices"]) > 1:
            raise ValueError(f"Ambiguous region {rid}")
        if not fields["labels"]:
            continue  # dangling choice/comment; not a span
        value = fields["labels"][0]
        labels = value.get("labels") or []
        if len(labels) != 1:
            raise ValueError(f"Ambiguous label for {rid}")
        start, end = value.get("start"), value.get("end")
        if (type(start) is not int or type(end) is not int or start < 0 or end <= start):
            raise ValueError(f"Invalid offsets for {rid}")
        label = labels[0]
        choice = fields["choices"][0].get("choices", []) if fields["choices"] else []
        comments = [str(t) for c in fields["textarea"] for t in (
            c.get("text") if isinstance(c.get("text"), list) else [c.get("text")]
        ) if t]
        out[rid] = {
            "id": rid, "task": "NER" if label.startswith("ENT_") else
            "SEG" if label.startswith("SEG_") else "UNKNOWN",
            "label": label, "start": start, "end": end,
            "text": value.get("text", ""),
            "choice": choice[0] if len(choice) == 1 else None,
            "comment": " | ".join(comments),
        }
    return out


def geometry(region):
    return tuple(region[k] for k in ("task", "start", "end", "label"))


def audit(original, evaluation_11, evaluation_17, output):
    source = load_tasks(original)
    review = {11: load_tasks(evaluation_11), 17: load_tasks(evaluation_17)}
    extra = (set(review[11]) | set(review[17])) - set(source)
    if extra:
        raise ValueError(f"Review without original: {sorted(extra)}")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    candidate_groups = defaultdict(list)
    for doc, task in sorted(source.items()):
        base = regions(task)
        other = {p: regions(review[p].get(doc)) for p in (11, 17)}
        base_geometry = defaultdict(list)
        for rid, r in base.items():
            base_geometry[geometry(r)].append(rid)
        for rid in sorted(set(base) | set(other[11]) | set(other[17])):
            original_region = base.get(rid)
            reviewer_regions = {p: other[p].get(rid) for p in (11, 17)}
            anchor = original_region or next(r for r in reviewer_regions.values() if r)
            reasons = []
            is_new = original_region is None
            if is_new:
                reasons.append("NOT_IN_ORIGINAL_BY_ID")
                if geometry(anchor) in base_geometry:
                    reasons.append("SAME_GEOMETRY_DIFFERENT_ID")
            if anchor["task"] == "UNKNOWN":
                reasons.append("UNKNOWN_LABEL_PREFIX")
            for p in (11, 17):
                r = reviewer_regions[p]
                if r is None:
                    reasons.append(f"ABSENT_IN_REVIEW_{p}")
                    continue
                if original_region and geometry(r) != geometry(original_region):
                    reasons.append(f"MODIFIED_SPAN_{p}")
                if is_new and geometry(r) != geometry(anchor):
                    reasons.append(f"CONFLICTING_NEW_SPAN_{p}")
                choice = (r["choice"] or "").strip().casefold()
                if choice in {"incorreto", "limite impreciso"}:
                    reasons.append(f"EXPLICIT_NEGATIVE_{p}")
                elif choice and choice != "certo":
                    reasons.append(f"UNKNOWN_CHOICE_{p}")
                if r["comment"]:
                    reasons.append(f"COMMENT_{p}")
            row = {
                "idacordao": doc, "region_id": rid,
                "audit_id": "p2_" + hashlib.sha256(
                    json.dumps([doc, rid]).encode("utf-8")
                ).hexdigest()[:20],
                "origin": "NEW_IN_REVIEW" if is_new else "ORIGINAL",
                "status": "PENDING_NEW" if is_new else
                "ORIGINAL_WITH_FLAGS" if reasons else "ORIGINAL_NO_FLAGS",
                "task": anchor["task"], "label": anchor["label"],
                "start": anchor["start"], "end": anchor["end"],
                "text": anchor["text"], "original": original_region,
                "original_annotator_id": task["annotations"][0]["completed_by"],
                "review_11": reviewer_regions[11], "review_17": reviewer_regions[17],
                "reviewer_11_id": review[11][doc]["annotations"][0]["completed_by"]
                if doc in review[11] else None,
                "reviewer_17_id": review[17][doc]["annotations"][0]["completed_by"]
                if doc in review[17] else None,
                "reasons": sorted(set(reasons)),
                "same_geometry_original_ids": base_geometry.get(geometry(anchor), []) if is_new else [],
                "adjudicated": False,
            }
            rows.append(row)
            if is_new:
                candidate_groups[(doc, *geometry(anchor))].append(row)
    with (output / "phase2_audit.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    columns = ["audit_id", "idacordao", "region_id", "origin", "status", "task",
               "label", "start", "end", "text", "original_annotator_id",
               "reviewer_11_id", "review_11_label", "review_11_start",
               "review_11_end", "review_11_choice", "review_11_comment",
               "reviewer_17_id", "review_17_label", "review_17_start",
               "review_17_end", "review_17_choice", "review_17_comment",
               "same_geometry_original_ids", "reasons", "human_decision"]
    with (output / "phase2_audit.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            flat = {k: row.get(k) for k in columns}
            for p in (11, 17):
                for field in ("label", "start", "end", "choice", "comment"):
                    flat[f"review_{p}_{field}"] = (row[f"review_{p}"] or {}).get(field)
            flat["same_geometry_original_ids"] = ";".join(row["same_geometry_original_ids"])
            flat["reasons"] = ";".join(row["reasons"])
            writer.writerow(flat)
    with (output / "phase2_new_candidate_groups.jsonl").open("w", encoding="utf-8") as handle:
        for key, group in sorted(candidate_groups.items()):
            group_row = {
                "idacordao": key[0], "task": key[1], "start": key[2],
                "end": key[3], "label": key[4],
                "source_region_ids": sorted(r["region_id"] for r in group),
                "source_audit_ids": sorted(r["audit_id"] for r in group),
                "projects_proposing": sorted({p for r in group for p in (11, 17)
                                              if r[f"review_{p}"] is not None}),
                "adjudicated": False,
            }
            handle.write(json.dumps(group_row, ensure_ascii=False, sort_keys=True) + "\n")
    summary = {
        "schema_version": "1.0", "documents": len(source),
        "region_id_records": len(rows),
        "by_origin": dict(sorted(Counter(r["origin"] for r in rows).items())),
        "by_status": dict(sorted(Counter(r["status"] for r in rows).items())),
        "new_exact_geometry_groups": len(candidate_groups),
        "new_duplicate_geometry_records": sum(len(g) - 1 for g in candidate_groups.values()),
        "reason_counts": dict(sorted(Counter(x for r in rows for x in r["reasons"]).items())),
        "policy": "ID is identity; geometry is diagnostic; explicit negative kept even on equal offsets; missing review is not agreement; no gold consolidation.",
    }
    (output / "phase2_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True)
    parser.add_argument("--evaluation-11", required=True)
    parser.add_argument("--evaluation-17", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.original, args.evaluation_11, args.evaluation_17, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
