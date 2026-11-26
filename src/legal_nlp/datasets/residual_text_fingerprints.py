"""Inspect residual Label Studio text mismatches without changing annotations.

Detailed diagnostics are metadata-only by default; no source text is included.
Grouping is by decision + region ID, retaining every project's independent
evidence. A matching similarity heuristic is never treated as adjudication.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from ..io.label_studio import extract, load
from .span_text_diagnostics import _classify
from .versioned_corpus import _text_from_task


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint(source: str, expected: str) -> dict:
    """Metadata-only edit diagnostics, never a text correction."""
    matcher = difflib.SequenceMatcher(a=source, b=expected, autojunk=False)
    changes = [(tag, a0, a1, b0, b1) for tag, a0, a1, b0, b1
               in matcher.get_opcodes() if tag != "equal"]
    edit_counts = Counter()
    for tag, a0, a1, b0, b1 in changes:
        edit_counts[tag] += 1
    first = changes[0] if changes else None
    return {
        "source_sha256": _digest(source),
        "document_slice_sha256": _digest(expected),
        "source_length": len(source),
        "document_slice_length": len(expected),
        "length_difference": len(source) - len(expected),
        "first_difference_source_position": first[1] if first else None,
        "first_difference_document_position": first[3] if first else None,
        "edit_operation_counts": dict(sorted(edit_counts.items())),
        "edit_operations": [
            {"operation": tag,
             "source_start": a0, "source_end": a1,
             "document_start": b0, "document_end": b1,
             "source_chars": a1 - a0, "document_chars": b1 - b0}
            for tag, a0, a1, b0, b1 in changes
        ],
        "unicode_nfc_equivalent": (
            unicodedata.normalize("NFC", source)
            == unicodedata.normalize("NFC", expected)
        ),
        "unicode_nfkc_equivalent": (
            unicodedata.normalize("NFKC", source)
            == unicodedata.normalize("NFKC", expected)
        ),
        "whitespace_insensitive_equivalent": (
            "".join(source.split()) == "".join(expected.split())
        ),
        "html_entity_equivalent": html.unescape(source) == expected,
    }


def character_operations(source: str, expected: str) -> list[dict]:
    """Provide exact changed Unicode codepoints, with no surrounding text.

    Intended only for locally stored private diagnostic output. The codepoints
    can still reveal content; never commit the output to version control.
    """
    matcher = difflib.SequenceMatcher(a=source, b=expected, autojunk=False)
    changes = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append({
            "operation": tag,
            "source_range": [a0, a1],
            "document_range": [b0, b1],
            "source_codepoints": [
                {"codepoint": f"U+{ord(char):04X}",
                 "unicode_name": unicodedata.name(char, "UNASSIGNED")}
                for char in source[a0:a1]
            ],
            "document_codepoints": [
                {"codepoint": f"U+{ord(char):04X}",
                 "unicode_name": unicodedata.name(char, "UNASSIGNED")}
                for char in expected[b0:b1]
            ],
        })
    return changes


def inspect_residuals(original, review_11, review_17, *, include_codepoints=False) -> dict:
    exports = {
        "original": load(original),
        "11": load(review_11),
        "17": load(review_17),
    }
    ids = set(exports["original"])
    if not ids or any(set(exports[p]) != ids for p in ("11", "17")):
        raise ValueError("Document sets differ")
    texts = {doc: _text_from_task(task) for doc, task in exports["original"].items()}
    groups = defaultdict(list)
    occurrence_count = Counter()
    for project in ("original", "11", "17"):
        for doc in sorted(ids, key=int):
            spans, choices, _ = extract(exports[project][doc])
            for rid, span in spans.items():
                start, end = span["start"], span["end"]
                text = texts[doc]
                if end > len(text):
                    continue  # invalid offsets handled in the primary diagnostic
                raw, expected = span["text"], text[start:end]
                category = _classify(raw, expected) if raw else "reference_excerpt_unavailable"
                if category != "other_mismatch":
                    continue
                occurrence_count[project] += 1
                item = {
                    "project": project,
                    "label": span["label"],
                    "start": start, "end": end,
                    "checkbox": choices.get(rid),
                    "category": category,
                    "fingerprint": fingerprint(raw, expected),
                }
                if include_codepoints:
                    item["character_operations"] = character_operations(raw, expected)
                groups[(doc, rid)].append(item)
    result = [
        {"idacordao": doc, "region_id": rid,
         "projects": sorted(rows, key=lambda item:
                            {"original": 0, "11": 1, "17": 2}[item["project"]])}
        for (doc, rid), rows in sorted(groups.items(), key=lambda item:
                                       (int(item[0][0]), item[0][1]))
    ]
    return {
        "schema_version": "1.0.0",
        "scope": "other_mismatch only",
        "codepoints_included": include_codepoints,
        "occurrences": sum(occurrence_count.values()),
        "unique_regions_by_document_and_region_id": len(result),
        "by_project": dict(sorted(occurrence_count.items())),
        "regions": result,
        "source_correction_performed": False,
        "automatic_adjudication_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--evaluation-11", required=True, type=Path)
    parser.add_argument("--evaluation-17", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--include-codepoints", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite existing diagnostic report")
    if not args.output.parent.is_dir():
        raise FileNotFoundError("Create the output directory first")
    result = inspect_residuals(
        args.original, args.evaluation_11, args.evaluation_17,
        include_codepoints=args.include_codepoints,
    )
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "occurrences": result["occurrences"],
        "unique_regions": result["unique_regions_by_document_and_region_id"],
        "by_project": result["by_project"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
