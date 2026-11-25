"""Fail-closed Phase 1 lineage audit, from raw exports to harmonized snapshot.

Unlike geometry diagnostics this audit REQUIRES the actual raw Phase 1 files
and checks original export checksums recorded at ingestion. Nothing is written
to Git or modified in the source corpus.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from ..io.jsonl import read_jsonl
from .harmonized_label_support import _validate_and_load, _sha
from .corpus_adapters import phase1_records


def _unique(rows, field, where):
    data = {}
    for row in rows:
        key = row.get(field)
        if not isinstance(key, str) or not key or key in data:
            raise ValueError(f"Invalid or repeated {field} in {where}: {key}")
        data[key] = row
    return data


def audit_phase1_lineage(snapshot, harmonized, taxonomy, raw_texts,
                         raw_annotations, ingested, sanitized, logical,
                         document_spans):
    ingested, sanitized, logical = map(Path, (ingested, sanitized, logical))
    source_manifest = json.loads(
        (ingested / "dataset_manifest.json").read_text(encoding="utf-8")
    )
    declared = source_manifest.get("input_sha256", {})
    expected = {
        "texts": _sha(Path(raw_texts)),
        "annotations": _sha(Path(raw_annotations)),
    }
    for name, digest in expected.items():
        if not isinstance(declared.get(name), str) or declared[name] != digest:
            raise ValueError(f"Original raw export checksum mismatch: {name}")
    # Verify all surviving logical spans against both intermediate layers.
    original_rows = read_jsonl(ingested / "annotations.jsonl")
    sanitized_rows = read_jsonl(sanitized / "sanitized_annotations.jsonl")
    logical_rows = read_jsonl(logical / "logical_spans.jsonl")
    document_rows = read_jsonl(Path(document_spans))
    ingested_docs = read_jsonl(ingested / "documents.jsonl")
    original = _unique(original_rows, "annotation_id", "ingested")
    clean = _unique(sanitized_rows, "annotation_id", "sanitized")
    logical_map = _unique(logical_rows, "logical_span_id", "logical")
    orig_docs = _unique(ingested_docs, "document_id", "ingested documents")
    doc_map = _unique(document_rows, "document_id", "document spans")
    for name, doc in doc_map.items():
        if name not in orig_docs or doc["text"] != orig_docs[name]["text"]:
            raise ValueError(f"Phase 1 document text differs from ingested source: {name}")
    derived_rows = phase1_records(document_rows)
    derived_map = _unique(derived_rows, "region_id", "document spans")
    # The harmonized snapshot is checked against its original input separately.
    snapshot_docs, harmonized_rows, _, _, _ = _validate_and_load(
        snapshot, harmonized, taxonomy
    )
    relevant_docs = {
        d["document_id"]: d for d in snapshot_docs if d["phase"] == "phase_1"
    }
    if len(relevant_docs) != len(doc_map):
        raise ValueError("Phase 1 document count differs across snapshot/source")
    for doc_id, doc in doc_map.items():
        canonical = "phase_1:" + doc_id
        if canonical not in relevant_docs or relevant_docs[canonical]["text"] != doc["text"]:
            raise ValueError(f"Snapshot document differs from original: {canonical}")
    phase1 = [r for r in harmonized_rows if r["phase"] == "phase_1"]
    if len(phase1) != len(derived_map) or len(logical_map) != len(derived_map):
        raise ValueError("Different logical-span counts in Phase 1 chain")
    issue_counts = Counter()
    selection_counts = Counter()
    annotation_references = set()
    checked = 0
    checked_seg = 0
    by_label = Counter()
    all_lineage = []
    for row in phase1:
        logical_id = row["region_id"]
        if logical_id not in logical_map or logical_id not in derived_map:
            raise ValueError(f"Unknown logical ID in snapshot: {logical_id}")
        logical_span = logical_map[logical_id]
        adapted = derived_map[logical_id]
        if row["document_id"] != "phase_1:" + adapted["document_id"]:
            raise ValueError(f"Document identity mismatch: {logical_id}")
        for field in ("label", "task", "start", "end"):
            if row["source_" + field] != adapted[field] if field in ("label", "task") else row[field] != adapted[field]:
                raise ValueError(f"Phase 1 source field differs: {logical_id}/{field}")
        for field in ("document_id", "label", "task", "start", "end"):
            if logical_span[field] != adapted[field]:
                raise ValueError(f"Logical span differs from document spans: {logical_id}/{field}")
        if logical_span["provenance"] != row["provenance"] or adapted["provenance"] != row["provenance"]:
            raise ValueError(f"Provenance changed between layers: {logical_id}")
        if not isinstance(row["provenance"], list) or not row["provenance"]:
            raise ValueError(f"Phase 1 provenance is not a nonempty list: {logical_id}")
        if len(row["provenance"]) != logical_span["source_annotation_count"]:
            raise ValueError(f"Source annotation count inconsistent: {logical_id}")
        ids = set()
        lineage = []
        for entry in row["provenance"]:
            ann_id = entry["annotation_id"]
            if ann_id in ids or ann_id not in original or ann_id not in clean:
                raise ValueError(f"Source annotation missing/repeated: {logical_id}/{ann_id}")
            ids.add(ann_id)
            if ann_id in annotation_references:
                raise ValueError(f"Source annotation assigned to multiple logical spans: {ann_id}")
            annotation_references.add(ann_id)
            ing = original[ann_id]
            sanit = clean[ann_id]
            for f in ("document_id", "label", "task", "start", "end"):
                if sanit[f] != logical_span[f]:
                    raise ValueError(f"Sanitized span differs from logical source: {ann_id}/{f}")
            if (entry["source_row"] != ing["source_row"] or
                    entry["source_row"] != sanit["source_row"] or
                    entry.get("annotator_id") != sanit.get("annotator_id") or
                    entry.get("annotator_id") != ing.get("annotator_id")):
                raise ValueError(f"Original row or annotator linkage differs: {ann_id}")
            selection = ing.get("target_selection_status")
            expected_truth = (
                "evaluator_reviewed_fields" if selection == "reviewed_final"
                else "original_confirmed_by_reviewers"
                if selection == "original_confirmed_by_reviewers" else None
            )
            if expected_truth is None or entry["selection_status"] != selection:
                raise ValueError(f"Unsupported reviewer selection: {ann_id}")
            if sanit["source_of_truth"] != expected_truth or entry["source_of_truth"] != expected_truth:
                raise ValueError(f"Reviewer target selection differs: {ann_id}")
            if (entry.get("review_agree_count") != ing.get("review_agree_count") or
                    entry.get("review_disagree_count") != ing.get("review_disagree_count")):
                raise ValueError(f"Reviewer vote counts differ: {ann_id}")
            selection_counts[selection] += 1
            # Use annotation IDs only in local review queue; no reviewer PII.
            lineage.append({
                "annotation_id": ann_id,
                "source_row": sanit["source_row"],
                "selection_status": selection,
                "original_label": ing["fields_original"].get("label"),
                "revised_label": ing["fields_revised"].get("label"),
                "original_start": ing["fields_original"].get("start"),
                "original_end": ing["fields_original"].get("end"),
                "revised_start": ing["fields_revised"].get("start"),
                "revised_end": ing["fields_revised"].get("end"),
                "review_agree_count": ing.get("review_agree_count"),
                "review_disagree_count": ing.get("review_disagree_count"),
            })
        checked += 1
        checked_seg += row["source_task"] == "SEG"
        by_label[row["source_label"]] += 1
        all_lineage.append({
            "document_id": row["document_id"],
            "logical_span_id": logical_id,
            "label": row["source_label"],
            "start": row["start"], "end": row["end"],
            "source_annotation_count": len(lineage),
            "source_records": lineage,
        })
    if set(derived_map) != {r["region_id"] for r in phase1}:
        raise ValueError("Missing Phase 1 logical spans in harmonized snapshot")
    if set(clean) != annotation_references:
        raise ValueError("Sanitized source annotations not fully accounted for")
    # Record the lineage of every Phase 1 logical span; audit output is private.
    return {
        "schema_version": "1.0.0",
        "kind": "phase1_source_lineage_audit",
        "training_ready": False, "verified_raw_export_sha256": expected,
        "verified_intermediate_sha256": {
            "ingested_annotations": _sha(ingested / "annotations.jsonl"),
            "sanitized_annotations": _sha(sanitized / "sanitized_annotations.jsonl"),
            "logical_spans": _sha(logical / "logical_spans.jsonl"),
            "document_spans": _sha(Path(document_spans)),
        },
        "verified_logical_spans": checked,
        "verified_seg_spans": checked_seg,
        "verified_source_annotations": len(annotation_references),
        "selection_counts": dict(sorted(selection_counts.items())),
        "segmentation_labels": dict(sorted((k, v) for k, v in by_label.items()
                                             if k.startswith("SEG_"))),
        "lineage": all_lineage,
        "warning": (
            "Raw bytes verified against the SHA-256 recorded by ingestion. "
            "Ingested source rows, sanitized annotations, logical spans, "
            "document spans and harmonized snapshot cross-checked. "
            "This verifies provenance, not whether each evaluator decision "
            "is methodologically valid or gold-approved."
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--harmonized", type=Path, required=True)
    p.add_argument("--taxonomy", type=Path, default=Path("configs/labels.json"))
    p.add_argument("--raw-texts", type=Path, required=True)
    p.add_argument("--raw-annotations", type=Path, required=True)
    p.add_argument("--ingested", type=Path, default=Path("data/interim/phase_1"))
    p.add_argument("--sanitized", type=Path, default=Path("data/interim/phase_1/sanitized"))
    p.add_argument("--logical", type=Path, default=Path("data/interim/phase_1/logical_spans"))
    p.add_argument("--document-spans", type=Path,
                   default=Path("data/interim/phase_1/document_dataset/document_spans.jsonl"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = audit_phase1_lineage(
        a.snapshot, a.harmonized, a.taxonomy, a.raw_texts,
        a.raw_annotations, a.ingested, a.sanitized, a.logical, a.document_spans
    )
    out = a.output
    if out.exists():
        raise FileExistsError("Source lineage report already exists")
    if not out.parent.is_dir():
        raise FileNotFoundError("Output parent does not exist")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "verified_logical_spans": result["verified_logical_spans"],
        "verified_seg_spans": result["verified_seg_spans"],
        "verified_source_annotations": result["verified_source_annotations"],
        "selection_counts": result["selection_counts"],
        "output": str(out),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
