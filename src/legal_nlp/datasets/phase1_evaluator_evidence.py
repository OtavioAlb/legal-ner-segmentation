"""Evaluator-evidence audit of Phase 1 SEG overlap families, with raw CSV checks.

All input lineage is revalidated against original SHA-256. Votes are recorded
as evidence, never converted into an automatic winning span or gold label.
No private text, reviewer names, or comments are emitted.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from ..ingestion import _load_rows, normalize_review_vote
from ..io.jsonl import read_jsonl
from .phase1_component_source_crosswalk import analyze_component_source_crosswalk
from .segmentation_overlap_components import _balanced_sample


def _verified_source_votes(raw_annotations, ingested):
    """Check each ingested raw row against the actual export and reviewer fields."""
    raw, _ = _load_rows(Path(raw_annotations))
    originals = read_jsonl(Path(ingested) / "annotations.jsonl")
    if len(raw) != len(originals):
        raise ValueError("Raw annotation row count differs from ingestion")
    by_id = {}
    seen_rows = set()
    for ann in originals:
        index = ann["source_row"]
        if type(index) is not int or not 2 <= index <= len(raw) + 1:
            raise ValueError("Invalid source row index")
        if index in seen_rows:
            raise ValueError("Repeated ingestion source row")
        seen_rows.add(index)
        source_row = raw[index - 2]
        expected_source = {
            str(k): None if v is None else str(v) for k, v in source_row.items()
        }
        if ann.get("source_fields") != expected_source:
            raise ValueError(f"Ingested raw source fields differ from export row {index}")
        opinions = ann.get("reviewer_opinions")
        if not isinstance(opinions, dict):
            raise ValueError(f"Reviewer opinions missing in source row {index}")
        keys = {
            k[len("concorda_"):] for k in source_row if k.startswith("concorda_")
        }
        if set(opinions) != keys:
            raise ValueError(f"Reviewer columns differ in row {index}")
        votes = Counter()
        checked = {}
        for name, vote in opinions.items():
            actual = source_row.get("concorda_" + name)
            comment = source_row.get("comentario_" + name)
            if (vote.get("agreement_raw") != actual
                    or vote.get("comment_raw") != comment
                    or vote.get("status") != normalize_review_vote(actual)):
                raise ValueError(f"Reviewer opinion differs from raw export row {index}")
            status = vote["status"]
            votes[status] += 1
            checked[name] = {
                "status": status,
                "comment_present": comment is not None and bool(str(comment).strip()),
            }
        if (votes["agree"] != ann.get("review_agree_count") or
                votes["disagree"] != ann.get("review_disagree_count")):
            raise ValueError(f"Reviewer totals differ from raw export row {index}")
        ann_id = ann["annotation_id"]
        if ann_id in by_id:
            raise ValueError("Duplicate source annotation identifier")
        by_id[ann_id] = {"opinions": checked, "source_row": index}
    if len(seen_rows) != len(raw):
        raise ValueError("Raw source rows not completely represented in ingestion")
    return by_id


def analyze_evaluator_evidence(snapshot, harmonized, taxonomy, raw_texts,
                               raw_annotations, ingested, sanitized,
                               logical, document_spans, *,
                               max_groups=100, max_per_document=4):
    if (type(max_groups) is not int or max_groups < 1 or
            type(max_per_document) is not int or max_per_document < 1):
        raise ValueError("Queue limits must be positive integers")
    # Re-run SHA + complete Phase 1 source lineage, then reconstruct every
    # component; do not reuse a prior JSON report as a source of truth.
    report = analyze_component_source_crosswalk(
        snapshot, harmonized, taxonomy, raw_texts, raw_annotations,
        ingested, sanitized, logical, document_spans, near_tolerance=5,
        max_groups=100000, max_per_document=100000
    )
    verified_votes = _verified_source_votes(raw_annotations, ingested)
    out = []
    summary = Counter()
    all_source_ids = set()
    for group in report["review_queue"]:
        # Family-scoped opaque reviewer keys: no real names, no email.
        reviewers = sorted({
            name for source in group["source_rows"]
            for name in verified_votes[source["annotation_id"]]["opinions"]
        })
        aliases = {name: f"R{i+1}" for i, name in enumerate(reviewers)}
        positive_geometry = defaultdict(set)
        candidates = defaultdict(list)
        for source in group["source_rows"]:
            ann_id = source["annotation_id"]
            if ann_id not in verified_votes or ann_id in all_source_ids:
                raise ValueError("Missing or repeated source annotation in overlap families")
            all_source_ids.add(ann_id)
            vote_map = verified_votes[ann_id]["opinions"]
            votes = Counter(v["status"] for v in vote_map.values())
            candidate_id = source["logical_span_id"]
            geometry = next(
                r for r in group["regions"] if r["region_id"] == candidate_id
            )
            for reviewer, vote in vote_map.items():
                if vote["status"] == "agree":
                    positive_geometry[reviewer].add(candidate_id)
            candidates[candidate_id].append({
                "annotation_id": ann_id,
                "source_row": source["source_row"],
                "selection_status": source["selection_status"],
                "agree": votes["agree"], "disagree": votes["disagree"],
                "not_recorded": votes["not_recorded"],
                "other_not_interpreted": votes["other_not_interpreted"],
                "commented_votes": sum(v["comment_present"] for v in vote_map.values()),
                "votes": [
                    {"reviewer": aliases[reviewer], **vote}
                    for reviewer, vote in sorted(vote_map.items())
                    if vote["status"] != "not_recorded" or vote["comment_present"]
                ],
            })
        conflict_reviewers = {
            aliases[name] for name, candidate_ids in positive_geometry.items()
            if len(candidate_ids) > 1
        }
        candidate_rows = []
        for region in group["regions"]:
            records = candidates[region["region_id"]]
            total = Counter()
            reviewers_who_agreed = set()
            reviewers_who_disagreed = set()
            for record in records:
                total.update({key: record[key] for key in (
                    "agree", "disagree", "not_recorded", "other_not_interpreted"
                )})
                for vote in record["votes"]:
                    if vote["status"] == "agree":
                        reviewers_who_agreed.add(vote["reviewer"])
                    if vote["status"] == "disagree":
                        reviewers_who_disagreed.add(vote["reviewer"])
            candidate_rows.append({
                "logical_span_id": region["region_id"],
                "label": group["label"],
                "start": region["start"], "end": region["end"],
                "source_annotation_count": len(records),
                "vote_totals_source_rows": dict(total),
                "distinct_reviewers_agreeing": len(reviewers_who_agreed),
                "distinct_reviewers_disagreeing": len(reviewers_who_disagreed),
                "reviewer_disagreement_on_same_geometry": bool(
                    reviewers_who_agreed & reviewers_who_disagreed
                ),
                "source_records": records,
            })
        has_negative = any(c["distinct_reviewers_disagreeing"] for c in candidate_rows)
        has_multiple_positive = len([
            c for c in candidate_rows if c["distinct_reviewers_agreeing"] > 0
        ]) > 1
        category = (
            "conflicting_positive_geometries" if conflict_reviewers
            else "multiple_supported_geometries" if has_multiple_positive
            else "negative_votes_present" if has_negative
            else "insufficient_explicit_votes"
        )
        summary[category] += 1
        summary["families"] += 1
        summary["source_annotations"] += len(group["source_rows"])
        summary["families_with_negative_votes"] += bool(has_negative)
        summary["families_with_competing_positive_geometry"] += has_multiple_positive
        summary["families_with_same_reviewer_supporting_alternatives"] += bool(conflict_reviewers)
        out.append({
            "document_id": group["document_id"],
            "label": group["label"],
            "number_of_regions": group["number_of_regions"],
            "source_annotation_count": len(group["source_rows"]),
            "decision": "requires_protocol_aware_adjudication",
            "evidence_category": category,
            "reviewer_aliases_supporting_multiple_geometries": sorted(conflict_reviewers),
            "candidates": candidate_rows,
        })
    if summary["families"] != report["components_total"]:
        raise ValueError("Not all verified overlap components were evaluated")
    if summary["source_annotations"] != report["by_phase"]["phase_1"]["source_annotations_in_components"]:
        raise ValueError("Source annotation coverage mismatch")
    selected = _balanced_sample(
        [{**g, "near_boundary_pairs": 0, "strict_containment_pairs": 0,
          "envelope_characters": 0, "envelope_start": min(c["start"] for c in g["candidates"])}
         for g in out],
        max_groups=max_groups, max_per_document=max_per_document,
    )
    return {
        "schema_version": "1.0.0",
        "mode": "original_source_reviewer_evidence_not_gold",
        "training_ready": False,
        "verified_export_sha256": report["verified_source_manifest_sha256"],
        "components_total": len(out),
        "summary": dict(sorted(summary.items())),
        "review_queue_count": len(selected),
        "review_queue": selected,
        "interpretation": (
            "Agreement and disagreement are votes about source annotations, "
            "not pairwise adjudication. Reviewer aliases are local to each "
            "family. Different geometries receiving positive votes are not "
            "necessarily mutually exclusive. No final span is chosen."
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "harmonized", "raw-texts", "raw-annotations", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--taxonomy", type=Path, default=Path("configs/labels.json"))
    p.add_argument("--ingested", type=Path, default=Path("data/interim/phase_1"))
    p.add_argument("--sanitized", type=Path,
                   default=Path("data/interim/phase_1/sanitized"))
    p.add_argument("--logical", type=Path,
                   default=Path("data/interim/phase_1/logical_spans"))
    p.add_argument("--document-spans", type=Path,
                   default=Path("data/interim/phase_1/document_dataset/document_spans.jsonl"))
    p.add_argument("--max-groups", type=int, default=100)
    p.add_argument("--max-per-document", type=int, default=4)
    args = p.parse_args()
    dest = args.output
    if dest.exists():
        raise FileExistsError("Report already exists")
    if not dest.parent.is_dir():
        raise FileNotFoundError("Report parent directory does not exist")
    result = analyze_evaluator_evidence(
        args.snapshot, args.harmonized, args.taxonomy,
        args.raw_texts, args.raw_annotations, args.ingested,
        args.sanitized, args.logical, args.document_spans,
        max_groups=args.max_groups,
        max_per_document=args.max_per_document
    )
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps({
        "components_total": result["components_total"],
        "summary": result["summary"],
        "review_queue_count": result["review_queue_count"],
        "output": str(dest),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
