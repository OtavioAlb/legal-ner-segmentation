"""Privacy-preserving diagnostics for Phase 2 text/offset mismatches.

Read-only. Never outputs document text, snippets or annotation excerpts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .audit import classify_mismatch


def _read_json(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
        raise ValueError(f"Expected array of objects: {path}")
    return rows


def _slice_utf16(text: str, start: int, end: int) -> str | None:
    try:
        raw = text.encode("utf-16-le")
        return raw[2 * start:2 * end].decode("utf-16-le")
    except UnicodeError:
        return None


def _slice_utf8(text: str, start: int, end: int) -> str | None:
    try:
        return text.encode("utf-8")[start:end].decode("utf-8")
    except UnicodeError:
        return None


def _nearby_positions(text: str, target: str, start: int, end: int, radius: int) -> list[int]:
    lower, upper = max(0, start - radius), min(len(text), end + radius)
    found: list[int] = []
    pos = text.find(target, lower, upper)
    while pos != -1 and len(found) < 3:
        found.append(pos)
        pos = text.find(target, pos + 1, upper)
    return found


def _reason(text: str, start: int, end: int, excerpt: str, radius: int
            ) -> tuple[str, int | None]:
    selected = text[start:end]
    decoded = excerpt.replace("\\r\\n", "\r\n").replace("\\n", "\n").replace(
        "\\r", "\r").replace("\\t", "\t")
    if decoded != excerpt and decoded == selected:
        return "literal_backslash_escapes", None
    if _slice_utf16(text, start, end) == excerpt:
        return "utf16_code_unit_offsets", None
    if _slice_utf8(text, start, end) == excerpt:
        return "utf8_byte_offsets", None
    if not excerpt:
        return "empty_excerpt", None
    near = _nearby_positions(text, excerpt, start, end, radius)
    if len(near) == 1:
        return "unique_nearby_exact_match", near[0] - start
    if len(near) > 1:
        return "ambiguous_nearby_exact_matches", None
    global_pos = text.find(excerpt)
    if global_pos != -1:
        if text.find(excerpt, global_pos + 1) == -1:
            return "unique_distant_exact_match", global_pos - start
        return "ambiguous_distant_exact_matches", None
    return "excerpt_not_found_in_document", None


def diagnose(original: str | Path, evaluations: str | Path, output: str | Path,
             radius: int = 200) -> dict[str, Any]:
    if radius < 0:
        raise ValueError("radius cannot be negative")
    original, evaluations, output = Path(original), Path(evaluations), Path(output)
    if original.resolve() == evaluations.resolve() or output.resolve() in {
        original.resolve(), evaluations.resolve()
    }:
        raise ValueError("Source and output paths must be distinct")
    original_rows, evaluation_rows = _read_json(original), _read_json(evaluations)
    checked = Counter()
    mismatches = Counter()
    reasons = Counter()
    mismatch_tasks = Counter()
    mismatch_project = Counter()
    mismatch_docs: set[str] = set()
    length_delta = Counter()
    shift_counts = Counter()
    cases = []

    for stage, rows in (("original", original_rows), ("evaluation", evaluation_rows)):
        for row in rows:
            data = row.get("data")
            doc_id = str(data.get("idacordao", "")) if isinstance(data, dict) else ""
            text = data.get("acordao") if isinstance(data, dict) else None
            if not isinstance(text, str):
                continue
            for annotation in row.get("annotations") or []:
                if not isinstance(annotation, dict):
                    continue
                for index, item in enumerate(annotation.get("result") or []):
                    if not isinstance(item, dict) or item.get("type") != "labels":
                        continue
                    value = item.get("value")
                    if not isinstance(value, dict):
                        continue
                    start, end = value.get("start"), value.get("end")
                    excerpt = value.get("text")
                    if not (
                        isinstance(start, int) and not isinstance(start, bool)
                        and isinstance(end, int) and not isinstance(end, bool)
                        and 0 <= start < end <= len(text) and isinstance(excerpt, str)
                    ):
                        continue
                    checked[stage] += 1
                    if text[start:end] == excerpt:
                        continue
                    mismatches[stage] += 1
                    mismatch_docs.add(doc_id)
                    project = str(row.get("project", "original"))
                    mismatch_project[project] += 1
                    labels = value.get("labels")
                    label = labels[0] if isinstance(labels, list) and labels else ""
                    category = "NER" if label.startswith("ENT_") else (
                        "SEG" if label.startswith("SEG_") else "UNKNOWN")
                    mismatch_tasks[category] += 1
                    kind, delta = _reason(text, start, end, excerpt, radius)
                    reasons[kind] += 1
                    length_delta[len(excerpt) - (end - start)] += 1
                    if delta is not None:
                        shift_counts[delta] += 1
                    cases.append({
                        "stage": stage, "project": project, "idacordao": doc_id,
                        "task_id": row.get("id"), "result_index": index,
                        "task": category,
                        "start": start, "end": end,
                        "offset_length": end - start,
                        "excerpt_length": len(excerpt),
                        "mismatch_type": classify_mismatch(text[start:end], excerpt),
                        "diagnostic": kind, "candidate_shift": delta,
                    })

    output.mkdir(parents=True, exist_ok=True)
    with (output / "mismatch_diagnostics.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema_version": "1.0",
        "span_results_checked_by_stage": dict(sorted(checked.items())),
        "mismatches_by_stage": dict(sorted(mismatches.items())),
        "total_mismatches": len(cases),
        "documents_with_mismatches": len(mismatch_docs),
        "mismatches_by_project": dict(sorted(mismatch_project.items())),
        "mismatches_by_task": dict(sorted(mismatch_tasks.items())),
        "diagnostic_reasons": dict(sorted(reasons.items())),
        "length_differences_top": [
            {"length_delta": delta, "count": count}
            for delta, count in length_delta.most_common(15)
        ],
        "candidate_shifts_top": [
            {"shift": delta, "count": count}
            for delta, count in shift_counts.most_common(15)
        ],
        "radius": radius,
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (original, evaluations)
        },
        "method": (
            "Diagnostics only: no automatic corrections; local exact match is "
            "not proof of a valid revised offset; reports exclude all text"
        ),
    }
    (output / "mismatch_summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--evaluations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--radius", type=int, default=200)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.original, args.evaluations, args.output,
                              args.radius), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
