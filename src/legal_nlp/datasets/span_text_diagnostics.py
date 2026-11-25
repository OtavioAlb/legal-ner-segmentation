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

from ..io.label_studio import extract, load
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
    sources = {
        "original": load(original_path),
        "11": load(evaluation_11),
        "17": load(evaluation_17),
    }
    if not sources["original"] or any(
        set(sources[project]) != set(sources["original"])
        for project in ("11", "17")
    ):
        raise ValueError("Document sets differ")
    texts = {doc: _text_from_task(task) for doc, task in sources["original"].items()}
    findings = []
    counts = Counter()
    candidates = 0
    for project in ("original", "11", "17"):
        for doc in sorted(sources[project], key=int):
            spans, choices, _ = extract(sources[project][doc])
            text = texts[doc]
            for rid, region in spans.items():
                candidates += 1
                start, end = region["start"], region["end"]
                actual = region["text"]
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                    category = "invalid_offsets"
                    expected = ""
                elif not actual:
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
                    "project": project,
                    "label": region["label"],
                    "start": start,
                    "end": end,
                    "document_length": len(text),
                    "category": category,
                    "source_text_length": len(actual),
                    "document_slice_length": len(expected),
                    "checkbox": choices.get(rid),
                }
                if include_excerpts:
                    finding["source_text_repr"] = repr(actual[:excerpt_limit])
                    finding["document_slice_repr"] = repr(expected[:excerpt_limit])
                findings.append(finding)
    return {
        "diagnostic_version": "1.0.0",
        "candidate_count": candidates,
        "categories": dict(sorted(counts.items())),
        "reference_excerpt_unavailable_is_not_failure": True,
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
