import json

import pytest

from legal_nlp.logical_spans import build_logical_spans


def _write(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _source(annotation_id, row_no, label_original, label_revised, status, annotator):
    return {
        "annotation_id": annotation_id,
        "source_row": row_no,
        "annotator_id": annotator,
        "target_selection_status": status,
        "fields_original": {"label": label_original},
        "fields_revised": {"label": label_revised},
        "review_agree_count": 1,
        "review_disagree_count": 0,
    }


def _selected(annotation_id, row_no, annotator, label, start, end, status):
    return {
        "annotation_id": annotation_id,
        "source_row": row_no,
        "annotator_id": annotator,
        "document_id": "phase1:291",
        "task": "NER",
        "label": label,
        "start": start,
        "end": end,
        "source_of_truth": (
            "evaluator_reviewed_fields" if status == "reviewed_final"
            else "original_confirmed_by_reviewers"
        ),
        "text_equivalence": "exact",
        "sanitization_rule_ids": [],
    }


def test_exact_grouping_keeps_all_provenance_and_distinct_spans(tmp_path):
    sources = [
        _source("a1", 2, "ENT_CLASSE", "ENT_RELATOR", "reviewed_final", "A"),
        _source("a2", 3, "ENT_RELATOR", None, "original_confirmed_by_reviewers", "B"),
        _source("a3", 4, "ENT_CLASSE", "ENT_CLASSE", "reviewed_final", "C"),
        _source("a4", 5, "ENT_RELATOR", "ENT_RELATOR", "reviewed_final", "D"),
    ]
    selected = [
        _selected("a1", 2, "A", "ENT_RELATOR", 100, 120, "reviewed_final"),
        _selected("a2", 3, "B", "ENT_RELATOR", 100, 120,
                  "original_confirmed_by_reviewers"),
        _selected("a3", 4, "C", "ENT_CLASSE", 100, 120, "reviewed_final"),
        _selected("a4", 5, "D", "ENT_RELATOR", 102, 121, "reviewed_final"),
    ]
    source_file = tmp_path / "annotations.jsonl"
    selected_file = tmp_path / "sanitized.jsonl"
    out = tmp_path / "logical"
    _write(source_file, sources)
    _write(selected_file, selected)
    result = build_logical_spans(selected_file, source_file, out)
    assert result["input_annotation_count"] == 4
    assert result["logical_span_count"] == 3
    assert result["exact_duplicate_extra_annotations"] == 1
    assert result["groups_with_multiple_source_annotations"] == 1
    spans = [json.loads(x) for x in (out / "logical_spans.jsonl").read_text().splitlines()]
    copied = next(x for x in spans if x["label"] == "ENT_RELATOR" and x["start"] == 100)
    assert copied["source_annotation_count"] == 2
    assert copied["annotator_ids"] == ["A", "B"]
    assert len(copied["provenance"]) == 2
    assert copied["explicit_evaluator_label_change_count"] == 1
    assert copied["provenance"][0]["label_original"] == "ENT_CLASSE"
    assert copied["provenance"][0]["label_evaluator_revised"] == "ENT_RELATOR"
    assert {x["start"] for x in spans} == {100, 102}
    before = (out / "logical_spans.jsonl").read_bytes()
    assert build_logical_spans(selected_file, source_file, out) == result
    assert (out / "logical_spans.jsonl").read_bytes() == before


def test_fails_closed_on_missing_provenance(tmp_path):
    selected_file = tmp_path / "sanitized.jsonl"
    source_file = tmp_path / "annotations.jsonl"
    _write(selected_file, [
        _selected("missing", 2, "A", "ENT_RELATOR", 100, 120, "reviewed_final")
    ])
    _write(source_file, [])
    with pytest.raises(ValueError, match="Missing provenance"):
        build_logical_spans(selected_file, source_file, tmp_path / "out")


def test_fails_closed_on_unreviewed_or_inconsistent_annotation(tmp_path):
    selected_file = tmp_path / "sanitized.jsonl"
    source_file = tmp_path / "annotations.jsonl"
    _write(selected_file, [
        _selected("a1", 2, "A", "ENT_RELATOR", 100, 120, "reviewed_final")
    ])
    _write(source_file, [
        _source("a1", 2, "ENT_RELATOR", None, "no_evaluation_no_correction", "A")
    ])
    with pytest.raises(ValueError, match="Invalid evaluator precedence"):
        build_logical_spans(selected_file, source_file, tmp_path / "out")
