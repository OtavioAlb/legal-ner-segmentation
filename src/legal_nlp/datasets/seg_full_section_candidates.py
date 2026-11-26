"""Read-only triage of full-section candidates in verified Phase 1 SEG families.

Full-section is an annotation-policy hypothesis, NOT a property derivable
from span length. The module never elects, merges or removes a span.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .phase1_evaluator_evidence import analyze_evaluator_evidence


def _relation(a, b, tolerance):
    """Relation between non-identical logical spans (half-open offsets)."""
    x0, x1 = a["start"], a["end"]
    y0, y1 = b["start"], b["end"]
    if (x0, x1) == (y0, y1):
        return "identical"
    if abs(x0-y0) <= tolerance and abs(x1-y1) <= tolerance:
        return "near_equal"
    if x0 <= y0 and y1 <= x1 or y0 <= x0 and x1 <= y1:
        return "containment"
    if max(x0, y0) < min(x1, y1):
        return "partial_overlap"
    return "disjoint"


def triage_families(evidence, *, near_tolerance=5):
    """Classify relationships between positively evaluated geometries.

    'Full-section candidate' means merely a non-dominated *interval* with
    positive evaluator support; never a confirmed correct section.
    """
    if type(near_tolerance) is not int or near_tolerance < 0:
        raise ValueError("near_tolerance must be a nonnegative integer")
    if evidence.get("training_ready") is not False:
        raise ValueError("Requires non-gold verified evaluator evidence")
    groups = evidence.get("review_queue")
    if not isinstance(groups, list) or len(groups) != evidence.get("components_total"):
        raise ValueError("All verified overlap families must be supplied")
    summary = Counter()
    processed = []
    for group in groups:
        candidates = group["candidates"]
        if len(candidates) != group["number_of_regions"]:
            raise ValueError("Missing candidate geometry")
        ids = [c["logical_span_id"] for c in candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("Repeated logical span")
        geometries = {(c["start"], c["end"]) for c in candidates}
        if len(geometries) != len(candidates):
            raise ValueError("Repeated logical span geometry")
        supported = [c for c in candidates if c["distinct_reviewers_agreeing"] > 0]
        if not supported:
            status = "no_positive_evaluator_support"
        elif len(supported) == 1:
            status = "single_supported_geometry"
        else:
            status = "multiple_supported_geometries"
        pair_counts = Counter()
        relationships = []
        for i, a in enumerate(supported):
            for b in supported[i+1:]:
                relation = _relation(a, b, near_tolerance)
                pair_counts[relation] += 1
                relationships.append({
                    "region_a": a["logical_span_id"],
                    "region_b": b["logical_span_id"],
                    "relation": relation,
                })
        # Maximal by exact containment, not 'longest wins': if two
        # intervals overlap partially, both remain candidates.
        outer = []
        for candidate in supported:
            contained = any(
                other["logical_span_id"] != candidate["logical_span_id"]
                and other["start"] <= candidate["start"]
                and candidate["end"] <= other["end"]
                for other in supported
            )
            if not contained:
                outer.append(candidate["logical_span_id"])
        # Record all supported spans, including nested alternatives. An
        # outer span is only a review priority, not a validated section.
        candidates_out = []
        for candidate in candidates:
            notes = []
            if candidate["logical_span_id"] in outer:
                notes.append("maximal_supported_interval_not_verified_complete_section")
            if candidate["distinct_reviewers_disagreeing"]:
                notes.append("negative_votes_require_contextual_review")
            if any(
                _relation(candidate, other, near_tolerance) == "near_equal"
                for other in candidates
                if other["logical_span_id"] != candidate["logical_span_id"]
            ):
                notes.append("near_equal_boundaries_require_canonical_offset_review")
            candidates_out.append({
                "logical_span_id": candidate["logical_span_id"],
                "start": candidate["start"], "end": candidate["end"],
                "length": candidate["end"] - candidate["start"],
                "distinct_reviewers_agreeing": candidate["distinct_reviewers_agreeing"],
                "distinct_reviewers_disagreeing": candidate["distinct_reviewers_disagreeing"],
                "source_annotation_count": candidate["source_annotation_count"],
                "is_maximal_supported_interval": candidate["logical_span_id"] in outer,
                "review_notes": notes,
            })
        requires_review = (
            len(supported) != 1
            or bool(pair_counts["containment"] + pair_counts["partial_overlap"]
                    + pair_counts["near_equal"])
            or any(c["distinct_reviewers_disagreeing"] for c in candidates)
        )
        summary["families"] += 1
        summary[status] += 1
        summary["families_with_containment_among_positives"] += bool(pair_counts["containment"])
        summary["families_with_partial_overlap_among_positives"] += bool(pair_counts["partial_overlap"])
        summary["families_with_near_equal_positives"] += bool(pair_counts["near_equal"])
        summary["families_requiring_manual_review"] += requires_review
        summary["maximal_supported_intervals"] += len(outer)
        processed.append({
            "document_id": group["document_id"],
            "label": group["label"],
            "source_annotation_count": group["source_annotation_count"],
            "status": status,
            "requires_manual_review": requires_review,
            "pair_relations_among_positively_evaluated": dict(sorted(pair_counts.items())),
            "maximal_supported_logical_ids": outer,
            "candidates": candidates_out,
            "positive_geometry_relationships": relationships,
        })
    return {
        "schema_version": "1.0.0",
        "mode": "full_section_candidate_triage_not_gold",
        "policy": "SEG full-section targets; preserve nested semantic segments until label-specific policy is approved",
        "training_ready": False,
        "verified_export_sha256": evidence.get("verified_export_sha256"),
        "summary": dict(sorted(summary.items())),
        "families": processed,
        "limitations": (
            "A maximal interval is not proven to be a complete section. "
            "Same-label overlap components exclude standalone spans; cross-label "
            "overlaps and uncovered gaps require separate coverage analysis. "
            "No winner, canonical boundary, merge, adjudication or training target "
            "is determined automatically."
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "harmonized", "raw-texts", "raw-annotations", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--taxonomy", type=Path, default=Path("configs/labels.json"))
    p.add_argument("--ingested", type=Path, default=Path("data/interim/phase_1"))
    p.add_argument("--sanitized", type=Path, default=Path("data/interim/phase_1/sanitized"))
    p.add_argument("--logical", type=Path, default=Path("data/interim/phase_1/logical_spans"))
    p.add_argument("--document-spans", type=Path,
                   default=Path("data/interim/phase_1/document_dataset/document_spans.jsonl"))
    p.add_argument("--near-tolerance", type=int, default=5)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError("Candidate triage report already exists")
    if not a.output.parent.is_dir():
        raise FileNotFoundError("Output directory does not exist")
    evidence = analyze_evaluator_evidence(
        a.snapshot, a.harmonized, a.taxonomy, a.raw_texts, a.raw_annotations,
        a.ingested, a.sanitized, a.logical, a.document_spans,
        max_groups=100000, max_per_document=100000
    )
    result = triage_families(evidence, near_tolerance=a.near_tolerance)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({
        "summary": result["summary"],
        "output": str(a.output),
        "training_ready": result["training_ready"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
