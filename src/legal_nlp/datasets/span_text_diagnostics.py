"""Read-only diagnostics for Label Studio region-text versus document offsets.

No offset changes or automatic reconstruction. Summary excludes judicial text.
Detailed report can contain excerpts and must remain in gitignored data/.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..io.label_studio import load
from ..phase2_audit_v2 import audit
from .corpus_adapters import phase2_records
from .versioned_corpus import _text_from_task


def _classify(source: str, observed: str) -> str:
    if source == observed:
        return "exact"
    if source.replace("\\n", "\n").replace("\\t", "\t") == observed:
        return "literal_backslash_escapes_in_span"
    if source.replace("\r\n", "\n") == observed.replace("\r\n", "\n"):
        return "newline_style_difference"
    if source.strip() == observed.strip():
        return "edge_whitespace"
    if source.casefold() == observed.casefold():
        return "case_difference"
    return "other_mismatch"


def inspect_phase2_text(
    original_path: str | Path,
    evaluation_11: str | Path,
    evaluation_17: str | Path,
    *,
    include_excerpts: bool = False,
    excerpt_limit: int = 100,
) -> dict[str, Any]:
    """Inspect every normalized Phase 2 candidate, continuing after mismatches."""
    if excerpt_limit < 1:
        raise ValueError("excerpt_limit must be positive")
    tasks = load(original_path)
    sheets, audit_metrics, _ = audit(original_path, evaluation_11, evaluation_17)
    rows = phase2_records(sheets)
    texts = {doc: _text_from_task(task) for doc, task in tasks.items()}
    findings = []
    counts = Counter()
    for row in rows:
        doc, rid = row["document_id"], row["region_id"]
        start, end = row["start"], row["end"]
        text = texts[doc]
        actual = row["text"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            category = "invalid_offsets"
            expected = ""
        elif not actual:
            # Accepted review rows have no source excerpt in this adapter.
            # Empty source is NOT a successful text equality validation.
            category = "reference_excerpt_unavailable"
            expected = text[start:end]
        else:
            expected = text[start:end]
            category = _classify(actual, expected)
        counts[category] += 1
        if category == "exact":
            continue
        finding = {
            "idacordao": doc,
            "region_id": rid,
            "task": row["task"],
            "label": row["label"],
            "status": row["status"],
            "source_status": row["source_status"],
            "start": start,
            "end": end,
            "document_length": len(text),
            "category": category,
            "source_text_length": len(actual),
            "document_slice_length": len(expected),
            "project_id": row["provenance"].get("project_id") if isinstance(row["provenance"], dict) else None,
        }
        if include_excerpts:
            finding["source_text_repr"] = repr(actual[:excerpt_limit])
            finding["document_slice_repr"] = repr(expected[:excerpt_limit])
        findings.append(finding)
    return {
        "diagnostic_version": "1.0.0",
        "candidate_count": len(rows),
        "categories": dict(sorted(counts.items())),
        "reference_excerpt_unavailable_is_not_failure": True,
        "audit_originals": audit_metrics.get("originais"),
        "findings": findings,
        "source_correction_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--evaluation-11", type=Path, required=True)
    parser.add_argument("--evaluation-17", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-excerpts", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite existing diagnostic report")
    if not args.output.parent.is_dir():
        raise FileNotFoundError("Create the local output directory first")
    report = inspect_phase2_text(
        args.original, args.evaluation_11, args.evaluation_17,
        include_excerpts=args.include_excerpts,
    )
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(
        {"candidate_count": report["candidate_count"],
         "categories": report["categories"],
         "findings_count": len(report["findings"]),
         "output": str(args.output)},
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
