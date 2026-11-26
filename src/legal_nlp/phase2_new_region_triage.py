"""Read-only Phase 2 triage: new-region evidence and cross-review matching.

This module never adjudicates replacements or adds labels to supervised data.
All output is local; no document text, comments, or person names are written.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .phase2_review_reconciliation import (
    _candidate_relation,
    choice,
    doc_id,
    labeled,
    marked_new,
    read_json,
    regions,
)


def triage(originals, evaluations):
    original = {}
    for task in originals:
        did = doc_id(task)
        if did in original:
            raise ValueError("Duplicate original document ID")
        original[did] = regions(task)

    seen = set()
    by_doc = defaultdict(dict)
    new_records = []
    stats = Counter()
    project_stats = defaultdict(Counter)
    for task in evaluations:
        did, project = doc_id(task), str(task.get("project"))
        if did not in original or project not in {"11", "17"}:
            raise ValueError("Unknown document or evaluation project")
        if (did, project) in seen:
            raise ValueError("Duplicate document/project review")
        seen.add((did, project))
        current = regions(task)
        by_doc[did][project] = current
        baseline = {rid: labeled(region) for rid, region in original[did].items()}
        baseline = {rid: sig for rid, sig in baseline.items() if sig is not None}
        for rid, group in current.items():
            sig = labeled(group)
            if sig is None or rid in baseline:
                continue
            marker = marked_new(group)
            assigned_choice = choice(group) or "not_recorded"
            possible_links = []
            for oid, old_sig in baseline.items():
                existing = current.get(oid)
                state = choice(existing)
                old_region_missing = labeled(existing) is None
                if state not in {"incorreto", "limite impreciso"} and not old_region_missing:
                    continue
                relation = _candidate_relation(old_sig, sig)
                if relation:
                    possible_links.append({
                        "original_region_id": oid,
                        "candidate_relation": relation,
                        "original_region_choice": state or "not_recorded",
                        "original_region_absent": old_region_missing,
                    })
            has_candidate = bool(possible_links)
            if marker:
                classification = ("explicit_new_with_candidate" if has_candidate
                                  else "explicit_new_without_candidate")
            else:
                classification = ("unmarked_with_candidate" if has_candidate
                                  else "unmarked_without_candidate")
            item = {
                "idacordao": did, "project": project, "region_id": rid,
                "start": sig[1], "end": sig[2], "labels": list(sig[0]),
                "choice": assigned_choice, "explicit_new_comment": marker,
                "classification": classification,
                "candidate_count": len(possible_links),
                "candidate_links": possible_links,
                "resolution_status": "unresolved_no_automatic_action",
            }
            new_records.append(item)
            stats["new_regions"] += 1
            stats[classification] += 1
            stats["candidate_links"] += len(possible_links)
            project_stats[project]["new_regions"] += 1
            project_stats[project][classification] += 1
            project_stats[project]["choice:" + assigned_choice] += 1
            if len(possible_links) > 1:
                stats["new_regions_multiple_candidates"] += 1

    # Only exact label+offset signatures can be used for cross-review matching.
    # Nonunique matches are flagged rather than paired arbitrarily.
    shared = []
    ambiguous = []
    stats["documents_with_two_reviews"] = sum(
        set(review_map) == {"11", "17"} for review_map in by_doc.values()
    )
    for did, review_map in by_doc.items():
        if set(review_map) != {"11", "17"}:
            continue
        original_ids = {
            rid for rid, group in original[did].items() if labeled(group) is not None
        }
        indexed = {}
        for project in ("11", "17"):
            idx = defaultdict(list)
            for rid, group in review_map[project].items():
                signature = labeled(group)
                if rid in original_ids or signature is None:
                    continue
                idx[signature].append(rid)
            indexed[project] = idx
        for signature in sorted(set(indexed["11"]) & set(indexed["17"])):
            left, right = indexed["11"][signature], indexed["17"][signature]
            result = {
                "idacordao": did,
                "labels": list(signature[0]),
                "start": signature[1], "end": signature[2],
                "project_11_region_ids": sorted(left),
                "project_17_region_ids": sorted(right),
                "status": "exact_new_region_signature_match",
            }
            if len(left) == len(right) == 1:
                shared.append(result)
            else:
                result["status"] = "ambiguous_duplicate_signature"
                ambiguous.append(result)
        stats["new_regions_project_11_in_paired_docs"] += sum(
            len(ids) for ids in indexed["11"].values()
        )
        stats["new_regions_project_17_in_paired_docs"] += sum(
            len(ids) for ids in indexed["17"].values()
        )

    stats["exact_cross_review_new_region_pairs"] = len(shared)
    stats["ambiguous_cross_review_new_region_signatures"] = len(ambiguous)
    report = {
        "schema_version": "1.0",
        "evaluations": len(evaluations),
        "original_documents": len(originals),
        "counts": dict(sorted(stats.items())),
        "by_project": {key: dict(sorted(value.items()))
                       for key, value in sorted(project_stats.items())},
        "policy": (
            "Candidate overlap is not proof of a correction; explicit new markers "
            "are reviewer evidence; exact signature matches are not adjudication."
        ),
    }
    return report, new_records, shared, ambiguous


def _write_jsonl(path, items):
    with path.open("w", encoding="utf-8") as stream:
        for item in items:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def run(original_path: Path, evaluated_path: Path, output: Path):
    if original_path.resolve() == evaluated_path.resolve():
        raise ValueError("Original and evaluation inputs must differ")
    report, candidates, shared, ambiguous = triage(
        read_json(original_path), read_json(evaluated_path)
    )
    paths = [
        output / "triage_summary.json",
        output / "new_regions_triage.jsonl",
        output / "new_regions_exact_crossreview.jsonl",
        output / "ambiguous_crossreview_signatures.jsonl",
    ]
    if any(path.resolve() in {original_path.resolve(), evaluated_path.resolve()}
           for path in paths):
        raise ValueError("Output would overwrite an input")
    output.mkdir(parents=True, exist_ok=True)
    paths[0].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    for path, rows in zip(paths[1:], (candidates, shared, ambiguous)):
        _write_jsonl(path, rows)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--evaluations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.original, args.evaluations, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
