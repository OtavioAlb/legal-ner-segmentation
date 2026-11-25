"""Create an explicitly derived, reversible vote-label harmonization view.

Only Phase 1 SEG_DECISAO_VOTO_* maps to the corresponding Phase 2
ENT_DECISAO_VOTO_*. No source files or statuses change. Not training-ready.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from ..io.jsonl import read_jsonl, write_jsonl


PHASE1_VOTE_MAP = {
    "SEG_DECISAO_VOTO_VENCEDOR": "ENT_DECISAO_VOTO_VENCEDOR",
    "SEG_DECISAO_VOTO_VENCIDO": "ENT_DECISAO_VOTO_VENCIDO",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_vote_harmonized_view(snapshot_dir, output_dir):
    source = Path(snapshot_dir)
    dest = Path(output_dir)
    if dest.exists():
        raise FileExistsError("Derived output already exists; snapshots are immutable")
    manifest_path = source / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "diagnostic_snapshot" or manifest.get("training_ready") is not False:
        raise ValueError("Requires a non-training diagnostic snapshot")
    annotations_file = source / "annotations.jsonl"
    documents_file = source / "documents.jsonl"
    records = read_jsonl(annotations_file)
    documents = read_jsonl(documents_file)
    if (len(records) != manifest.get("annotation_count")
            or len(documents) != manifest.get("document_count")):
        raise ValueError("Input manifest count mismatch")
    source_quarantine = source / "quarantine.jsonl"
    if manifest.get("quarantine_record_count", 0):
        if not source_quarantine.is_file():
            raise ValueError("Missing input quarantine")
        if len(read_jsonl(source_quarantine)) != manifest["quarantine_record_count"]:
            raise ValueError("Input quarantine count mismatch")
    if len({d["document_id"] for d in documents}) != len(documents):
        raise ValueError("Duplicate document identifiers")

    rewritten = []
    transitions = Counter()
    seen = set()
    for row in records:
        phase, original, task = row["phase"], row["label"], row["task"]
        if row["document_id"] not in {d["document_id"] for d in documents}:
            raise ValueError("Unknown document identifier")
        if row["status"] not in ("consolidated", "pending_review"):
            raise ValueError("Unexpected status in input")
        if not isinstance(row.get("region_id"), str) or not row["region_id"]:
            raise ValueError("Missing region id")
        if not row.get("provenance"):
            raise ValueError("Missing provenance")
        source_key = (row["document_id"], row["region_id"],
                      str(row["provenance"].get("project_id", "")) if isinstance(row["provenance"], dict) else "",
                      row.get("source_status"))
        if source_key in seen:
            raise ValueError("Duplicate source identity")
        seen.add(source_key)
        mapping = PHASE1_VOTE_MAP.get(original) if phase == "phase_1" else None
        if mapping and task != "SEG":
            raise ValueError("Unexpected task for Phase 1 vote segment")
        target = mapping or original
        final_task = "NER" if mapping else task
        updated = {
            **row,
            "label": target,
            "task": final_task,
            "source_label": original,
            "source_task": task,
            "harmonization": {
                "policy": "phase1_vote_result_to_ner_v1" if mapping else "identity",
                "changed": bool(mapping),
            },
        }
        rewritten.append(updated)
        if mapping:
            transitions[(original, target)] += 1

    expected = sum(transitions.values())
    counts = Counter((row["phase"], row["task"], row["status"]) for row in rewritten)
    view_manifest = {
        "schema_version": "1.0.0",
        "kind": "derived_diagnostic_label_view",
        "training_ready": False,
        "splits_frozen": False,
        "formal_gold_approval": False,
        "source_snapshot_version": manifest.get("corpus_version"),
        "source_sha256": {
            "dataset_manifest.json": _sha(manifest_path),
            "documents.jsonl": _sha(documents_file),
            "annotations.jsonl": _sha(annotations_file),
            **({"quarantine.jsonl": _sha(source_quarantine)}
               if source_quarantine.exists() else {}),
        },
        "source_documents": len(documents),
        "source_annotations": len(records),
        "output_annotations": len(rewritten),
        "mapped_count": expected,
        "transitions": [
            {"from": old, "to": new, "count": count}
            for (old, new), count in sorted(transitions.items())
        ],
        "counts": [
            {"phase": phase, "task": task, "status": status, "count": value}
            for (phase, task, status), value in sorted(counts.items())
        ],
        "quarantine_record_count": manifest.get("quarantine_record_count", 0),
        "quarantine_not_harmonized": True,
        "policy": (
            "Derived Phase 1 vote-result SEG to ENT mapping only. Original labels "
            "and tasks retained per row, original offsets/text/status/provenance "
            "unchanged. NOT authorized as gold or for training."
        ),
    }
    dest.mkdir(parents=True, exist_ok=False)
    write_jsonl(dest / "annotations_harmonized.jsonl", rewritten)
    (dest / "harmonization_manifest.json").write_text(
        json.dumps(view_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return view_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_vote_harmonized_view(args.snapshot, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
