"""Read-only comparison of annotation frequencies and segmentation coverage.

Both consolidated and pending_review are counted as *potential* labels,
not formally approved gold. Quarantined normalized regions are separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from ..io.jsonl import read_jsonl


def _covered(intervals):
    """Union length of half-open intervals; overlapping spans count once."""
    length, end_seen = 0, 0
    for start, end in sorted(intervals):
        if end <= end_seen:
            continue
        length += end - max(start, end_seen)
        end_seen = end
    return length


def _distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {"min": 0, "median": 0, "max": 0, "mean": 0}
    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


def compare_phase_coverage(snapshot_dir):
    root = Path(snapshot_dir)
    manifest_file = root / "dataset_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("kind") != "diagnostic_snapshot" or manifest.get("training_ready") is not False:
        raise ValueError("Expected diagnostic-only corpus snapshot")
    docs = read_jsonl(root / "documents.jsonl")
    spans = read_jsonl(root / "annotations.jsonl")
    quarantine_file = root / "quarantine.jsonl"
    quarantined = read_jsonl(quarantine_file) if quarantine_file.is_file() else []
    if len(docs) != manifest.get("document_count") or len(spans) != manifest.get("annotation_count"):
        raise ValueError("Manifest totals and snapshot content differ")
    if manifest.get("quarantine_record_count", 0) != len(quarantined):
        raise ValueError("Manifest quarantine count mismatch")
    doc_by_id = {doc["document_id"]: doc for doc in docs}
    if len(doc_by_id) != len(docs):
        raise ValueError("Duplicate documents")
    per_doc = defaultdict(list)
    for row in spans:
        doc_id = row["document_id"]
        if doc_id not in doc_by_id:
            raise ValueError("Annotation references unknown document")
        doc = doc_by_id[doc_id]
        if row["phase"] != doc["phase"]:
            raise ValueError("Annotation phase differs from document phase")
        start, end = row["start"], row["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(doc["text"]):
            raise ValueError("Invalid annotation offsets")
        if row["text"] != doc["text"][start:end]:
            raise ValueError("Annotation text and source disagree")
        if row["status"] not in ("consolidated", "pending_review"):
            raise ValueError("Unexpected annotation status")
        if row["task"] not in ("NER", "SEG"):
            raise ValueError("Unknown task")
        per_doc[doc_id].append(row)
    raw_quarantine = [q for q in quarantined if q.get("record_type") == "raw_source_occurrence"]
    normalized_quarantine = [q for q in quarantined if q.get("reason") == "unresolved_source_text_integrity"]
    phases = {}
    labels = {}
    by_doc = []
    for phase in ("phase_1", "phase_2"):
        group = [doc for doc in docs if doc["phase"] == phase]
        if not group:
            continue
        chars = sum(len(doc["text"]) for doc in group)
        all_rows = [item for doc in group for item in per_doc[doc["document_id"]]]
        status = Counter(item["status"] for item in all_rows)
        by_task = {}
        for task in ("NER", "SEG"):
            task_rows = [item for item in all_rows if item["task"] == task]
            by_task[task] = {
                "consolidated": sum(r["status"] == "consolidated" for r in task_rows),
                "pending_review": sum(r["status"] == "pending_review" for r in task_rows),
                "potential_in_snapshot": len(task_rows),
                "per_document": len(task_rows) / len(group),
                "per_10000_characters": len(task_rows) * 10000 / chars if chars else 0,
            }
        seg_intervals = [(r["document_id"], r["start"], r["end"])
                         for r in all_rows if r["task"] == "SEG"]
        seg_by_doc = defaultdict(list)
        for doc_id, start, end in seg_intervals:
            seg_by_doc[doc_id].append((start, end))
        covered = sum(_covered(seg_by_doc[doc["document_id"]]) for doc in group)
        length_dist = _distribution([len(doc["text"]) for doc in group])
        seg_counts = _distribution([
            sum(r["task"] == "SEG" for r in per_doc[doc["document_id"]])
            for doc in group
        ])
        phases[phase] = {
            "document_count": len(group),
            "characters_total": chars,
            "text_length_distribution": length_dist,
            "annotations_in_snapshot": len(all_rows),
            "status_counts": dict(sorted(status.items())),
            "task_counts": by_task,
            "segmentation_covered_characters": covered,
            "segmentation_character_coverage_fraction": covered / chars if chars else None,
            "segmentation_spans_per_document_distribution": seg_counts,
        }
        for doc in group:
            doc_id = doc["document_id"]
            rows = per_doc[doc_id]
            seg = [r for r in rows if r["task"] == "SEG"]
            by_doc.append({
                "document_id": doc_id,
                "phase": phase,
                "characters": len(doc["text"]),
                "ner_potential": sum(r["task"] == "NER" for r in rows),
                "seg_potential": len(seg),
                "ner_consolidated": sum(r["task"] == "NER" and r["status"] == "consolidated" for r in rows),
                "seg_consolidated": sum(r["task"] == "SEG" and r["status"] == "consolidated" for r in rows),
                "seg_covered_chars": _covered((r["start"], r["end"]) for r in seg),
                "seg_covered_fraction": (_covered((r["start"], r["end"]) for r in seg) / len(doc["text"])
                                         if doc["text"] else None),
            })
        for item in all_rows:
            key = (item["task"], item["label"])
            labels.setdefault(key, {
                "task": item["task"], "label": item["label"],
                "phase_1_consolidated": 0,
                "phase_1_pending": 0,
                "phase_2_consolidated": 0,
                "phase_2_pending": 0,
            })
            bucket = f"{phase}_consolidated" if item["status"] == "consolidated" else f"{phase}_pending"
            labels[key][bucket] += 1
    # Include all taxonomy labels from the snapshot, even if absent in both phases.
    taxonomy = root.parent  # taxonomy file not guaranteed to be stored in snapshot
    del taxonomy
    frequency_rows = []
    for item in sorted(labels.values(), key=lambda x: (x["task"], x["label"])):
        p1 = item["phase_1_consolidated"] + item["phase_1_pending"]
        p2 = item["phase_2_consolidated"] + item["phase_2_pending"]
        frequency_rows.append({
            **item,
            "phase_1_potential": p1,
            "phase_2_potential": p2,
            "total_potential_in_snapshot": p1 + p2,
            "phase_2_pending_share": item["phase_2_pending"] / p2 if p2 else None,
            "phase_1_documents_support": len({
                r["document_id"] for r in spans
                if r["phase"] == "phase_1" and r["label"] == item["label"] and r["task"] == item["task"]
            }),
            "phase_2_documents_support": len({
                r["document_id"] for r in spans
                if r["phase"] == "phase_2" and r["label"] == item["label"] and r["task"] == item["task"]
            }),
        })
    return {
        "schema_version": "1.0.0",
        "corpus_version": manifest.get("corpus_version"),
        "dataset_manifest_sha256": hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
        "analysis_mode": "potential_includes_pending_not_gold",
        "counts_may_change_after_adjudication": True,
        "by_phase": phases,
        "labels": frequency_rows,
        "documents": sorted(by_doc, key=lambda r: r["document_id"]),
        "quarantine": {
            "normalized_rows": len(normalized_quarantine),
            "raw_source_occurrences": len(raw_quarantine),
            "total_records": len(quarantined),
            "normalized_by_task": dict(sorted(Counter(q["task"] for q in normalized_quarantine).items())),
            "raw_occurrences_by_task": dict(sorted(Counter(q["task"] for q in raw_quarantine).items())),
            "warning": "Quarantined rows excluded from potential frequencies; raw occurrences are not new unique spans",
        },
        "interpretation": (
            "Potential frequency includes consolidated and pending_review without "
            "assuming pending labels will survive. Segmentation coverage is a union "
            "of half-open intervals, not a partition completeness assertion."
        ),
    }


def write_report(snapshot_dir, output):
    result = compare_phase_coverage(snapshot_dir)
    target = Path(output)
    if target.exists():
        raise FileExistsError("Refusing to overwrite existing report")
    if not target.parent.is_dir():
        raise FileNotFoundError("Output directory must already exist")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = write_report(args.snapshot, args.output)
    print(json.dumps({
        "corpus_version": result["corpus_version"],
        "by_phase": result["by_phase"],
        "quarantine": result["quarantine"],
        "label_count_with_support": len(result["labels"]),
        "report": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
