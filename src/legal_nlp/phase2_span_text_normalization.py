"""Normalize demonstrably escaped Label Studio span text in private derived JSON.

No source export, document text, label, span boundary, or reviewer decision is
changed. All transformations require an exact match after decoding escapes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _read(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        raise ValueError(f"Expected JSON array of objects: {path}")
    return value


def _decode_escapes(value: str) -> str:
    return (value.replace("\\r\\n", "\r\n")
                 .replace("\\n", "\n")
                 .replace("\\r", "\r")
                 .replace("\\t", "\t"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_rows(rows: list[dict[str, Any]], stage: str
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Return modified copies, text-free provenance and mismatch statistics."""
    output = copy.deepcopy(rows)
    actions: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row_index, row in enumerate(output):
        data = row.get("data")
        document_text = data.get("acordao") if isinstance(data, dict) else None
        decision_id = data.get("idacordao") if isinstance(data, dict) else None
        annotations = row.get("annotations")
        if not isinstance(annotations, list):
            counts["malformed_annotation_container"] += 1
            continue
        for annotation_index, annotation in enumerate(annotations):
            if not isinstance(annotation, dict) or not isinstance(annotation.get("result"), list):
                counts["malformed_annotation_container"] += 1
                continue
            for result_index, result in enumerate(annotation["result"]):
                if not isinstance(result, dict) or result.get("type") != "labels":
                    continue
                value = result.get("value")
                if not isinstance(value, dict):
                    counts["malformed_labeled_span"] += 1
                    continue
                start, end, excerpt = value.get("start"), value.get("end"), value.get("text")
                if not (isinstance(document_text, str) and isinstance(excerpt, str)
                        and isinstance(start, int) and not isinstance(start, bool)
                        and isinstance(end, int) and not isinstance(end, bool)
                        and 0 <= start < end <= len(document_text)):
                    counts["unverifiable_span"] += 1
                    continue
                counts["checked_spans"] += 1
                actual = document_text[start:end]
                if excerpt == actual:
                    counts["already_exact"] += 1
                    continue
                decoded = _decode_escapes(excerpt)
                if decoded != excerpt and decoded == actual:
                    value["text"] = actual
                    counts["normalized"] += 1
                    actions.append({
                        "stage": stage, "row_index": row_index,
                        "idacordao": decision_id, "task_id": row.get("id"),
                        "annotation_index": annotation_index, "result_index": result_index,
                        "start": start, "end": end,
                        "source_text_sha256": _sha(excerpt),
                        "normalized_text_sha256": _sha(actual),
                        "action": "decode_literal_escapes_exact_offset_match",
                    })
                else:
                    counts["unresolved_mismatch"] += 1
    return output, actions, dict(sorted(counts.items()))


def normalize_files(original_path: str | Path, evaluations_path: str | Path,
                    output_dir: str | Path, expected_normalizations: int | None = None
                    ) -> dict[str, Any]:
    originals = Path(original_path)
    evaluations = Path(evaluations_path)
    target = Path(output_dir)
    outputs = (target / "original_normalized.json", target / "evaluations_normalized.json",
               target / "normalization_actions.jsonl", target / "normalization_summary.json")
    inputs = (originals, evaluations)
    if len({p.resolve() for p in (*inputs, *outputs)}) != 6:
        raise ValueError("Input and output paths must all be distinct")
    if expected_normalizations is not None and expected_normalizations < 0:
        raise ValueError("Expected normalizations must be nonnegative")
    processed, summaries, actions = [], {}, []
    for stage, source in (("original", originals), ("evaluation", evaluations)):
        rows, changes, summary = normalize_rows(_read(source), stage)
        processed.append(rows)
        actions.extend(changes)
        summaries[stage] = summary
    total = len(actions)
    if expected_normalizations is not None and total != expected_normalizations:
        raise ValueError(f"Expected {expected_normalizations} normalizations, found {total}; nothing written")
    target.mkdir(parents=True, exist_ok=True)
    for path, rows in zip(outputs[:2], processed):
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with outputs[2].open("w", encoding="utf-8", newline="\n") as handle:
        for item in actions:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema_version": "1.0.0",
        "summary_by_stage": summaries,
        "total_normalized": total,
        "total_unresolved_mismatches": sum(
            s.get("unresolved_mismatch", 0) for s in summaries.values()
        ),
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "policy": "Source files unchanged; edit derived value.text only on proven exact-offset match; no offset shifts",
    }
    outputs[3].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--evaluations", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-normalizations", type=int)
    args = parser.parse_args(argv)
    print(json.dumps(normalize_files(args.original, args.evaluations, args.output,
                                     args.expected_normalizations), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
