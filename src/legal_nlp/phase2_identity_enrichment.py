"""Enrich Phase 2 exports with private assignment-based identity labels.

Numeric Label Studio user IDs are preserved. Crosswalk assignments are
external private inputs and are not verified account identities.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

IDENTITY_FIELDS = (
    "annotator_name_inferred",
    "evaluator_1_name_assigned",
    "evaluator_2_name_assigned",
    "evaluator_1_assignment_listed",
    "evaluator_2_assignment_listed",
    "identity_provenance",
)
REQUIRED_CROSSWALK_COLUMNS = (
    "id_acordao",
    "anotador",
    "avaliador_projeto_1",
    "avaliador_projeto_2",
    "projeto_1_id_confirmado",
    "projeto_2_id_confirmado",
)


def normalize_id(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    s = str(value).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s if s.isdigit() else None


def find_document_id(row: dict[str, Any]) -> str | None:
    for data in (row, row.get("data")):
        if isinstance(data, dict):
            for field in ("id_acordao", "idacordao", "acordao_id"):
                result = normalize_id(data.get(field))
                if result is not None:
                    return result
    return None


def read_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
    elif suffix == ".jsonl":
        with path.open(encoding="utf-8-sig") as file:
            rows = [json.loads(line) for line in file if line.strip()]
    elif suffix == ".json":
        with path.open(encoding="utf-8-sig") as file:
            rows = json.load(file)
    else:
        raise ValueError("Input must end in .csv, .json or .jsonl")
    if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
        raise ValueError("Expected a list of row objects")
    return rows


def make_lookup(crosswalk: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not crosswalk:
        raise ValueError("Crosswalk cannot be empty")
    lookup: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(crosswalk, start=1):
        absent = [key for key in REQUIRED_CROSSWALK_COLUMNS if key not in row]
        if absent:
            raise ValueError(f"Missing required crosswalk columns in row {index}: {absent}")
        doc_id = normalize_id(row["id_acordao"])
        if not doc_id:
            raise ValueError(f"Invalid id_acordao in crosswalk row {index}")
        if doc_id in lookup:
            raise ValueError(f"Duplicate id_acordao in crosswalk: {doc_id}")
        lookup[doc_id] = row
    return lookup


def enrich(
    rows: list[dict[str, Any]], crosswalk: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return enriched copies and a coverage report without personal names."""
    lookup = make_lookup(crosswalk)
    counts: Counter[str] = Counter()
    unmatched: set[str] = set()
    output: list[dict[str, Any]] = []
    for row in rows:
        doc_id = find_document_id(row)
        assigned = lookup.get(doc_id) if doc_id is not None else None
        if doc_id is None:
            counts["missing_id"] += 1
        elif assigned is None:
            counts["unmatched"] += 1
            unmatched.add(doc_id)
        else:
            counts["matched"] += 1
        record = dict(row)
        if any(field in record for field in IDENTITY_FIELDS):
            raise ValueError("Input already contains identity-enrichment fields")
        record.update({
            "annotator_name_inferred": assigned["anotador"] if assigned else "",
            "evaluator_1_name_assigned": assigned["avaliador_projeto_1"] if assigned else "",
            "evaluator_2_name_assigned": assigned["avaliador_projeto_2"] if assigned else "",
            "evaluator_1_assignment_listed": assigned["projeto_1_id_confirmado"] if assigned else "",
            "evaluator_2_assignment_listed": assigned["projeto_2_id_confirmado"] if assigned else "",
            "identity_provenance": (
                "assignment_crosswalk_not_user_verified" if assigned else "unresolved"
            ),
        })
        output.append(record)
    report = {
        "input_rows": len(rows),
        "crosswalk_documents": len(lookup),
        "matched_rows": counts["matched"],
        "unmatched_rows": counts["unmatched"],
        "missing_document_id_rows": counts["missing_id"],
        "unmatched_document_ids": sorted(unmatched),
        "warning": "Assignment-based names do not verify numeric Label Studio user IDs.",
    }
    return output, report


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".json", ".jsonl"}:
        raise ValueError("Output must end in .csv, .json or .jsonl")
    if suffix == ".csv" and any(
        isinstance(value, (dict, list)) for row in rows for value in row.values()
    ):
        raise ValueError("Nested records cannot be exported to CSV without conversion")
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".json":
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    elif suffix == ".jsonl":
        with path.open("w", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
    else:
        fields = list(dict.fromkeys(key for row in rows for key in row)) or list(IDENTITY_FIELDS)
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--strict", action="store_true", help="Reject unmatched document IDs")
    args = parser.parse_args(argv)
    paths = (args.input, args.crosswalk, args.output, args.report)
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("All input and output paths must be distinct")
    results, report = enrich(read_rows(args.input), read_rows(args.crosswalk))
    if args.strict and (report["unmatched_rows"] or report["missing_document_id_rows"]):
        raise ValueError(f"Identity coverage incomplete: {report}")
    write_rows(args.output, results)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
