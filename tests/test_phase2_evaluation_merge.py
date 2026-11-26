"""Synthetic, no judicial text: Phase 2 evaluation consolidation."""
import copy
import json

import pytest

from legal_nlp.phase2_evaluation_merge import merge_evaluation_exports


def _row(idacordao, task_id, completed_by, *, text=None):
    return {
        "id": task_id,
        "annotations": [
            {"id": task_id + 1000, "completed_by": completed_by,
             "was_cancelled": False, "result": [
                 {"type": "choices", "from_name": "confianca_anotacao",
                  "value": {"choices": ["Certo"]}}
             ]}
        ],
        "data": {"idacordao": idacordao, "acordao": text or f"Documento {idacordao}"},
        "predictions": [{"id": task_id * 10}],
        "updated_by": completed_by,
        "project": 17,
    }


def _dump(path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def _case(tmp_path):
    original = [_row(202, 1, 8), _row(101, 2, 3), _row(303, 3, 4)]
    ev1 = [_row(303, 33, 8), _row(101, 31, 7), _row(202, 32, 5)]
    ev2 = [_row(202, 42, 9), _row(101, 41, 12)]
    p0, p1, p2 = [tmp_path / name for name in ("original.json", "eval1.json", "eval2.json")]
    for path, data in ((p0, original), (p1, ev1), (p2, ev2)):
        _dump(path, data)
    return (p0, p1, p2), [original, ev1, ev2]


def test_merge_retains_two_evaluations_and_single_evaluation(tmp_path):
    (p0, p1, p2), (_, ev1, ev2) = _case(tmp_path)
    output = tmp_path / "merged.json"
    report = tmp_path / "report.json"
    summary = merge_evaluation_exports(p0, [p1, p2], output, report, 3)
    assert summary["evaluation_records_merged"] == 5
    assert summary["evaluated_unique_acordaos"] == 3
    assert summary["acordaos_with_one_evaluation"] == 1
    assert summary["acordaos_with_two_evaluations"] == 2
    rows = json.loads(output.read_text(encoding="utf-8"))
    assert len(rows) == 5
    assert [(x["annotated_by"], x["data"]["idacordao"], x["evaluated_by"]) for x in rows] == [
        (3, 101, 7), (3, 101, 12), (4, 303, 8), (8, 202, 5), (8, 202, 9)
    ]
    for row in rows:
        original_eval = next(
            x for x in ev1 + ev2 if x["id"] == row["id"]
        )
        stripped = {k: v for k, v in row.items() if k not in {"annotated_by", "evaluated_by"}}
        assert stripped == original_eval
        assert row["annotations"][0]["completed_by"] == row["evaluated_by"]
        assert row["updated_by"] == original_eval["updated_by"]
    assert summary == json.loads(report.read_text(encoding="utf-8"))
    previous = output.read_bytes()
    assert merge_evaluation_exports(p0, [p2, p1], output, report, 3)["evaluation_records_merged"] == 5
    assert previous == output.read_bytes()


def test_unmatched_document_fails_without_writing(tmp_path):
    (p0, p1, p2), (_, ev1, _) = _case(tmp_path)
    ev1[0]["data"]["idacordao"] = 777
    _dump(p1, ev1)
    output = tmp_path / "merged.json"
    with pytest.raises(ValueError, match="unmatched"):
        merge_evaluation_exports(p0, [p1, p2], output, expected_original_documents=3)
    assert not output.exists()


def test_text_mismatch_fails(tmp_path):
    (p0, p1, p2), (_, ev1, _) = _case(tmp_path)
    ev1[0]["data"]["acordao"] = "texto diferente"
    _dump(p1, ev1)
    with pytest.raises(ValueError, match="text_mismatches"):
        merge_evaluation_exports(p0, [p1, p2], tmp_path / "merged.json", expected_original_documents=3)


def test_same_reviewer_twice_fails(tmp_path):
    (p0, p1, p2), (_, _, ev2) = _case(tmp_path)
    ev2[0]["annotations"][0]["completed_by"] = 5
    _dump(p2, ev2)
    with pytest.raises(ValueError, match="Repeated evaluation"):
        merge_evaluation_exports(p0, [p1, p2], tmp_path / "merged.json", expected_original_documents=3)


def test_multiple_annotations_in_one_task_fail_closed(tmp_path):
    (p0, p1, p2), (_, ev1, _) = _case(tmp_path)
    ev1[0]["annotations"].append(copy.deepcopy(ev1[0]["annotations"][0]))
    _dump(p1, ev1)
    with pytest.raises(ValueError, match="exactly one annotation"):
        merge_evaluation_exports(p0, [p1, p2], tmp_path / "merged.json", expected_original_documents=3)


def test_same_person_annotated_and_evaluated_fails(tmp_path):
    (p0, p1, p2), (_, ev1, _) = _case(tmp_path)
    ev1[0]["annotations"][0]["completed_by"] = 4
    _dump(p1, ev1)
    with pytest.raises(ValueError, match="Self-evaluation"):
        merge_evaluation_exports(p0, [p1, p2], tmp_path / "merged.json", expected_original_documents=3)


def test_outputs_cannot_overwrite_inputs(tmp_path):
    (p0, p1, p2), _ = _case(tmp_path)
    with pytest.raises(ValueError, match="paths must all be distinct"):
        merge_evaluation_exports(p0, [p1, p2], p1, expected_original_documents=3)
