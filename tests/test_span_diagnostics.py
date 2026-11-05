import json

import pytest

from legal_nlp.span_diagnostics import diagnose_spans


def _row(annotation_id, task, start, end, label, annotator_id="A"):
    return {
        "annotation_id": annotation_id,
        "source_row": int(annotation_id[1:]) + 1,
        "document_id": "phase1:1",
        "task": task, "start": start, "end": end,
        "label": label, "annotator_id": annotator_id,
    }


def _load_jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_diagnostics_separate_duplicates_conflicts_and_overlaps(tmp_path):
    rows = [
        _row("a1", "NER", 0, 10, "ENT_RELATOR", "A"),
        _row("a2", "NER", 0, 10, "ENT_RELATOR", "B"),  # exact duplicate
        _row("a3", "NER", 0, 10, "ENT_CLASSE", "C"),    # same geometry, new label
        _row("a4", "NER", 2, 5, "ENT_RELATOR"),        # nested
        _row("a5", "NER", 7, 12, "ENT_RELATOR"),       # crossing
        _row("a6", "SEG", 0, 10, "SEG_EMENTA"),        # cross-task excluded
    ]
    source = tmp_path / "sanitized.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
    output = tmp_path / "diagnostics"
    report = diagnose_spans(source, output)
    assert report["input_annotation_count"] == 6
    assert report["per_task_counts"]["NER"]["annotation_count"] == 5
    assert report["per_task_counts"]["SEG"]["annotation_count"] == 1
    assert report["overall_counts"]["exact_duplicate_groups"] == 1
    assert report["overall_counts"]["exact_duplicate_extra_annotations"] == 1
    assert report["overall_counts"]["same_geometry_distinct_label_groups"] == 1
    assert report["overall_counts"]["overlap_pairs"] == 4
    assert report["per_task_counts"]["NER"]["overlap_nested_pairs"] == 2
    assert report["per_task_counts"]["NER"]["overlap_crossing_pairs"] == 2
    copies = _load_jsonl(output / "exact_duplicate_groups.jsonl")
    assert copies[0]["annotation_ids"] == ["a1", "a2"]
    assert copies[0]["annotator_identity_complete"]
    conflicts = _load_jsonl(output / "same_span_label_conflicts.jsonl")
    assert conflicts[0]["labels"] == ["ENT_CLASSE", "ENT_RELATOR"]
    before = source.read_bytes()
    expected = (output / "span_diagnostics_summary.json").read_bytes()
    assert diagnose_spans(source, output) == report
    assert source.read_bytes() == before
    assert (output / "span_diagnostics_summary.json").read_bytes() == expected


def test_diagnostics_rejects_invalid_input(tmp_path):
    source = tmp_path / "sanitized.jsonl"
    rows = [
        _row("a1", "SEG", 4, 2, "SEG_EMENTA"),
    ]
    source.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid sanitized span"):
        diagnose_spans(source, tmp_path / "result")


def test_diagnostics_detects_duplicate_annotation_identifiers(tmp_path):
    source = tmp_path / "sanitized.jsonl"
    row = _row("a1", "NER", 0, 4, "ENT_RELATOR")
    source.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate annotation_id"):
        diagnose_spans(source, tmp_path / "result")
