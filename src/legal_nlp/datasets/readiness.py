"""Auditable readiness report for a versioned diagnostic corpus.

This module NEVER creates supervised labels, partitions, or training files.
A status of "consolidated" means technical agreement in the audit, not a
blanket authorization to use a document as complete supervised gold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..io.jsonl import read_jsonl


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def analyze_readiness(snapshot_dir: str | Path) -> dict[str, Any]:
    root = Path(snapshot_dir)
    manifest = json.loads((root / "dataset_manifest.json").read_text(encoding="utf-8"))
    documents = read_jsonl(root / "documents.jsonl")
    annotations = read_jsonl(root / "annotations.jsonl")
    if manifest.get("kind") != "diagnostic_snapshot" or manifest.get("training_ready") is not False:
        raise ValueError("Expected an explicitly non-training diagnostic snapshot")
    if len(documents) != manifest.get("document_count") or len(annotations) != manifest.get("annotation_count"):
        raise ValueError("Snapshot and manifest row counts differ")
    quarantine_count = manifest.get("quarantine_record_count", 0)
    if type(quarantine_count) is not int or quarantine_count < 0:
        raise ValueError("Invalid quarantine count in manifest")
    if manifest.get("quarantine_enabled"):
        quarantine_file = root / "quarantine.jsonl"
        if not quarantine_file.is_file():
            raise ValueError("Quarantine manifest requires quarantine.jsonl")
        if len(read_jsonl(quarantine_file)) != quarantine_count:
            raise ValueError("Quarantine and manifest row counts differ")
    elif quarantine_count:
        raise ValueError("Nonzero quarantine count without quarantine mode")


    ids: set[str] = set()
    acordaos: dict[str, str] = {}
    text_hashes: dict[str, str] = {}
    docs: dict[str, dict[str, Any]] = {}
    grouping_missing: list[str] = []
    for doc in documents:
        doc_id = doc["document_id"]
        if not isinstance(doc_id, str) or not doc_id or doc_id in ids:
            raise ValueError("Duplicate or invalid document ID")
        ids.add(doc_id)
        text = doc["text"]
        digest = _text_hash(text)
        if digest != doc["text_sha256"]:
            raise ValueError(f"Text checksum mismatch for {doc_id}")
        if digest in text_hashes:
            raise ValueError("Duplicate exact document text across IDs")
        text_hashes[digest] = doc_id
        acordao = doc.get("idacordao")
        if acordao is not None and str(acordao).strip():
            value = str(acordao).strip()
            if value in acordaos:
                raise ValueError("Duplicate idacordao in snapshot")
            acordaos[value] = doc_id
        # idacordao identifies a decision, not necessarily a judicial process.
        if not isinstance(doc.get("process_id"), str) or not doc["process_id"].strip():
            grouping_missing.append(doc_id)
        docs[doc_id] = doc

    statuses = Counter()
    labels = Counter()
    by_document: dict[str, Counter[str]] = defaultdict(Counter)
    by_task: dict[str, Counter[str]] = defaultdict(Counter)
    seen_region_keys = set()
    geometry_map: dict[tuple[str, str, int, int], set[str]] = defaultdict(set)
    for item in annotations:
        doc_id = item["document_id"]
        if doc_id not in docs:
            raise ValueError(f"Orphan annotation in {doc_id}")
        task, label = item["task"], item["label"]
        if task not in {"NER", "SEG"} or not isinstance(label, str) or not label.startswith(
            "ENT_" if task == "NER" else "SEG_"
        ):
            raise ValueError(f"Task/label mismatch in {doc_id}")
        start, end = item["start"], item["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(docs[doc_id]["text"]):
            raise ValueError(f"Invalid span bounds in {doc_id}")
        if docs[doc_id]["text"][start:end] != item["text"]:
            raise ValueError(f"Span text mismatch in {doc_id}")
        status = item["status"]
        if status not in {"consolidated", "pending_review", "rejected", "excluded_invalid"}:
            raise ValueError(f"Unexpected annotation status: {status}")
        region_id = item["region_id"]
        if not isinstance(region_id, str) or not region_id:
            raise ValueError("Missing source region identity")
        # Two distinct proposals can retain the same local ID across review projects.
        provenance = item.get("provenance")
        if not provenance:
            raise ValueError("Missing annotation provenance")
        project = str(provenance.get("project_id", "")) if isinstance(provenance, dict) else ""
        key = (doc_id, region_id, project, item["source_status"])
        if key in seen_region_keys:
            raise ValueError("Duplicate annotation source identity")
        seen_region_keys.add(key)
        statuses[status] += 1
        labels[(task, label)] += 1
        by_document[doc_id][status] += 1
        by_task[task][status] += 1
        geometry_map[(doc_id, task, start, end)].add(label)

    same_boundary_different_label = sum(len(x) > 1 for x in geometry_map.values())
    checks = {
        "source_manifest_present": bool(manifest.get("input_sha256")),
        "document_identity_unique": True,
        "text_integrity_verified": True,
        "span_integrity_verified": True,
        "taxonomy_version_present": bool(manifest.get("taxonomy_version")),
        "process_linkage_complete": not grouping_missing,
        "annotation_adjudication_complete": statuses["pending_review"] == 0,
        "source_text_quarantine_empty": quarantine_count == 0,
        "formal_gold_approval": False,
        "splits_frozen": manifest.get("splits_frozen") is True,
    }
    # No implicit training authorization even if there are zero pending annotations.
    blockers = [name for name, ok in checks.items() if not ok]
    report = {
        "report_schema_version": "0.1.0",
        "corpus_version": manifest.get("corpus_version"),
        "input_files_sha256": {
            "documents.jsonl": _hash(root / "documents.jsonl"),
            "annotations.jsonl": _hash(root / "annotations.jsonl"),
            "dataset_manifest.json": _hash(root / "dataset_manifest.json"),
        },
        "document_count": len(documents),
        "annotation_count": len(annotations),
        "quarantine_record_count": quarantine_count,
        "annotation_status_counts": dict(sorted(statuses.items())),
        "by_task_status": {
            task: dict(sorted(counter.items())) for task, counter in sorted(by_task.items())
        },
        "label_support": [
            {"task": task, "label": label, "records": count}
            for (task, label), count in sorted(labels.items())
        ],
        "documents_with_pending_reviews": sum(
            by_document[doc_id]["pending_review"] > 0 for doc_id in docs
        ),
        "documents_without_process_id": len(grouping_missing),
        "same_boundary_different_label_diagnostic": same_boundary_different_label,
        "checks": checks,
        "blockers": blockers,
        "training_ready": False,
        "splits_frozen": False,
        "policy": (
            "No automatic gold promotion. Group by verified process before splits; "
            "same-boundary multi-label spans are diagnostic, never silently dropped."
        ),
    }
    return report


def write_readiness_report(snapshot_dir: str | Path, output: str | Path) -> dict[str, Any]:
    report = analyze_readiness(snapshot_dir)
    target = Path(output)
    root = Path(snapshot_dir).resolve()
    if target.resolve() == root / "dataset_manifest.json":
        raise ValueError("Refusing to overwrite corpus manifest")
    if target.exists():
        raise FileExistsError("Readiness report already exists")
    if not target.parent.is_dir():
        raise FileNotFoundError("Output parent directory must exist")
    target.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = write_readiness_report(args.snapshot, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
