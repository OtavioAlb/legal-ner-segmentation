"""Read-only segmentation overlap and uncovered-interval audit.

Uses only the source-hash-verified, vote-harmonized diagnostic view.
Pair counts are not error counts; gaps are not automatically omissions.
No source excerpts, auto-adjudication, splits, or gold promotion.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .harmonized_label_support import _validate_and_load, _sha


def _uncovered_intervals(length, spans):
    """Return maximal uncovered half-open ranges, merging touching spans."""
    cursor = 0
    gaps = []
    for start, end in sorted((r["start"], r["end"]) for r in spans):
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < length:
        gaps.append((cursor, length))
    return gaps


def _pairs(rows):
    """Yields each positive-overlap pair once per document."""
    ordered = sorted(rows, key=lambda x: (x["start"], x["end"], x["region_id"]))
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if b["start"] >= a["end"]:
                break
            overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
            if overlap > 0:
                yield a, b, overlap


def analyze_overlap_gaps(snapshot, harmonized, taxonomy, *, top_n=30, min_gap=150):
    if type(top_n) is not int or top_n < 1 or type(min_gap) is not int or min_gap < 1:
        raise ValueError("top_n and min_gap must be positive integers")
    docs, rows, labels, source_manifest, derived = _validate_and_load(
        snapshot, harmonized, taxonomy
    )
    by_doc = defaultdict(list)
    docmap = {d["document_id"]: d for d in docs}
    for row in rows:
        if row["task"] == "SEG":
            by_doc[row["document_id"]].append(row)

    matrix = Counter()
    pair_detail = defaultdict(lambda: Counter())
    geometry = Counter()
    gap_detail = []
    by_document = []
    by_phase = defaultdict(lambda: Counter())
    within_label = Counter()
    for doc in docs:
        doc_id, phase, length = doc["document_id"], doc["phase"], len(doc["text"])
        spans = by_doc[doc_id]
        gaps = _uncovered_intervals(length, spans)
        uncovered = sum(e - s for s, e in gaps)
        positive = [dict(
            document_id=doc_id, phase=phase, start=s, end=e,
            characters=e - s, relative_start=s / length, relative_end=e / length
        ) for s, e in gaps if e - s >= min_gap]
        gap_detail.extend(positive)
        doc_overlaps = 0
        doc_cross = 0
        doc_same = 0
        for a, b, overlap in _pairs(spans):
            doc_overlaps += 1
            label_a, label_b = sorted((a["label"], b["label"]))
            key = (phase, label_a, label_b)
            matrix[key] += 1
            pair_detail[key]["overlap_characters_sum"] += overlap
            pair_detail[key]["documents"].add(doc_id) if False else None
            both_consolidated = (a["status"] == "consolidated" and
                                 b["status"] == "consolidated")
            pair_detail[key]["both_consolidated"] += both_consolidated
            pair_detail[key]["at_least_one_pending"] += not both_consolidated
            same = a["label"] == b["label"]
            doc_same += same
            doc_cross += not same
            if same:
                within_label[(phase, a["label"])] += 1
            identical = a["start"] == b["start"] and a["end"] == b["end"]
            nested = (a["start"] <= b["start"] and b["end"] <= a["end"]) or (
                b["start"] <= a["start"] and a["end"] <= b["end"])
            geometry[(phase, "identical")] += identical
            geometry[(phase, "strict_containment")] += nested and not identical
            geometry[(phase, "partial_overlap")] += not nested
        by_document.append({
            "phase": phase, "document_id": doc_id,
            "characters": length, "seg_spans": len(spans),
            "pending_seg_spans": sum(x["status"] == "pending_review" for x in spans),
            "uncovered_characters": uncovered,
            "uncovered_fraction": uncovered / length,
            "uncovered_gaps_total": len(gaps),
            "gaps_at_least_threshold": len(positive),
            "longest_uncovered_gap": max((e - s for s, e in gaps), default=0),
            "overlapping_pairs": doc_overlaps,
            "same_label_pairs": doc_same,
            "cross_label_pairs": doc_cross,
        })
        by_phase[phase]["documents"] += 1
        by_phase[phase]["characters"] += length
        by_phase[phase]["seg_spans"] += len(spans)
        by_phase[phase]["uncovered_characters"] += uncovered
        by_phase[phase]["uncovered_intervals"] += len(gaps)
        by_phase[phase]["gaps_at_least_threshold"] += len(positive)
        by_phase[phase]["overlapping_pairs"] += doc_overlaps
        by_phase[phase]["same_label_pairs"] += doc_same
        by_phase[phase]["cross_label_pairs"] += doc_cross

    # Get unique document counts per label-pair using a separate, bounded
    # traversal. A single document can have many overlapping region pairs.
    pair_docs = defaultdict(set)
    for doc in docs:
        for a, b, _ in _pairs(by_doc[doc["document_id"]]):
            label_a, label_b = sorted((a["label"], b["label"]))
            pair_docs[(doc["phase"], label_a, label_b)].add(doc["document_id"])
    matrix_rows = [{
        "phase": phase, "label_a": label_a, "label_b": label_b,
        "same_label": label_a == label_b,
        "pair_count": count,
        "documents_with_pair": len(pair_docs[(phase, label_a, label_b)]),
        "overlap_characters_pairwise_sum": pair_detail[
            (phase, label_a, label_b)]["overlap_characters_sum"],
        "both_consolidated": pair_detail[
            (phase, label_a, label_b)]["both_consolidated"],
        "at_least_one_pending": pair_detail[
            (phase, label_a, label_b)]["at_least_one_pending"],
    } for (phase, label_a, label_b), count in sorted(matrix.items())]
    phase_summary = {}
    for phase in ("phase_1", "phase_2"):
        d = dict(by_phase[phase])
        d["coverage_fraction"] = (
            1 - d["uncovered_characters"] / d["characters"]
            if d.get("characters") else None
        )
        d["geometry_pairs"] = {
            kind: geometry[(phase, kind)]
            for kind in ("identical", "strict_containment", "partial_overlap")
        }
        phase_summary[phase] = d
    gap_detail.sort(key=lambda x: (-x["characters"], x["phase"],
                                   x["document_id"], x["start"]))
    return {
        "schema_version": "1.0.0",
        "mode": "diagnostic_potential_not_gold",
        "training_ready": False,
        "source_corpus_version": source_manifest.get("corpus_version"),
        "source_view_annotations_sha256": _sha(
            Path(harmonized) / "annotations_harmonized.jsonl"
        ),
        "mapped_vote_spans": derived["mapped_count"],
        "gap_minimum_characters": min_gap,
        "by_phase": phase_summary,
        "overlap_matrix": matrix_rows,
        "within_label_overlap_counts": [
            {"phase": phase, "label": label, "pair_count": count}
            for (phase, label), count in sorted(within_label.items())
        ],
        "top_uncovered_intervals": gap_detail[:top_n],
        "all_document_metrics": sorted(by_document,
                                       key=lambda x: (x["phase"], x["document_id"])),
        "quarantine_record_count": source_manifest.get("quarantine_record_count", 0),
        "interpretation": (
            "Overlaps count unordered pairs of distinct regions, not errors or "
            "unique intersecting characters. Pairwise character sums can double "
            "count. Uncovered intervals are not by themselves missing "
            "annotations. Consolidated and pending are potential candidates; "
            "mapped vote result ENT spans are not SEG. No judicial text is emitted."
        ),
    }


def write_overlap_gaps_report(snapshot, harmonized, taxonomy, output, *,
                              top_n=30, min_gap=150):
    path = Path(output)
    if path.exists():
        raise FileExistsError("Refusing to overwrite an existing report")
    if not path.parent.is_dir():
        raise FileNotFoundError("Output parent directory does not exist")
    result = analyze_overlap_gaps(snapshot, harmonized, taxonomy,
                                  top_n=top_n, min_gap=min_gap)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                               sort_keys=True) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--harmonized", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/labels.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--min-gap", type=int, default=150)
    args = parser.parse_args()
    result = write_overlap_gaps_report(
        args.snapshot, args.harmonized, args.taxonomy, args.output,
        top_n=args.top_n, min_gap=args.min_gap,
    )
    print(json.dumps({
        "by_phase": result["by_phase"],
        "overlap_pair_categories": len(result["overlap_matrix"]),
        "top_uncovered_intervals": len(result["top_uncovered_intervals"]),
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
