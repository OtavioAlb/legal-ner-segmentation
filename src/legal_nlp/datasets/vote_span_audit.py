"""Read-only empirical audit of vote-related ENT/SEG spans in both phases.

Distinguishes taxonomy availability, snapshot occurrence, and raw Label Studio
source occurrence. No inferred label migration, edits, or gold promotion.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from ..io.jsonl import read_jsonl
from ..io.label_studio import extract, load

LABELS = (
    "ENT_DECISAO_VOTO_VENCEDOR",
    "ENT_DECISAO_VOTO_VENCIDO",
    "SEG_DECISAO_VOTO_VENCEDOR",
    "SEG_DECISAO_VOTO_VENCIDO",
    "SEG_JURISPRUDENCIA_VOTO_VENCEDOR",
    "SEG_JURISPRUDENCIA_VOTO_VENCIDO",
)
VOTE_ENT = {"ENT_DECISAO_VOTO_VENCEDOR", "ENT_DECISAO_VOTO_VENCIDO"}


def _dist(values):
    if not values:
        return {"n": 0, "min": None, "median": None, "mean": None,
                "p90": None, "max": None}
    values = sorted(values)
    p90_idx = (len(values) - 1) * .9
    low = int(p90_idx)
    alpha = p90_idx - low
    return {"n": len(values), "min": values[0],
            "median": statistics.median(values), "mean": statistics.mean(values),
            "p90": values[low] * (1 - alpha) + values[min(low + 1, len(values) - 1)] * alpha,
            "max": values[-1]}


def _overlap(a, b):
    return max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def analyze_votes(snapshot_dir, original=None, review_11=None, review_17=None):
    root = Path(snapshot_dir)
    manifest = json.loads((root / "dataset_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("training_ready") is not False:
        raise ValueError("This audit requires a diagnostic, non-training snapshot")
    docs_list = read_jsonl(root / "documents.jsonl")
    annotations = read_jsonl(root / "annotations.jsonl")
    quarantine_file = root / "quarantine.jsonl"
    quarantine = read_jsonl(quarantine_file) if quarantine_file.exists() else []
    if len(docs_list) != manifest["document_count"] or len(annotations) != manifest["annotation_count"]:
        raise ValueError("Manifest row counts disagree")
    docs = {doc["document_id"]: doc for doc in docs_list}
    if len(docs) != len(docs_list):
        raise ValueError("Duplicate document")
    by_doc = defaultdict(list)
    for row in annotations:
        if row["document_id"] not in docs:
            raise ValueError("Orphan annotation")
        by_doc[row["document_id"]].append(row)
    label_stats = []
    rows = []
    for phase in ("phase_1", "phase_2"):
        phase_docs = [d for d in docs_list if d["phase"] == phase]
        for label in LABELS:
            group = [r for d in phase_docs for r in by_doc[d["document_id"]]
                     if r["label"] == label]
            lengths = [r["end"] - r["start"] for r in group]
            word_counts = [len(r["text"].split()) for r in group]
            ratios = [(r["end"] - r["start"]) / len(docs[r["document_id"]]["text"])
                      for r in group]
            label_stats.append({
                "phase": phase, "label": label, "task": label.split("_", 1)[0],
                "occurrences": len(group),
                "consolidated": sum(r["status"] == "consolidated" for r in group),
                "pending_review": sum(r["status"] == "pending_review" for r in group),
                "documents_with_label": len({r["document_id"] for r in group}),
                "character_lengths": _dist(lengths),
                "word_counts": _dist(word_counts),
                "document_fraction": _dist(ratios),
            })
            for row in group:
                doc = docs[row["document_id"]]
                segs = [r for r in by_doc[row["document_id"]] if r["task"] == "SEG"]
                overlaps = [
                    {
                        "label": seg["label"],
                        "overlap_characters": n,
                        "entity_contained_by_segment": (
                            seg["start"] <= row["start"] and row["end"] <= seg["end"]
                        ),
                        "segment_contained_by_entity": (
                            row["start"] <= seg["start"] and seg["end"] <= row["end"]
                        ),
                    }
                    for seg in segs if (n := _overlap(row, seg)) > 0
                ]
                rows.append({
                    "document_id": row["document_id"], "phase": phase,
                    "region_id": row["region_id"], "label": label, "task": row["task"],
                    "status": row["status"], "start": row["start"], "end": row["end"],
                    "characters": row["end"] - row["start"],
                    "words": len(row["text"].split()),
                    "document_characters": len(doc["text"]),
                    "document_fraction": (row["end"] - row["start"]) / len(doc["text"]),
                    "text_position_fraction": row["start"] / len(doc["text"]),
                    "overlapping_segments": overlaps,
                    "spans_newline": "\n" in row["text"],
                })
    raw_counts = None
    if any(x is not None for x in (original, review_11, review_17)):
        if not all(x is not None for x in (original, review_11, review_17)):
            raise ValueError("Provide all 3 exports or none")
        exports = {"original": load(original), "11": load(review_11), "17": load(review_17)}
        keys = set(exports["original"])
        if not keys or any(set(export) != keys for export in exports.values()):
            raise ValueError("Document sets differ")
        raw_counts = {}
        for project, export in exports.items():
            count = Counter()
            docsets = defaultdict(set)
            for doc_id, task in export.items():
                spans, _, _ = extract(task)
                for region in spans.values():
                    if region["label"] in LABELS:
                        count[region["label"]] += 1
                        docsets[region["label"]].add(doc_id)
            raw_counts[project] = {
                label: {"region_occurrences": count[label],
                        "documents_with_label": len(docsets[label])}
                for label in LABELS
            }
    quarantined = [
        q for q in quarantine
        if q.get("reason") == "unresolved_source_text_integrity"
        and q.get("label") in LABELS
    ]
    return {
        "schema_version": "1.0.0",
        "corpus_version": manifest.get("corpus_version"),
        "basis": "both_consolidated_and_pending; not gold",
        "label_statistics": label_stats,
        "spans": rows,
        "phase2_raw_label_counts": raw_counts,
        "vote_labels_in_quarantined_normalized_rows": [
            {k: q.get(k) for k in ("document_id", "region_id", "label", "task",
                                  "start", "end", "source_status")}
            for q in quarantined
        ],
        "interpretation_limits": [
            "Label prefix alone does not establish semantic function.",
            "Span length and overlap indicate structural use, not definitive label migration.",
            "Zero occurrences in a snapshot do not mean a label was unavailable.",
            "Raw exports count region occurrences by project, not unique candidate spans.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--evaluation-11", type=Path)
    parser.add_argument("--evaluation-17", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze_votes(args.snapshot, args.original,
                           args.evaluation_11, args.evaluation_17)
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite existing report")
    if not args.output.parent.is_dir():
        raise FileNotFoundError("Output directory must exist")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "labels": result["label_statistics"],
        "raw_label_counts": result["phase2_raw_label_counts"],
        "quarantined_vote_rows": len(result["vote_labels_in_quarantined_normalized_rows"]),
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
