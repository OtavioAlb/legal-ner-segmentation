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
    altered_label = {"label": "ENT_RELATOR", "start": 10, "end": 25}
    altered_limit = {"label": "ENT_COMARCA", "start": 11, "end": 25}
    altered_both = {"label": "ENT_RELATOR", "start": 11, "end": 26}
    assert divergence_problem(old, altered_label, "Certo") == (
        "checkbox certo com label diferente do original"
    )
    assert divergence_problem(old, altered_limit, "Certo") == (
        "checkbox certo com limite diferente do original"
    )
    assert divergence_problem(old, altered_both, "Certo") == (
        "checkbox certo com label e limite diferentes do original"
    )
    assert divergence_problem(old, same, "Certo") is None


def test_two_independent_seven_column_reviewer_sheets(tmp_path):
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
    assert {key: len(value) for key, value in grouped.items()} == {"8": 1}
    assert grouped["8"][0]["problema de divergencia"] == "limite igual original"
    assert grouped["8"][0]["decisão checkbox"] == "Limite impreciso"
    assert grouped["8"][0]["label original"] == "ENT_COMARCA"
    assert grouped["8"][0]["trecho anotado originalmente"] == "trecho"
    assert control[0]["grupo_planilha"] == "Emily"

    output = write_workbooks(grouped, control, tmp_path / "out")
    from openpyxl import load_workbook
    wb = load_workbook(output, read_only=True)
    for name in ("Emily",):
        sheet = wb[name]
        assert [cell.value for cell in sheet[1]] == list(FIELDS)
        assert sheet.max_column == 7
        assert sheet.max_row == 2
    wb.close()
    assert output.is_file()

def test_substitution_assigned_to_teresa_not_tiago(tmp_path):
    paths = []
    for name, t in (
        ("original", task(1, 8, "reg", "ENT_COMARCA", 10, 25)),
        ("11", task(2, 3, "reg", "ENT_COMARCA", 10, 25, "Limite impreciso")),
        ("17", task(3, 10, "reg", "ENT_COMARCA", 10, 25, "Incorreto", updated_by=3)),
    ):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps([t]), encoding="utf-8")
        paths.append(path)

    grouped, control, metrics, _ = review_rows(*paths)
    assert set(grouped) == {"3", "10"}
    assert metrics["inconsistencias_individuais"] == 2
    assert metrics["substituicoes_por_tiago"] == 1
    assert next(row for row in control if row["grupo_planilha"] == "Teresa")[
        "substituicao_por_tiago"
    ] is True
    output = write_workbooks(grouped, control, tmp_path / "out")
    from openpyxl import load_workbook
    wb = load_workbook(output, read_only=True)
    assert "Teresa" in wb.sheetnames
    assert "Tiago" in wb.sheetnames
    assert [c.value for c in wb["Teresa"][1]] == list(FIELDS)
    wb.close()
