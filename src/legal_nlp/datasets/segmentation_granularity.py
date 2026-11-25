"""Read-only segmentation geometry audit on the harmonized diagnostic view.

Counts consolidated + pending as potential evidence; reports differences in
span length, fragmentation, union coverage, gaps and overlaps by phase/label.
No inferred error, gold promotion, manual corrections, splits or source excerpts.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .harmonized_label_support import _validate_and_load, _sha
from .phase_coverage_audit import _covered


def _stats(numbers):
    ordered = sorted(numbers)
    if not ordered:
        return {"n": 0, "min": None, "median": None, "mean": None,
                "p90": None, "max": None}
    ix = .9 * (len(ordered) - 1)
    lo = int(ix)
    p90 = ordered[lo] + (ordered[min(lo + 1, len(ordered) - 1)] - ordered[lo]) * (ix - lo)
    return {"n": len(ordered), "min": ordered[0],
            "median": statistics.median(ordered),
            "mean": statistics.mean(ordered), "p90": p90,
            "max": ordered[-1]}


def _union_components(intervals):
    """Number of connected components in the closed union of half-open spans.

    Touching intervals become one component; gaps are positive characters.
    """
    components = 0
    end_seen = -1
    for start, end in sorted(intervals):
        if start > end_seen:
            components += 1
        end_seen = max(end_seen, end)
    return components


def _pair_overlap_metrics(rows):
    """Cross-region overlap; nested/identical cases not double-counted."""
    ordered = sorted(rows, key=lambda r: (r["start"], r["end"]))
    overlaps, same_label, cross_label, fully_nested, identical = 0, 0, 0, 0, 0
    for i, current in enumerate(ordered):
        for nxt in ordered[i + 1:]:
            if nxt["start"] >= current["end"]:
                break
            if nxt["end"] <= current["start"]:
                continue
            overlaps += 1
            same_label += current["label"] == nxt["label"]
            cross_label += current["label"] != nxt["label"]
            fully_nested += (current["start"] <= nxt["start"]
                             and nxt["end"] <= current["end"])
            identical += (current["start"] == nxt["start"]
                          and current["end"] == nxt["end"])
    return {
        "overlapping_pairs": overlaps,
        "same_label_pairs": same_label,
        "cross_label_pairs": cross_label,
        "contained_pairs": fully_nested,
        "identical_boundary_pairs": identical,
    }


def analyze_granularity(snapshot, harmonized, taxonomy):
    docs, annotations, labels, source_manifest, derived = _validate_and_load(
        snapshot, harmonized, taxonomy
    )
    all_seg_labels = [x for x in labels if x.startswith("SEG_")]
    docs_by_phase = defaultdict(list)
    doc_lookup = {}
    for d in docs:
        docs_by_phase[d["phase"]].append(d)
        doc_lookup[d["document_id"]] = d
    rows_by_doc = defaultdict(list)
    for row in annotations:
        if row["task"] == "SEG":
            rows_by_doc[row["document_id"]].append(row)

    # Inspect both statuses together but report them separately.
    report_by_phase = {}
    per_document = []
    per_label = []
    for phase in ("phase_1", "phase_2"):
        group = docs_by_phase[phase]
        chars_total = sum(len(d["text"]) for d in group)
        span_lengths = []
        union_total = 0
        num_seg = 0
        num_components = 0
        overlap_totals = Counter()
        for d in group:
            rows = rows_by_doc[d["document_id"]]
            intervals = [(r["start"], r["end"]) for r in rows]
            union = _covered(intervals)
            comp = _union_components(intervals)
            overlap = _pair_overlap_metrics(rows)
            for key, value in overlap.items():
                overlap_totals[key] += value
            union_total += union
            num_seg += len(rows)
            num_components += comp
            span_lengths.extend(r["end"] - r["start"] for r in rows)
            per_document.append({
                "phase": phase,
                "document_id": d["document_id"],
                "characters": len(d["text"]),
                "seg_potential": len(rows),
                "seg_pending": sum(r["status"] == "pending_review" for r in rows),
                "seg_covered_characters": union,
                "seg_coverage_fraction": union / len(d["text"]),
                "seg_uncovered_characters": len(d["text"]) - union,
                "seg_union_components": comp,
                "seg_overlapping_pairs": overlap["overlapping_pairs"],
                "seg_cross_label_overlapping_pairs": overlap["cross_label_pairs"],
            })
        report_by_phase[phase] = {
            "documents": len(group), "characters": chars_total,
            "seg_potential": num_seg,
            "seg_consolidated": sum(
                r["status"] == "consolidated"
                for d in group for r in rows_by_doc[d["document_id"]]
            ),
            "seg_pending": sum(
                r["status"] == "pending_review"
                for d in group for r in rows_by_doc[d["document_id"]]
            ),
            "spans_per_document": _stats([
                len(rows_by_doc[d["document_id"]]) for d in group
            ]),
            "span_characters": _stats(span_lengths),
            "total_union_covered_characters": union_total,
            "coverage_fraction": union_total / chars_total if chars_total else None,
            "union_components": num_components,
            "pairwise_overlaps": dict(sorted(overlap_totals.items())),
        }

    for label in all_seg_labels:
        item = {"label": label}
        for phase in ("phase_1", "phase_2"):
            group = docs_by_phase[phase]
            n_docs = len(group)
            all_rows = []
            lengths_per_doc = []
            coverage_sum = 0
            connected = 0
            within_label_overlap_pairs = 0
            document_support = 0
            for doc in group:
                rows = [r for r in rows_by_doc[doc["document_id"]] if r["label"] == label]
                all_rows.extend(rows)
                lengths_per_doc.append(len(rows))
                if rows:
                    document_support += 1
                intervals = [(r["start"], r["end"]) for r in rows]
                coverage_sum += _covered(intervals)
                connected += _union_components(intervals)
                within_label_overlap_pairs += _pair_overlap_metrics(rows)["overlapping_pairs"]
            chars = sum(len(d["text"]) for d in group)
            item[phase] = {
                "occurrences": len(all_rows),
                "consolidated": sum(r["status"] == "consolidated" for r in all_rows),
                "pending": sum(r["status"] == "pending_review" for r in all_rows),
                "documents_with_support": document_support,
                "spans_per_all_documents": len(all_rows) / n_docs if n_docs else None,
                "spans_per_supporting_document": (
                    len(all_rows) / document_support if document_support else None
                ),
                "spans_per_document_distribution": _stats(lengths_per_doc),
                "span_characters": _stats([r["end"] - r["start"] for r in all_rows]),
                "union_covered_characters": coverage_sum,
                "coverage_fraction_of_phase_characters": (
                    coverage_sum / chars if chars else None
                ),
                "union_components": connected,
                "within_label_overlapping_pairs": within_label_overlap_pairs,
            }
        p1 = item["phase_1"]
        p2 = item["phase_2"]
        item["median_span_length_ratio_phase2_over_phase1"] = (
            p2["span_characters"]["median"] / p1["span_characters"]["median"]
            if p1["occurrences"] and p2["occurrences"] else None
        )
        item["mean_spans_per_supporting_document_ratio_phase2_over_phase1"] = (
            p2["spans_per_supporting_document"] / p1["spans_per_supporting_document"]
            if p1["documents_with_support"] and p2["documents_with_support"] else None
        )
        per_label.append(item)

    return {
        "schema_version": "1.0.0",
        "mode": "segmentation_geometry_diagnostic_with_pending_not_gold",
        "training_ready": False,
        "source_corpus_version": source_manifest.get("corpus_version"),
        "mapped_vote_spans": derived.get("mapped_count"),
        "harmonization_annotations_sha256": _sha(
            Path(harmonized) / "annotations_harmonized.jsonl"
        ),
        "by_phase": report_by_phase,
        "by_label": per_label,
        "by_document": sorted(per_document, key=lambda d: d["document_id"]),
        "quarantine_normalized_rows_excluded": source_manifest.get(
            "quarantine_normalized_rows", 0
        ),
        "interpretation": (
            "Counts consolidated and pending candidate SEG spans. Span lengths, "
            "coverage, number of blocks and overlaps describe observed geometry "
            "but do not prove omitted annotations or an invalid segmentation "
            "protocol. Label-specific coverage may overlap and exceed overall "
            "coverage if summed. Converted vote-result spans are ENT and not "
            "included in SEG here."
        ),
    }


def write_granularity_report(snapshot, harmonized, taxonomy, output):
    target = Path(output)
    if target.exists():
        raise FileExistsError("Refusing to overwrite existing diagnostic report")
    if not target.parent.is_dir():
        raise FileNotFoundError("Output parent must exist")
    result = analyze_granularity(snapshot, harmonized, taxonomy)
    target.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--harmonized", required=True, type=Path)
    parser.add_argument("--taxonomy", default=Path("configs/labels.json"), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = write_granularity_report(
        args.snapshot, args.harmonized, args.taxonomy, args.output
    )
    print(json.dumps({
        "mode": result["mode"],
        "by_phase": result["by_phase"],
        "labels_reported": len(result["by_label"]),
        "documents_reported": len(result["by_document"]),
        "quarantine_normalized_rows_excluded": result[
            "quarantine_normalized_rows_excluded"
        ],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
