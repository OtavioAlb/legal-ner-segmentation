"""Read-only review queues for segmentation overlap provenance and long gaps.

All regions are validated against the original snapshot, immutable hashes
and the harmonized view. No judicial excerpts, annotations or reviewer PII
are exported. Queue priority is diagnostic, not an error probability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from .harmonized_label_support import _validate_and_load, _sha
from .segmentation_overlap_gaps import _pairs, _uncovered_intervals


def _provenance_digest(row):
    """Stable lineage fingerprint without exposing source payload or PII."""
    data = json.dumps(row["provenance"], ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _region(row):
    return {
        "region_id": row["region_id"],
        "label": row["label"],
        "source_label": row["source_label"],
        "start": row["start"], "end": row["end"],
        "length": row["end"] - row["start"],
        "status": row["status"],
        "source_status": row["source_status"],
        "lineage_sha256": _provenance_digest(row),
    }


def _pair_type(a, b):
    if (a["start"], a["end"]) == (b["start"], b["end"]):
        return "identical"
    if ((a["start"] <= b["start"] and b["end"] <= a["end"])
            or (b["start"] <= a["start"] and a["end"] <= b["end"])):
        return "strict_containment"
    return "partial_overlap"


def build_review_queues(snapshot, harmonized, taxonomy, *,
                        min_gap=150, top_pairs=100, top_gaps=100):
    if any(type(n) is not int or n < 1 for n in (min_gap, top_pairs, top_gaps)):
        raise ValueError("Threshold and queue limits must be positive integers")
    docs, rows, _, source_manifest, derived = _validate_and_load(
        snapshot, harmonized, taxonomy
    )
    group = defaultdict(list)
    for row in rows:
        if row["task"] == "SEG":
            group[row["document_id"]].append(row)
    pair_queue = []
    gap_queue = []
    category_counts = Counter()
    phase_counts = Counter()
    for doc in docs:
        phase, doc_id = doc["phase"], doc["document_id"]
        spans = group[doc_id]
        for a, b, overlap in _pairs(spans):
            same = a["label"] == b["label"]
            geometry = _pair_type(a, b)
            category = ("same_label" if same else "cross_label", geometry)
            category_counts[(phase, *category)] += 1
            phase_counts[(phase, "all_pairs")] += 1
            if same:
                phase_counts[(phase, "same_label_pairs")] += 1
            else:
                phase_counts[(phase, "cross_label_pairs")] += 1
            if not (a["status"] == b["status"] == "consolidated"):
                phase_counts[(phase, "at_least_one_pending_pairs")] += 1
            # Queue only; never infer duplications or corrections from geometry.
            pair_queue.append({
                "phase": phase, "document_id": doc_id,
                "category": category[0], "geometry": geometry,
                "overlap_characters": overlap,
                "overlap_fraction_smaller_span": overlap / min(
                    a["end"] - a["start"], b["end"] - b["start"]
                ),
                "review_reason": (
                    "inspect_same_label_overlap" if same
                    else "inspect_cross_label_semantics"
                ),
                "pair_has_pending": (
                    a["status"] != "consolidated" or b["status"] != "consolidated"
                ),
                "region_a": _region(a), "region_b": _region(b),
            })
        for start, end in _uncovered_intervals(len(doc["text"]), spans):
            gap_length = end - start
            phase_counts[(phase, "all_gaps")] += 1
            if gap_length >= min_gap:
                phase_counts[(phase, "long_gaps")] += 1
                gap_queue.append({
                    "phase": phase, "document_id": doc_id,
                    "start": start, "end": end,
                    "characters": gap_length,
                    "relative_start": start / len(doc["text"]),
                    "relative_end": end / len(doc["text"]),
                    "review_reason": "inspect_unlabeled_interval",
                    "seg_spans_in_document": len(spans),
                    "seg_pending_in_document": sum(
                        s["status"] == "pending_review" for s in spans
                    ),
                })

    pair_queue.sort(key=lambda x: (
        x["phase"] != "phase_1", x["category"] != "same_label",
        x["geometry"] == "partial_overlap",
        -x["overlap_fraction_smaller_span"],
        -x["overlap_characters"],
        x["document_id"], x["region_a"]["start"], x["region_b"]["start"]
    ))
    gap_queue.sort(key=lambda x: (
        x["phase"] != "phase_2", -x["characters"], x["document_id"], x["start"]
    ))
    return {
        "schema_version": "1.0.0",
        "mode": "read_only_review_queue_not_gold",
        "training_ready": False,
        "source_corpus_version": source_manifest.get("corpus_version"),
        "harmonized_annotations_sha256": _sha(
            Path(harmonized) / "annotations_harmonized.jsonl"
        ),
        "mapped_vote_spans": derived["mapped_count"],
        "parameters": {
            "min_gap": min_gap, "top_pairs": top_pairs, "top_gaps": top_gaps
        },
        "overlap_category_counts": [
            {"phase": phase, "category": category, "geometry": geometry,
             "count": count}
            for (phase, category, geometry), count in sorted(category_counts.items())
        ],
        "phase_metrics": [
            {"phase": phase, **{
                key: phase_counts[(phase, key)]
                for key in ("all_pairs", "same_label_pairs",
                            "cross_label_pairs", "at_least_one_pending_pairs",
                            "all_gaps", "long_gaps")
            }} for phase in ("phase_1", "phase_2")
        ],
        "overlap_review_queue": pair_queue[:top_pairs],
        "gap_review_queue": gap_queue[:top_gaps],
        "overlap_candidates_total": len(pair_queue),
        "gap_candidates_above_threshold_total": len(gap_queue),
        "quarantine_record_count": source_manifest.get("quarantine_record_count", 0),
        "limitations": (
            "A source status of consolidated is not formal gold. Same-label "
            "overlap is not proof of duplication, nested regions may be valid, "
            "and uncovered intervals are not automatically omissions. The "
            "queue emits only IDs, offsets, labels, and opaque provenance "
            "fingerprints; original text and reviewer identities are excluded."
        ),
    }


def write_review_queues(snapshot, harmonized, taxonomy, output, *,
                        min_gap=150, top_pairs=100, top_gaps=100):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Refusing to overwrite report")
    if not output.parent.is_dir():
        raise FileNotFoundError("Output directory must already exist")
    data = build_review_queues(snapshot, harmonized, taxonomy,
                               min_gap=min_gap, top_pairs=top_pairs,
                               top_gaps=top_gaps)
    output.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--harmonized", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/labels.json"))
    parser.add_argument("--min-gap", type=int, default=150)
    parser.add_argument("--top-pairs", type=int, default=100)
    parser.add_argument("--top-gaps", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = write_review_queues(
        args.snapshot, args.harmonized, args.taxonomy, args.output,
        min_gap=args.min_gap, top_pairs=args.top_pairs, top_gaps=args.top_gaps
    )
    print(json.dumps({
        "mode": result["mode"],
        "phase_metrics": result["phase_metrics"],
        "overlap_category_counts": result["overlap_category_counts"],
        "overlap_candidates_total": result["overlap_candidates_total"],
        "gap_candidates_above_threshold_total": result["gap_candidates_above_threshold_total"],
        "overlap_queue_size": len(result["overlap_review_queue"]),
        "gap_queue_size": len(result["gap_review_queue"]),
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
