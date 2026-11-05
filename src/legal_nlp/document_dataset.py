"""Document-level span dataset and deterministic, leakage-checked CV folds.

No BIO labels, span adjudication, tokenization, source annotation deletion,
or train/validation sample mixing. Actual judicial text is written only to
local output paths, which must remain git-ignored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for row in records:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def build_document_dataset(
    documents_path: str | Path,
    logical_spans_path: str | Path,
    output_dir: str | Path,
    folds: int = 5,
    seed: int = 42,
) -> dict[str, Any]:
    """Build document-aligned spans and disjoint validation folds.

    Fold assignment is a stable SHA-256(seed, document_id) ordering followed
    by round-robin allocation, not label-stratified. It prevents document-
    level leakage, but does NOT guarantee process-level independence when
    multiple distinct decisions belong to the same judicial proceeding.
    """
    if isinstance(folds, bool) or not isinstance(folds, int) or folds < 2:
        raise ValueError("folds must be an integer >= 2")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    documents_path = Path(documents_path)
    logical_spans_path = Path(logical_spans_path)
    output_dir = Path(output_dir)
    documents = _read_jsonl(documents_path)
    logical_spans = _read_jsonl(logical_spans_path)
    if len(documents) < folds:
        raise ValueError("Each validation fold requires at least one document")

    by_id: dict[str, dict[str, Any]] = {}
    seen_text_hashes: dict[str, str] = {}
    seen_acordao_ids: dict[str, str] = {}
    for document in documents:
        document_id = document.get("document_id")
        content = document.get("text")
        declared_hash = document.get("text_sha256")
        if not isinstance(document_id, str) or not document_id:
            raise ValueError("Document without valid document_id")
        if document_id in by_id:
            raise ValueError(f"Duplicate document_id: {document_id}")
        if not isinstance(content, str):
            raise ValueError(f"Document without source text: {document_id}")
        computed_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if declared_hash != computed_hash:
            raise ValueError(f"Document text checksum mismatch: {document_id}")
        if computed_hash in seen_text_hashes:
            raise ValueError(
                "Identical text occurs under distinct document IDs: "
                f"{seen_text_hashes[computed_hash]}, {document_id}. "
                "Manual linkage/grouping required before folds."
            )
        seen_text_hashes[computed_hash] = document_id
        # idacordao refers to the decision, not necessarily the process.
        acordao_id = document.get("idacordao")
        if isinstance(acordao_id, str) and acordao_id.strip():
            key = acordao_id.strip()
            if key in seen_acordao_ids:
                raise ValueError(
                    f"Repeated idacordao across documents: {key}. "
                    "Resolve shared decision identity before splitting."
                )
            seen_acordao_ids[key] = document_id
        by_id[document_id] = document

    by_document: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"NER": [], "SEG": []}
    )
    seen_spans: set[str] = set()
    seen_span_keys: set[tuple[str, str, int, int, str]] = set()
    label_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    source_count = 0
    for span in logical_spans:
        identifier = span.get("logical_span_id")
        document_id = span.get("document_id")
        task, label = span.get("task"), span.get("label")
        start, end = span.get("start"), span.get("end")
        provenance = span.get("provenance")
        if not isinstance(identifier, str) or not identifier or identifier in seen_spans:
            raise ValueError(f"Missing or duplicate logical span ID: {identifier}")
        seen_spans.add(identifier)
        if document_id not in by_id:
            raise ValueError(f"Span references unknown document: {document_id}")
        if (task not in {"NER", "SEG"}
                or not isinstance(label, str)
                or not label.startswith("ENT_" if task == "NER" else "SEG_")
                or not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)
                or start < 0 or end <= start or end > len(by_id[document_id]["text"])):
            raise ValueError(f"Invalid logical span bounds/label: {identifier}")
        key = (document_id, task, start, end, label)
        if key in seen_span_keys:
            raise ValueError(f"Duplicate logical span key: {identifier}")
        seen_span_keys.add(key)
        if (not isinstance(provenance, list) or not provenance
                or len(provenance) != span.get("source_annotation_count")):
            raise ValueError(f"Inconsistent span provenance: {identifier}")
        for source in provenance:
            if not isinstance(source, dict) or not source.get("annotation_id"):
                raise ValueError(f"Invalid source lineage: {identifier}")
        source_count += len(provenance)
        by_document[document_id][task].append(span)
        task_counts[task] += 1
        label_counts[label] += 1

    doc_ids = sorted(
        by_id,
        key=lambda doc_id: (
            hashlib.sha256(f"{seed}|{doc_id}".encode("utf-8")).hexdigest(),
            doc_id,
        ),
    )
    validation_groups = [sorted(doc_ids[i::folds]) for i in range(folds)]
    if any(not fold for fold in validation_groups):
        raise AssertionError("Empty validation fold")
    if sorted(doc_id for group in validation_groups for doc_id in group) != sorted(by_id):
        raise AssertionError("Each document must appear in exactly one validation fold")

    fold_by_document: dict[str, int] = {}
    for index, group in enumerate(validation_groups):
        for doc_id in group:
            fold_by_document[doc_id] = index

    document_rows: list[dict[str, Any]] = []
    for document_id in sorted(by_id):
        document = by_id[document_id]
        tasks = by_document[document_id]
        document_rows.append({
            "document_id": document_id,
            "source_id": document.get("source_id"),
            "idacordao": document.get("idacordao"),
            "text": document["text"],
            "text_sha256": document["text_sha256"],
            "validation_fold": fold_by_document[document_id],
            "spans": {
                task: sorted(
                    tasks[task],
                    key=lambda item: (
                        item["start"], item["end"], item["label"],
                        item["logical_span_id"],
                    ),
                ) for task in ("NER", "SEG")
            },
        })

    counts_by_fold: list[dict[str, Any]] = []
    manifest_folds: list[dict[str, Any]] = []
    all_doc_ids = set(by_id)
    for i, validation_ids in enumerate(validation_groups):
        val_ids = set(validation_ids)
        train_ids = sorted(all_doc_ids - val_ids)
        if val_ids & set(train_ids):
            raise AssertionError("Document leakage detected")
        per_task = Counter()
        per_label = Counter()
        for doc_id in validation_ids:
            for task in ("NER", "SEG"):
                for span in by_document[doc_id][task]:
                    per_task[task] += 1
                    per_label[span["label"]] += 1
        counts_by_fold.append({
            "fold": i,
            "validation_documents": len(validation_ids),
            "training_documents": len(train_ids),
            "validation_spans_by_task": {
                task: per_task[task] for task in ("NER", "SEG")
            },
            "validation_label_counts": dict(sorted(per_label.items())),
            "labels_absent_from_validation": sorted(
                set(label_counts) - set(per_label)
            ),
        })
        manifest_folds.append({
            "fold": i,
            "training_document_ids": train_ids,
            "validation_document_ids": validation_ids,
        })

    fold_manifest = {
        "fold_schema_version": "1.0.0",
        "split_unit": "document_id",
        "folds": folds,
        "seed": seed,
        "stratification": "none; stable SHA-256 document ordering, balanced fold sizes",
        "process_grouping": "not_guaranteed; judicial process key not available",
        "fold_assignments": manifest_folds,
    }
    summary = {
        "document_dataset_schema_version": "1.0.0",
        "document_count": len(document_rows),
        "logical_span_count": len(logical_spans),
        "source_annotation_count_preserved": source_count,
        "logical_span_count_by_task": {
            task: task_counts[task] for task in ("NER", "SEG")
        },
        "unique_label_count": len(label_counts),
        "fold_count": folds,
        "fold_sizes": [len(group) for group in validation_groups],
        "fold_diagnostics": counts_by_fold,
        "policy": (
            "span supervision only; exact original text and character offsets; "
            "no overlap deletion, boundary alignment, label arbitration or BIO; "
            "document-disjoint CV, no process-level guarantee"
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "document_spans.jsonl", document_rows)
    (output_dir / "document_folds.json").write_bytes(_json_bytes(fold_manifest))
    (output_dir / "document_dataset_summary.json").write_bytes(_json_bytes(summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build local document-level span datasets and CV folds"
    )
    parser.add_argument(
        "--documents", type=Path,
        default=Path("data/interim/phase_1/documents.jsonl"),
    )
    parser.add_argument(
        "--logical-spans", type=Path,
        default=Path("data/interim/phase_1/logical_spans/logical_spans.jsonl"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/interim/phase_1/document_dataset"),
    )
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(
        build_document_dataset(
            args.documents, args.logical_spans, args.output, args.folds, args.seed,
        ), ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
