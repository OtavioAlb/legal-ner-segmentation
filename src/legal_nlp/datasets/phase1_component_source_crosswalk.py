"""Crosswalk ALL Phase 1 same-label SEG overlap families to verified source rows.

Re-verifies raw CSV checksums and every lineage layer, rather than trusting
a previously written report. Outputs no judicial text or reviewer PII.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .phase1_source_lineage import audit_phase1_lineage
from .segmentation_overlap_components import _components, _summarize, _balanced_sample


def analyze_component_source_crosswalk(
    snapshot, harmonized, taxonomy, raw_texts, raw_annotations, ingested,
    sanitized, logical, document_spans, *, near_tolerance=5,
    max_groups=100, max_per_document=4
):
    if (type(near_tolerance) is not int or near_tolerance < 0 or
            type(max_groups) is not int or max_groups < 1 or
            type(max_per_document) is not int or max_per_document < 1):
        raise ValueError("Invalid queue limit or offset tolerance")
    # A successful call validates both original raw exports and the full lineage.
    verified = audit_phase1_lineage(
        snapshot, harmonized, taxonomy, raw_texts, raw_annotations,
        ingested, sanitized, logical, document_spans
    )
    from ..io.jsonl import read_jsonl
    rows = [
        r for r in read_jsonl(Path(harmonized) / "annotations_harmonized.jsonl")
        if r["phase"] == "phase_1" and r["task"] == "SEG"
    ]
    source_by_id = {
        item["logical_span_id"]: item for item in verified["lineage"]
    }
    # Source consistency already checked above; here ensure the SEG view
    # matches exactly the expected non-remapped subset.
    expected_ids = {
        s["logical_span_id"] for s in verified["lineage"]
        if s["label"].startswith("SEG_")
        and s["label"] not in (
            "SEG_DECISAO_VOTO_VENCEDOR", "SEG_DECISAO_VOTO_VENCIDO"
        )
    }
    if {r["region_id"] for r in rows} != expected_ids:
        raise ValueError("SEG view differs from original-source logical spans")
    per_doc = defaultdict(list)
    for r in rows:
        per_doc[r["document_id"]].append(r)
    group_rows = []
    source_annotation_ids_in_groups = set()
    spans_in_groups = set()
    for doc_id in sorted(per_doc):
        for label, group in _components(per_doc[doc_id]):
            summary = _summarize("phase_1", doc_id, label, group, near_tolerance)
            source_rows = []
            for r in group:
                region = r["region_id"]
                spans_in_groups.add(region)
                source = source_by_id[region]
                for origin in source["source_records"]:
                    source_annotation_ids_in_groups.add(origin["annotation_id"])
                    source_rows.append({
                        "logical_span_id": region,
                        "annotation_id": origin["annotation_id"],
                        "source_row": origin["source_row"],
                        "selection_status": origin["selection_status"],
                        "original_label": origin["original_label"],
                        "revised_label": origin["revised_label"],
                        "original_start": origin["original_start"],
                        "original_end": origin["original_end"],
                        "revised_start": origin["revised_start"],
                        "revised_end": origin["revised_end"],
                        "review_agree_count": origin["review_agree_count"],
                        "review_disagree_count": origin["review_disagree_count"],
                    })
            summary["source_annotation_count"] = len(source_rows)
            summary["source_annotation_ids_unique"] = len({
                r["annotation_id"] for r in source_rows
            })
            summary["reviewed_final_source_rows"] = sum(
                r["selection_status"] == "reviewed_final" for r in source_rows
            )
            summary["original_confirmed_source_rows"] = sum(
                r["selection_status"] == "original_confirmed_by_reviewers"
                for r in source_rows
            )
            summary["source_label_revised_different"] = sum(
                r["original_label"] != r["revised_label"]
                for r in source_rows
                if r["selection_status"] == "reviewed_final"
            )
            summary["source_offset_revised_different"] = sum(
                (r["original_start"], r["original_end"]) !=
                (r["revised_start"], r["revised_end"])
                for r in source_rows
                if r["selection_status"] == "reviewed_final"
            )
            summary["source_rows"] = sorted(
                source_rows, key=lambda x: (x["logical_span_id"], x["source_row"],
                                           x["annotation_id"])
            )
            group_rows.append(summary)
    counts = {}
    for phase in ("phase_1",):
        part = [g for g in group_rows if g["phase"] == phase]
        counts[phase] = {
            "components": len(part),
            "documents": len({g["document_id"] for g in part}),
            "spans_in_components": sum(g["number_of_regions"] for g in part),
            "source_annotations_in_components": len(source_annotation_ids_in_groups),
            "source_rows_with_revised_offsets": sum(
                g["source_offset_revised_different"] for g in part
            ),
            "source_rows_with_revised_labels": sum(
                g["source_label_revised_different"] for g in part
            ),
            "overlapping_pairs": sum(g["overlapping_pairs"] for g in part),
            "near_boundary_pairs": sum(g["near_boundary_pairs"] for g in part),
        }
    if len(spans_in_groups) != sum(g["number_of_regions"] for g in group_rows):
        raise ValueError("Repeated spans in source-linked overlap components")
    if len(source_annotation_ids_in_groups) != sum(
            g["source_annotation_count"] for g in group_rows):
        raise ValueError("Repeated original annotation in multiple overlap groups")
    selected = _balanced_sample(group_rows, max_groups=max_groups,
                                max_per_document=max_per_document)
    return {
        "schema_version": "1.0.0",
        "mode": "verified_source_crosswalk_not_adjudication",
        "training_ready": False,
        "verified_source_manifest_sha256": verified["verified_raw_export_sha256"],
        "verified_intermediate_sha256": verified["verified_intermediate_sha256"],
        "verified_logical_spans": verified["verified_logical_spans"],
        "verified_source_annotations": verified["verified_source_annotations"],
        "verified_phase1_SEG_after_vote_mapping": len(rows),
        "by_phase": counts,
        "components_total": len(group_rows),
        "review_queue": selected,
        "review_queue_count": len(selected),
        "limits": {"max_groups": max_groups, "max_per_document": max_per_document,
                   "near_tolerance": near_tolerance},
        "limitations": (
            "Source rows and evaluator selected fields verified against declared "
            "original ingestion CSV hashes, not independently against raw Doccano "
            "export history. Reviewed_final does not imply correction or human "
            "consensus. Geometry cannot adjudicate true section boundaries."
        )
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("snapshot", "harmonized", "raw-texts", "raw-annotations",
                "output"):
        p.add_argument("--" + arg, type=Path, required=True)
    p.add_argument("--taxonomy", type=Path, default=Path("configs/labels.json"))
    p.add_argument("--ingested", type=Path, default=Path("data/interim/phase_1"))
    p.add_argument("--sanitized", type=Path,
                   default=Path("data/interim/phase_1/sanitized"))
    p.add_argument("--logical", type=Path,
                   default=Path("data/interim/phase_1/logical_spans"))
    p.add_argument("--document-spans", type=Path,
                   default=Path("data/interim/phase_1/document_dataset/document_spans.jsonl"))
    p.add_argument("--near-tolerance", type=int, default=5)
    p.add_argument("--max-groups", type=int, default=100)
    p.add_argument("--max-per-document", type=int, default=4)
    a = p.parse_args()
    target = a.output
    if target.exists():
        raise FileExistsError("Crosswalk report already exists")
    if not target.parent.is_dir():
        raise FileNotFoundError("Crosswalk output directory does not exist")
    result = analyze_component_source_crosswalk(
        a.snapshot, a.harmonized, a.taxonomy, a.raw_texts, a.raw_annotations,
        a.ingested, a.sanitized, a.logical, a.document_spans,
        near_tolerance=a.near_tolerance, max_groups=a.max_groups,
        max_per_document=a.max_per_document,
    )
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({
        "verified_logical_spans": result["verified_logical_spans"],
        "verified_source_annotations": result["verified_source_annotations"],
        "by_phase": result["by_phase"],
        "review_queue_count": result["review_queue_count"],
        "output": str(target),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
