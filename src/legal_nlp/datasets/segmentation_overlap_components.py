"""Read-only connected overlap components for SEG regions, stratified by document.

A component joins two regions iff their half-open intervals intersect with
positive length AND labels match; transitive overlaps join the component.
No adjudication, deduplication, span deletion, gold promotion or data splits.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .harmonized_label_support import _validate_and_load, _sha
from .segmentation_provenance_review import _pair_type, _region


def _components(rows):
    """Group same-label overlapping spans in O(n log n) sorting plus scan."""
    by_label = defaultdict(list)
    for row in rows:
        if row["task"] == "SEG":
            by_label[row["label"]].append(row)
    result = []
    for label, items in sorted(by_label.items()):
        items = sorted(items, key=lambda r: (r["start"], r["end"], r["region_id"]))
        group = []
        max_end = -1
        for item in items:
            # Touching intervals do NOT overlap under [start, end).
            if group and item["start"] >= max_end:
                if len(group) > 1:
                    result.append((label, group))
                group = []
                max_end = -1
            group.append(item)
            max_end = max(max_end, item["end"])
        if len(group) > 1:
            result.append((label, group))
    return result


def _summarize(phase, doc_id, label, group, near_tolerance):
    # Pair statistics are computed inside each component so a single region
    # can appear in multiple pairs. No pair count is a count of errors.
    geometry = Counter()
    near = 0
    pairs = 0
    for i, a in enumerate(group):
        for b in group[i + 1:]:
            if max(a["start"], b["start"]) >= min(a["end"], b["end"]):
                continue
            pairs += 1
            geometry[_pair_type(a, b)] += 1
            if (abs(a["start"] - b["start"]) <= near_tolerance
                    and abs(a["end"] - b["end"]) <= near_tolerance):
                near += 1
    starts, ends = [r["start"] for r in group], [r["end"] for r in group]
    return {
        "phase": phase, "document_id": doc_id, "label": label,
        "number_of_regions": len(group),
        "envelope_start": min(starts), "envelope_end": max(ends),
        "envelope_characters": max(ends) - min(starts),
        "overlapping_pairs": pairs,
        "near_boundary_pairs": near,
        "identical_pairs": geometry["identical"],
        "strict_containment_pairs": geometry["strict_containment"],
        "partial_overlap_pairs": geometry["partial_overlap"],
        "distinct_boundaries": len({(r["start"], r["end"]) for r in group}),
        "distinct_lineage_fingerprints": len({
            _region(r)["lineage_sha256"] for r in group
        }),
        "pending_regions": sum(r["status"] == "pending_review" for r in group),
        "source_status_counts": dict(sorted(Counter(
            r["source_status"] for r in group
        ).items())),
        "regions": sorted((_region(r) for r in group),
                          key=lambda r: (r["start"], r["end"], r["region_id"])),
        "review_reason": "inspect_same_label_connected_component",
    }


def _balanced_sample(items, max_groups, max_per_document):
    """Round-robin documents: avoid one acórdão dominating the review queue."""
    by_doc = defaultdict(list)
    for item in items:
        by_doc[item["document_id"]].append(item)
    for value in by_doc.values():
        value.sort(key=lambda x: (-x["near_boundary_pairs"],
                                  -x["strict_containment_pairs"],
                                  -x["number_of_regions"], -x["envelope_characters"],
                                  x["label"], x["envelope_start"]))
    selected, taken = [], Counter()
    docs = sorted(by_doc)
    while len(selected) < max_groups:
        advanced = False
        for doc_id in docs:
            if len(selected) >= max_groups:
                break
            if taken[doc_id] < max_per_document and by_doc[doc_id]:
                selected.append(by_doc[doc_id].pop(0))
                taken[doc_id] += 1
                advanced = True
        if not advanced:
            break
    return selected


def analyze_overlap_components(snapshot, harmonized, taxonomy, *,
                               near_tolerance=5, max_groups=100,
                               max_per_document=3):
    if any(type(x) is not int or x < 0 for x in (
        near_tolerance, max_groups, max_per_document
    )) or max_groups == 0 or max_per_document == 0:
        raise ValueError("Tolerance must be nonnegative; queue limits positive integers")
    docs, rows, _, source_manifest, derived = _validate_and_load(
        snapshot, harmonized, taxonomy
    )
    by_doc = defaultdict(list)
    for row in rows:
        if row["task"] == "SEG":
            by_doc[row["document_id"]].append(row)
    all_groups = []
    for doc in docs:
        for label, group in _components(by_doc[doc["document_id"]]):
            all_groups.append(_summarize(
                doc["phase"], doc["document_id"], label, group, near_tolerance
            ))
    by_phase = {}
    for phase in ("phase_1", "phase_2"):
        selected = [g for g in all_groups if g["phase"] == phase]
        by_phase[phase] = {
            "overlap_components": len(selected),
            "documents_with_overlap_components": len({
                g["document_id"] for g in selected
            }),
            "regions_in_components": sum(g["number_of_regions"] for g in selected),
            "overlapping_pairs_in_components": sum(g["overlapping_pairs"] for g in selected),
            "near_boundary_pairs": sum(g["near_boundary_pairs"] for g in selected),
            "strict_containment_pairs": sum(g["strict_containment_pairs"] for g in selected),
            "partial_overlap_pairs": sum(g["partial_overlap_pairs"] for g in selected),
            "identical_pairs": sum(g["identical_pairs"] for g in selected),
        }
    by_label = []
    for (phase, label) in sorted({(g["phase"], g["label"]) for g in all_groups}):
        subset = [g for g in all_groups if (g["phase"], g["label"]) == (phase, label)]
        by_label.append({
            "phase": phase, "label": label,
            "components": len(subset),
            "documents": len({g["document_id"] for g in subset}),
            "regions": sum(g["number_of_regions"] for g in subset),
            "overlapping_pairs": sum(g["overlapping_pairs"] for g in subset),
            "near_boundary_pairs": sum(g["near_boundary_pairs"] for g in subset),
        })
    selected = _balanced_sample(
        all_groups, max_groups=max_groups, max_per_document=max_per_document
    )
    return {
        "schema_version": "1.0.0",
        "mode": "diagnostic_stratified_component_review_not_gold",
        "training_ready": False,
        "source_corpus_version": source_manifest.get("corpus_version"),
        "harmonized_annotations_sha256": _sha(
            Path(harmonized) / "annotations_harmonized.jsonl"
        ),
        "mapped_vote_spans": derived["mapped_count"],
        "parameters": {
            "near_tolerance": near_tolerance,
            "max_groups": max_groups,
            "max_per_document": max_per_document,
        },
        "by_phase": by_phase,
        "by_label": by_label,
        "all_components_count": len(all_groups),
        "review_queue_count": len(selected),
        "review_queue": selected,
        "methodology": (
            "Connected components formed only from strictly overlapping "
            "same-label half-open spans. Near-boundary pairs require both "
            "start and end to differ by at most tolerance. Counts include "
            "pending candidates and are not adjudicated gold. One component "
            "may generate many overlap pairs. Queue is round-robin by "
            "document; no source excerpts, reviewer identity or corrections."
        ),
    }


def write_component_report(snapshot, harmonized, taxonomy, output, *,
                           near_tolerance=5, max_groups=100,
                           max_per_document=3):
    dest = Path(output)
    if dest.exists():
        raise FileExistsError("Refusing to overwrite component report")
    if not dest.parent.is_dir():
        raise FileNotFoundError("Output directory must exist")
    result = analyze_overlap_components(
        snapshot, harmonized, taxonomy,
        near_tolerance=near_tolerance,
        max_groups=max_groups,
        max_per_document=max_per_document
    )
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                               sort_keys=True) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--harmonized", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path,
                        default=Path("configs/labels.json"))
    parser.add_argument("--near-tolerance", type=int, default=5)
    parser.add_argument("--max-groups", type=int, default=100)
    parser.add_argument("--max-per-document", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = write_component_report(
        args.snapshot, args.harmonized, args.taxonomy, args.output,
        near_tolerance=args.near_tolerance, max_groups=args.max_groups,
        max_per_document=args.max_per_document,
    )
    print(json.dumps({
        "by_phase": report["by_phase"],
        "by_label": report["by_label"],
        "all_components_count": report["all_components_count"],
        "review_queue_count": report["review_queue_count"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
