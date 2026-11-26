"""Export merged evaluation JSON records to a lossless, one-row-per-review CSV."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def export_csv(input_path: str | Path, output_path: str | Path) -> dict:
    source = Path(input_path)
    destination = Path(output_path)
    if source.resolve() == destination.resolve():
        raise ValueError("CSV output must not overwrite input JSON")
    evaluations = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(evaluations, list) or not all(isinstance(x, dict) for x in evaluations):
        raise ValueError("Input must be a JSON array of evaluation objects")

    preferred = ["idacordao", "annotated_by", "evaluated_by", "id"]
    names = set().union(*(row.keys() for row in evaluations)) if evaluations else set()
    columns = preferred + sorted(names.difference(preferred))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in evaluations:
            data = row.get("data")
            if not isinstance(data, dict) or "idacordao" not in data:
                raise ValueError("Missing data.idacordao")
            if "annotated_by" not in row or "evaluated_by" not in row:
                raise ValueError("Missing original annotator or evaluator")
            cells = {"idacordao": str(data["idacordao"])}
            for key, value in row.items():
                if isinstance(value, (dict, list)):
                    cells[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
                elif value is None:
                    cells[key] = "null"
                elif isinstance(value, bool):
                    cells[key] = "true" if value else "false"
                else:
                    cells[key] = str(value)
            writer.writerow(cells)
    return {"evaluation_rows": len(evaluations), "columns": columns, "output": str(destination)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the merged Phase 2 evaluations JSON to CSV")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export_csv(args.input, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
