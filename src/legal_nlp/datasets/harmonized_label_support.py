"""Read-only support audit of the derived vote-harmonized diagnostic view.

No gold promotion, training splits, label removal, threshold-based class
merging, or changes to source records. Reports contain no judicial excerpts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from ..io.jsonl import read_jsonl
from .vote_harmonization import PHASE1_VOTE_MAP


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_and_load(snapshot, harmonized, taxonomy):
    snapshot, harmonized, taxonomy = Path(snapshot), Path(harmonized), Path(taxonomy)
    source_manifest = json.loads((snapshot / "dataset_manifest.json").read_text(encoding="utf-8"))
    derived = json.loads((harmonized / "harmonization_manifest.json").read_text(encoding="utf-8"))
    if source_manifest.get("kind") != "diagnostic_snapshot" or source_manifest.get("training_ready") is not False:
        raise ValueError("Expected original diagnostic snapshot")
    if derived.get("kind") != "derived_diagnostic_label_view" or derived.get("training_ready") is not False:
        raise ValueError("Expected derived non-training diagnostic view")
    for name, sha in derived.get("source_sha256", {}).items():
        if _sha(snapshot / name) != sha:
            raise ValueError(f"Source checksum changed: {name}")
    if not all(k in derived.get("source_sha256", {}) for k in (
        "dataset_manifest.json", "annotations.jsonl", "documents.jsonl"
    )):
        raise ValueError("Missing source checksums in view")
    docs = read_jsonl(snapshot / "documents.jsonl")
    original = read_jsonl(snapshot / "annotations.jsonl")
    rows = read_jsonl(harmonized / "annotations_harmonized.jsonl")
    if (len(docs) != source_manifest.get("document_count")
            or len(original) != source_manifest.get("annotation_count")
            or len(rows) != derived.get("output_annotations")
            or len(original) != len(rows)
            or len(rows) != derived.get("source_annotations")):
        raise ValueError("Document or annotation count mismatch")
    docmap = {d["document_id"]: d for d in docs}
    if len(docmap) != len(docs):
        raise ValueError("Duplicate document identifier")
    taxonomy_data = json.loads(taxonomy.read_text(encoding="utf-8"))
    labels = taxonomy_data["labels"]
    if len(set(labels)) != len(labels) or not all(
        name.startswith(("ENT_", "SEG_")) for name in labels
    ):
        raise ValueError("Invalid canonical taxonomy")
    expected_mapped = 0
    for before, after in zip(original, rows):
        if before["document_id"] not in docmap:
            raise ValueError("Unknown document id")
        if not all(before.get(field) == after.get(field) for field in (
            "document_id", "phase", "region_id", "status", "start", "end",
            "text", "source_status", "provenance"
        )):
            raise ValueError("Source provenance, geometry or status changed")
        if after.get("source_label") != before["label"] or after.get("source_task") != before["task"]:
            raise ValueError("Original label/task not retained")
        target = PHASE1_VOTE_MAP.get(before["label"]) if before["phase"] == "phase_1" else None
        expected_label = target or before["label"]
        expected_task = "NER" if target else before["task"]
        if after["label"] != expected_label or after["task"] != expected_task:
            raise ValueError("Unexpected harmonization policy")
        if after["label"] not in labels or after["status"] not in ("consolidated", "pending_review"):
            raise ValueError("Unexpected label/status in harmonized view")
        if after["task"] != ("NER" if after["label"].startswith("ENT_") else "SEG"):
            raise ValueError("Task prefix conflict")
        text = docmap[after["document_id"]]["text"]
        start, end = after["start"], after["end"]
        if not (type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                and text[start:end] == after["text"]):
            raise ValueError("Span offsets/text mismatch")
        if target:
            expected_mapped += 1
    if expected_mapped != derived.get("mapped_count"):
        raise ValueError("Mapped count inconsistent with derived manifest")
    return docs, rows, labels, source_manifest, derived


def analyze_support(snapshot, harmonized, taxonomy):
    docs, rows, labels, source_manifest, derived = _validate_and_load(
        snapshot, harmonized, taxonomy
    )
    groups = defaultdict(list)
    lengths_by_phase = Counter()
    documents_by_phase = Counter()
    for doc in docs:
        phase = doc["phase"]
        if phase not in ("phase_1", "phase_2"):
            raise ValueError("Unknown phase")
        lengths_by_phase[phase] += len(doc["text"])
        documents_by_phase[phase] += 1
    for row in rows:
        groups[(row["task"], row["label"], row["phase"])].append(row)

    per_label = []
    for label in labels:
        task = "NER" if label.startswith("ENT_") else "SEG"
        summary = {"task": task, "label": label}
        for phase in ("phase_1", "phase_2"):
            group = groups[(task, label, phase)]
            con = sum(r["status"] == "consolidated" for r in group)
            pend = sum(r["status"] == "pending_review" for r in group)
            docs_with = {r["document_id"] for r in group}
            summary[phase] = {
                "consolidated": con,
                "pending_review": pend,
                "potential": len(group),
                "documents_with_support": len(docs_with),
                "documents_without_support": documents_by_phase[phase] - len(docs_with),
                "potential_per_10000_characters": (
                    10000 * len(group) / lengths_by_phase[phase]
                    if lengths_by_phase[phase] else 0
                ),
            }
        p1, p2 = summary["phase_1"]["potential"], summary["phase_2"]["potential"]
        total = p1 + p2
        summary["total_consolidated"] = (summary["phase_1"]["consolidated"]
                                         + summary["phase_2"]["consolidated"])
        summary["total_pending_review"] = (summary["phase_1"]["pending_review"]
                                           + summary["phase_2"]["pending_review"])
        summary["total_potential"] = total
        summary["documents_with_support_total"] = (
            summary["phase_1"]["documents_with_support"]
            + summary["phase_2"]["documents_with_support"]
        )
        summary["phase_presence"] = (
            "both" if p1 and p2 else
            "phase_1_only" if p1 else
            "phase_2_only" if p2 else "neither"
        )
        summary["descriptive_support_band"] = (
            "zero" if total == 0 else
            "1-4" if total < 5 else
            "5-9" if total < 10 else
            "10-29" if total < 30 else
            "30-99" if total < 100 else "100+"
        )
        summary["phase_2_pending_share"] = (
            summary["phase_2"]["pending_review"] / p2 if p2 else None
        )
        per_label.append(summary)

    by_phase_task_status = Counter(
        (r["phase"], r["task"], r["status"]) for r in rows
    )
    diagnostics = {}
    for task in ("NER", "SEG"):
        items = [r for r in per_label if r["task"] == task]
        diagnostics[task] = {
            "taxonomy_labels": len(items),
            "labels_with_support": sum(x["total_potential"] > 0 for x in items),
            "zero_support": sorted(x["label"] for x in items if x["total_potential"] == 0),
            "labels_with_under_10_potential": sorted(x["label"] for x in items
                                                     if 0 < x["total_potential"] < 10),
            "phase_1_only": sorted(x["label"] for x in items
                                   if x["phase_presence"] == "phase_1_only"),
            "phase_2_only": sorted(x["label"] for x in items
                                   if x["phase_presence"] == "phase_2_only"),
            "both": sum(x["phase_presence"] == "both" for x in items),
        }
    quarantine = {
        "raw_record_count": source_manifest.get("quarantine_record_count", 0),
        "normalized_rows": source_manifest.get("quarantine_normalized_rows", 0),
        "included_in_support": False,
    }
    return {
        "schema_version": "1.0.0",
        "mode": "diagnostic_potential_not_gold",
        "training_ready": False,
        "source_corpus_version": source_manifest.get("corpus_version"),
        "taxonomy_version": json.loads(Path(taxonomy).read_text(encoding="utf-8")).get("schema_version"),
        "source_view_manifest_sha256": _sha(Path(harmonized) / "harmonization_manifest.json"),
        "source_view_annotations_sha256": _sha(Path(harmonized) / "annotations_harmonized.jsonl"),
        "documents": len(docs),
        "annotations": len(rows),
        "mapped_count": derived["mapped_count"],
        "totals": [
            {"phase": phase, "task": task, "status": status, "count": count}
            for (phase, task, status), count in sorted(by_phase_task_status.items())
        ],
        "documents_by_phase": dict(sorted(documents_by_phase.items())),
        "characters_by_phase": dict(sorted(lengths_by_phase.items())),
        "labels": per_label,
        "task_diagnostics": diagnostics,
        "quarantine": quarantine,
        "methodology": (
            "All consolidated and pending_review annotations count toward potential "
            "support; statuses are never merged into gold. Descriptive bands are "
            "not statistically validated minimum sample thresholds. Zero support "
            "means no occurrences in the harmonized diagnostic snapshot, not "
            "absence from source taxonomy or document meaning."
        ),
    }


def write_support_report(snapshot, harmonized, taxonomy, output):
    dest = Path(output)
    if dest.exists():
        raise FileExistsError("Refusing to overwrite report")
    if not dest.parent.is_dir():
        raise FileNotFoundError("Output directory parent must exist")
    report = analyze_support(snapshot, harmonized, taxonomy)
    dest.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--harmonized", required=True, type=Path)
    parser.add_argument("--taxonomy", default=Path("configs/labels.json"), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = write_support_report(args.snapshot, args.harmonized, args.taxonomy, args.output)
    print(json.dumps({
        "documents": report["documents"], "annotations": report["annotations"],
        "mapped_count": report["mapped_count"], "totals": report["totals"],
        "task_diagnostics": report["task_diagnostics"],
        "quarantine": report["quarantine"], "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
