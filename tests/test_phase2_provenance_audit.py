"""Regression tests for deterministic Phase 2 provenance; no private data."""
import json

from legal_nlp.phase2_provenance_audit import audit


def task(doc, project, reviewer, spans):
    result = []
    for rid, label, start, end, choice, comment in spans:
        result.append({"id": rid, "type": "labels",
                       "value": {"labels": [label], "start": start, "end": end,
                                 "text": "x" * (end - start)}})
        if choice:
            result.append({"id": rid, "type": "choices", "value": {"choices": [choice]}})
        if comment:
            result.append({"id": rid, "type": "textarea", "value": {"text": [comment]}})
    return {"id": project, "data": {"idacordao": doc},
            "annotations": [{"completed_by": reviewer, "result": result}]}


def write(path, tasks):
    path.write_text(json.dumps(tasks), encoding="utf-8")
    return path


def test_new_region_negative_identical_geometry_not_accepted(tmp_path):
    original = write(tmp_path / "original.json", [
        task(16062822, 6, 8, [("existing", "SEG_FOLHA_ROSTO", 0, 452, None, None)])
    ])
    review11 = write(tmp_path / "r11.json", [
        task(16062822, 11, 7, [
            ("existing", "SEG_FOLHA_ROSTO", 0, 452, "Certo", None),
            ("kQcIH4ot0Y", "ENT_COMARCA", 0, 97, "Incorreto",
             'seria somente "comarca de promissão"'),
        ])
    ])
    review17 = write(tmp_path / "r17.json", [
        task(16062822, 17, 5, [("existing", "SEG_FOLHA_ROSTO", 0, 452, "Certo", None)])
    ])
    summary = audit(original, review11, review17, tmp_path / "output")
    assert summary["by_origin"] == {"NEW_IN_REVIEW": 1, "ORIGINAL": 1}
    rows = [json.loads(line) for line in
            (tmp_path / "output/phase2_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    new = next(r for r in rows if r["region_id"] == "kQcIH4ot0Y")
    assert new["status"] == "PENDING_NEW"
    assert new["adjudicated"] is False
    assert "EXPLICIT_NEGATIVE_11" in new["reasons"]
    assert "ABSENT_IN_REVIEW_17" in new["reasons"]
    assert new["review_11"]["comment"] == 'seria somente "comarca de promissão"'


def test_same_geometry_different_id_not_identity(tmp_path):
    a = write(tmp_path / "o.json", [task(1, 6, 8, [
        ("A", "ENT_COMARCA", 2, 7, None, None)])])
    b = write(tmp_path / "e11.json", [task(1, 11, 7, [
        ("A", "ENT_COMARCA", 2, 7, "Certo", None),
        ("B", "ENT_COMARCA", 2, 7, None, None)])])
    c = write(tmp_path / "e17.json", [task(1, 17, 5, [
        ("A", "ENT_COMARCA", 2, 7, "Certo", None)])])
    summary = audit(a, b, c, tmp_path / "out")
    assert summary["new_exact_geometry_groups"] == 1
    new = next(json.loads(line) for line in
               (tmp_path / "out/phase2_audit.jsonl").read_text(encoding="utf-8").splitlines()
               if '"region_id": "B"' in line)
    assert new["origin"] == "NEW_IN_REVIEW"
    assert new["same_geometry_original_ids"] == ["A"]


def test_identical_new_proposals_are_grouped_without_automatic_adjudication(tmp_path):
    a = write(tmp_path / "o.json", [task(1, 6, 8, [])])
    b = write(tmp_path / "e11.json", [task(1, 11, 7, [
        ("B", "ENT_COMARCA", 2, 7, "Certo", None)])])
    c = write(tmp_path / "e17.json", [task(1, 17, 5, [
        ("C", "ENT_COMARCA", 2, 7, "Certo", None)])])
    summary = audit(a, b, c, tmp_path / "out")
    assert summary["new_exact_geometry_groups"] == 1
    assert summary["new_duplicate_geometry_records"] == 1
    group = json.loads((tmp_path / "out/phase2_new_candidate_groups.jsonl")
                       .read_text(encoding="utf-8").splitlines()[0])
    assert group["source_region_ids"] == ["B", "C"]
    assert group["projects_proposing"] == [11, 17]
    assert group["adjudicated"] is False
