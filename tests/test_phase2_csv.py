import csv
import json

from legal_nlp.phase2_csv import export_csv


def test_csv_export(tmp_path):
    source = tmp_path / "merged.json"
    target = tmp_path / "merged.csv"
    row = {
        "id": 1,
        "annotated_by": 3,
        "evaluated_by": 7,
        "data": {"idacordao": 100, "acordao": "a\\nb"},
        "annotations": [{"result": [{"value": {"choices": ["Certo"]}}]}],
    }
    source.write_text(json.dumps([row]), encoding="utf-8")
    result = export_csv(source, target)
    assert result["evaluation_rows"] == 1
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["idacordao"] == "100"
    assert rows[0]["annotated_by"] == "3"
    assert rows[0]["evaluated_by"] == "7"
    assert json.loads(rows[0]["annotations"]) == row["annotations"]
    assert json.loads(rows[0]["data"]) == row["data"]
