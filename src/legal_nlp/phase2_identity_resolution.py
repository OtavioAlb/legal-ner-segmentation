"""Resolve individual review assignments from an already enriched Phase 2 export.

The inputs remain local. No personal records are bundled in this module.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .phase2_identity_enrichment import (
    find_document_id,
    make_lookup,
    normalize_id,
    read_rows,
    write_rows,
)

PROJECTS = {
    "11": ("avaliador_projeto_1", "projeto_1_id_confirmado"),
    "17": ("avaliador_projeto_2", "projeto_2_id_confirmado"),
}


def resolve(rows, crosswalk):
    lookup = make_lookup(crosswalk)
    assigned_users = {}
    seen = set()
    out = []
    statuses = Counter()
    projects = Counter()

    for source in rows:
        row = dict(source)
        doc_id = find_document_id(row)
        project = normalize_id(row.get("project"))
        annotator_id = normalize_id(row.get("annotated_by"))
        evaluator_id = normalize_id(row.get("evaluated_by"))
        entry = lookup.get(doc_id) if doc_id else None
        row["annotator_name"] = ""
        row["evaluator_name"] = ""

        if entry is None:
            status = "unmatched_acordao"
        elif project not in PROJECTS:
            status = "unknown_project"
        elif annotator_id is None or evaluator_id is None:
            status = "missing_user_id"
        else:
            pair = (doc_id, project)
            if pair in seen:
                raise ValueError(f"Duplicate document/project pair: {pair}")
            seen.add(pair)
            projects[project] += 1
            name_key, confirmed_key = PROJECTS[project]
            if str(entry[confirmed_key]).strip().lower() != "sim":
                status = "assignment_unlisted"
            else:
                people = (
                    (annotator_id, str(entry["anotador"]).strip()),
                    (evaluator_id, str(entry[name_key]).strip()),
                )
                if not all(name for _, name in people):
                    status = "missing_assignment_name"
                else:
                    for user_id, name in people:
                        existing = assigned_users.get(user_id)
                        if existing is not None and existing != name:
                            raise ValueError(f"Conflicting role mapping for user ID {user_id}")
                        assigned_users[user_id] = name
                    row["annotator_name"] = people[0][1]
                    row["evaluator_name"] = people[1][1]
                    status = "assignment_consistent"
        row["identity_validation_status"] = status
        statuses[status] += 1
        out.append(row)

    report = {
        "records": len(rows),
        "project_counts": dict(sorted(projects.items())),
        "distinct_user_ids": len(assigned_users),
        "status_counts": dict(sorted(statuses.items())),
        "note": "Assignment consistency does not verify platform account ownership.",
    }
    return out, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    paths = (args.input, args.crosswalk, args.output, args.report)
    if len(set(p.resolve() for p in paths)) != len(paths):
        parser.error("Input and output paths must be distinct")
    enriched, report = resolve(read_rows(args.input), read_rows(args.crosswalk))
    if args.strict and report["status_counts"].get("assignment_consistent", 0) != len(enriched):
        raise ValueError(f"Incomplete assignment consistency: {report['status_counts']}")
    write_rows(args.output, enriched)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
