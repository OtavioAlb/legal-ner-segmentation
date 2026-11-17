"""Regression checks for deterministic checkbox review exports."""
import json

from legal_nlp.phase2_checkbox_review import (
    FIELDS, divergence_problem, review_rows, write_workbooks,
)


def task(doc_id, user_id, region_id, label, start, end, checkbox=None, updated_by=None):
    result = [{
        "id": region_id, "type": "labels",
        "value": {"labels": [label], "start": start, "end": end, "text": "trecho"}
    }]
    if checkbox is not None:
        result.append({
            "id": region_id, "type": "choices",
            "value": {"choices": [checkbox], "start": start, "end": end}
        })
    return {
        "id": doc_id,
        "data": {"idacordao": 123},
        "annotations": [{
            "completed_by": user_id, "was_cancelled": False, "result": result
        }],
        "updated_by": updated_by if updated_by is not None else user_id,
    }


def test_problem_is_computed_from_checkbox_and_original_geometry():
    old = {"label": "ENT_COMARCA", "start": 10, "end": 25}
    same = dict(old)
    assert divergence_problem(old, same, "Limite impreciso") == "limite igual original"
    assert divergence_problem(old, same, "Incorreto") == "label igual original"
    altered = {"label": "ENT_RELATOR", "start": 10, "end": 25}
    assert divergence_problem(old, altered, "Certo") == (
        "checkbox certo com anotação diferente do original"
    )
    assert divergence_problem(old, same, "Certo") == (
        "checkbox divergente entre avaliadores"
    )


def test_two_independent_five_column_reviewer_sheets(tmp_path):
    paths = []
    for name, t in (
        ("original", task(1, 8, "reg", "ENT_COMARCA", 10, 25)),
        ("11", task(2, 8, "reg", "ENT_COMARCA", 10, 25, "Limite impreciso")),
        ("17", task(3, 5, "reg", "ENT_COMARCA", 10, 25, "Certo")),
    ):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps([t]), encoding="utf-8")
        paths.append(path)

    grouped, control, metrics, _ = review_rows(*paths)
    assert len(control) == 1
    assert {key: len(value) for key, value in grouped.items()} == {"8": 1, "5": 1}
    assert grouped["8"][0]["problema de divergencia"] == "limite igual original"
    assert grouped["8"][0]["decisão checkbox"] == "Limite impreciso"
    assert grouped["5"][0]["decisão checkbox"] == "Certo"

    output, archive = write_workbooks(grouped, control, tmp_path / "out")
    from openpyxl import load_workbook
    wb = load_workbook(output, read_only=True)
    for name in ("Emily", "Guilherme"):
        sheet = wb[name]
        assert [cell.value for cell in sheet[1]] == list(FIELDS)
        assert sheet.max_column == 5
        assert sheet.max_row == 2
    wb.close()
    assert archive.is_file()
