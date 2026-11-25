"""Versioned *diagnostic* corpus: Phase 1 + Phase 2, never auto-promotes gold.

The output directory must not exist; inputs and their checksums are recorded.
No private judicial data should be committed to Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .corpus_adapters import phase1_records, phase2_records, resolve_text
from .quarantine import scan_phase2_regions
from ..io.jsonl import read_jsonl, write_jsonl
from ..io.label_studio import load as load_label_studio
from ..phase2_audit_v2 import audit as audit_phase2


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_from_task(task: dict) -> str:
    data = task["data"]
    # Keep the exact decoded text; no whitespace/newline normalization.
    choices = [data[key] for key in ("acordao", "text") if key in data]
    if len(choices) != 1 or not isinstance(choices[0], str):
        raise ValueError("Phase 2 task requires exactly one textual data field: acordao or text")
    return choices[0]


def _documents(phase1: list[dict], phase2_tasks: dict[str, dict]) -> tuple[list[dict], dict]:
    """Reject ambiguous identities and duplicate text across phases."""
    docs, phase2_text = [], {}
    acordaos, texts, canonical_ids = {}, {}, set()

    def add(phase: str, local_id: str, acordao, text: str, source_id: str) -> None:
        if not isinstance(text, str) or not text:
            raise ValueError("Document requires nonempty immutable text")
        canonical = f"{phase}:{local_id}"
        if canonical in canonical_ids:
            raise ValueError("Duplicate canonical document ID")
        canonical_ids.add(canonical)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in texts:
            raise ValueError("Identical source text under multiple documents: manual linkage required")
        texts[digest] = canonical
        key = str(acordao).strip() if acordao is not None else ""
        if key:
            if key in acordaos:
                raise ValueError("Repeated idacordao: manual cross-phase linkage required")
            acordaos[key] = canonical
        docs.append({
            "document_id": canonical, "phase": phase,
            "source_document_id": local_id, "idacordao": key or None,
            "source_id": source_id, "text": text, "text_sha256": digest,
        })

    for doc in phase1:
        local_id = str(doc["document_id"])
        text = doc["text"]
        declared_hash = doc.get("text_sha256")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if declared_hash != digest:
            raise ValueError("Phase 1 document checksum mismatch")
        add("phase_1", local_id, doc.get("idacordao"), text, local_id)

    for doc_id, task in sorted(phase2_tasks.items()):
        text = _text_from_task(task)
        phase2_text[doc_id] = text
        add("phase_2", doc_id, doc_id, text, str(task["id"]))

    return sorted(docs, key=lambda d: d["document_id"]), phase2_text


def build_diagnostic_corpus(
    phase1_documents: str | Path,
    phase2_original: str | Path,
    phase2_review_11: str | Path,
    phase2_review_17: str | Path,
    labels_path: str | Path,
    output_dir: str | Path,
    *,
    version: str,
    quarantine_unresolved: bool = False,
) -> dict:
    """Produce a versioned, traceable diagnostic snapshot; no training splits."""
    if not version or not version.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Version must be a nonempty alphanumeric identifier")
    paths = {
        "phase1_document_spans": Path(phase1_documents),
        "phase2_original": Path(phase2_original),
        "phase2_review_11": Path(phase2_review_11),
        "phase2_review_17": Path(phase2_review_17),
        "labels": Path(labels_path),
    }
    out = Path(output_dir)
    if out.exists():
        raise FileExistsError("Output directory already exists; versioned snapshots are immutable")
    phase1 = read_jsonl(paths["phase1_document_spans"])
    originals = load_label_studio(paths["phase2_original"])
    sheets, metrics, _ = audit_phase2(
        paths["phase2_original"], paths["phase2_review_11"],
        paths["phase2_review_17"],
    )
    label_config = json.loads(paths["labels"].read_text(encoding="utf-8"))
    labels = label_config["labels"]
    if not isinstance(labels, list) or len(labels) != len(set(labels)):
        raise ValueError("Taxonomy must contain unique labels")

    documents, phase2_text = _documents(phase1, originals)
    p1 = phase1_records(phase1)
    phase2_candidates = phase2_records(sheets)
    quarantine_records = []
    text_integrity_counts = {}
    if quarantine_unresolved:
        affected, findings, text_integrity_counts = scan_phase2_regions(
            paths["phase2_original"], paths["phase2_review_11"],
            paths["phase2_review_17"], _text_from_task,
        )
        def relevant_region_ids(record):
            ids = {str(record["region_id"])}
            provenance = record.get("provenance")
            if isinstance(provenance, dict):
                for key in ("original_region_id", "project_11_region_id",
                            "project_17_region_id"):
                    value = provenance.get(key)
                    if value:
                        ids.add(str(value))
            return ids

        eligible_candidates = []
        for record in phase2_candidates:
            doc_id = record["document_id"]
            related = sorted(
                rid for rid in relevant_region_ids(record)
                if (doc_id, rid) in affected
            )
            if related:
                quarantine_records.append({
                    "document_id": "phase_2:" + doc_id,
                    "region_id": record["region_id"],
                    "source_status": record["source_status"],
                    "original_review_status": record["status"],
                    "task": record["task"],
                    "label": record["label"],
                    "start": record["start"],
                    "end": record["end"],
                    "related_source_region_ids": related,
                    "reason": "unresolved_source_text_integrity",
                    "provenance": record["provenance"],
                })
            else:
                eligible_candidates.append(record)
        phase2_candidates = eligible_candidates
        # Store unmatched raw-source evidence too, including discrepancies
        # that are not part of the normalized audit view.
        for finding in findings:
            quarantine_records.append({
                "document_id": "phase_2:" + finding["idacordao"],
                "region_id": finding["region_id"],
                "project": finding["project"],
                "task": "NER" if finding["label"].startswith("ENT_") else "SEG",
                "label": finding["label"],
                "start": finding["start"],
                "end": finding["end"],
                "reason": finding["reason"],
                "record_type": "raw_source_occurrence",
            })
    p2 = resolve_text(phase2_candidates, phase2_text)
    rows = []
    seen_source_regions = set()
    for record in p1 + p2:
        updated = {**record, "document_id": record["phase"] + ":" + record["document_id"]}
        source_identity = (updated["phase"], updated["document_id"],
                           updated["region_id"], updated["source_status"],
                           str(updated["provenance"].get("project_id", "")) if
                           isinstance(updated["provenance"], dict) else "")
        if source_identity in seen_source_regions:
            raise ValueError("Duplicate source region identity in diagnostic snapshot")
        seen_source_regions.add(source_identity)
        if updated["label"] not in labels:
            raise ValueError("Unknown label in canonical taxonomy")
        rows.append(updated)

    lookup = {d["document_id"]: d for d in documents}
    for record in rows:
        doc = lookup[record["document_id"]]
        start, end = record["start"], record["end"]
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(doc["text"])
                or record["text"] != doc["text"][start:end]):
            raise ValueError("Corpus span offsets or text mismatch")
    rows.sort(key=lambda r: (
        r["document_id"], r["task"], r["start"], r["end"],
        r["label"], r["region_id"], r["source_status"],
    ))
    counts = Counter((r["phase"], r["task"], r["status"]) for r in rows)
    manifest = {
        "schema_version": "0.1.0",
        "corpus_version": version,
        "kind": "diagnostic_snapshot",
        "training_ready": False,
        "splits_frozen": False,
        "reason": "Eligibility policy, process linkage and frozen splits are not finalized",
        "taxonomy_version": label_config.get("schema_version"),
        "input_sha256": {key: _digest(path) for key, path in paths.items()},
        "document_count": len(documents),
        "document_count_by_phase": dict(sorted(Counter(d["phase"] for d in documents).items())),
        "annotation_count": len(rows),
        "quarantine_enabled": quarantine_unresolved,
        "quarantine_record_count": len(quarantine_records),
        "quarantine_normalized_rows": sum(
            item.get("reason") == "unresolved_source_text_integrity"
            for item in quarantine_records
        ),
        "source_text_integrity_counts": text_integrity_counts,
        "quarantine_policy": (
            "Conservative exclusion from normalized annotations if any source "
            "project for the same decision and region ID has an unresolved text "
            "mismatch; preserve each source occurrence in quarantine.jsonl; "
            "not training-ready"
        ) if quarantine_unresolved else "strict validation",

        "counts": [
            {"phase": phase, "task": task, "status": status, "count": count}
            for (phase, task, status), count in sorted(counts.items())
        ],
        "phase2_audit_metrics": metrics,
        "phase2_text_equivalence": dict(sorted(
            Counter(row.get("text_equivalence", "not_applicable") for row in p2).items()
        )),
        "text_equivalence_policy": (
            "exact match OR literal \\n/\\t interpreted as control characters "
            "only when resulting text equals the immutable document slice; "
            "raw source excerpt retained"
        ),
        "identity_policy": "phase-namespaced IDs; reject duplicate text and idacordao",
    }
    # All validation is completed before any output is created.
    out.mkdir(parents=True, exist_ok=False)
    write_jsonl(out / "documents.jsonl", documents)
    write_jsonl(out / "annotations.jsonl", rows)
    if quarantine_unresolved:
        write_jsonl(out / "quarantine.jsonl", quarantine_records)
    (out / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-document-spans", type=Path, required=True)
    parser.add_argument("--phase2-original", type=Path, required=True)
    parser.add_argument("--phase2-review-11", type=Path, required=True)
    parser.add_argument("--phase2-review-17", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=Path("configs/labels.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--quarantine-unresolved", action="store_true",
                        help="Diagnostic mode; quarantine unresolved source texts without changing originals")
    args = parser.parse_args()
    result = build_diagnostic_corpus(
        args.phase1_document_spans, args.phase2_original,
        args.phase2_review_11, args.phase2_review_17,
        args.labels, args.output, version=args.version,
        quarantine_unresolved=args.quarantine_unresolved,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
