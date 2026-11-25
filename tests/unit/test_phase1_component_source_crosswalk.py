"""Contract tests for source-linked overlap families; no real judicial data."""
import json

import pytest

from legal_nlp.datasets import phase1_component_source_crosswalk as mod
from legal_nlp.io.jsonl import write_jsonl


def _setup(tmp_path, monkeypatch):
    harmonized = tmp_path / "harmonized"
    harmonized.mkdir()
    provenance = [{"annotation_id": f"ann{i}", "source_row": i + 2,
                   "annotator_id": "anonymous", "selection_status": "reviewed_final",
                   "source_of_truth": "evaluator_reviewed_fields",
                   "review_agree_count": 1, "review_disagree_count": 0}
                  for i in range(3)]
    rows = []
    lineage = []
    for i, (start, end) in enumerate([(0, 10), (0, 9), (18, 25)]):
        entry = provenance[i]
        lid = f"ls_{i}"
        rows.append({
            "phase": "phase_1", "document_id": "phase_1:phase1:1",
            "region_id": lid, "task": "SEG", "label": "SEG_RELATORIO",
            "source_label": "SEG_RELATORIO", "source_task": "SEG",
            "start": start, "end": end,
            "status": "consolidated", "source_status": "fixture",
            "provenance": [entry],
        })
        lineage.append({
            "logical_span_id": lid, "label": "SEG_RELATORIO",
            "source_records": [{
                "annotation_id": entry["annotation_id"],
                "source_row": entry["source_row"],
                "selection_status": "reviewed_final",
                "original_label": "SEG_RELATORIO",
                "revised_label": "SEG_RELATORIO",
                "original_start": start,
                "original_end": end - 1,
                "revised_start": start,
                "revised_end": end,
                "review_agree_count": 1, "review_disagree_count": 0,
            }]
        })
    write_jsonl(harmonized / "annotations_harmonized.jsonl", rows)
    verified = {
        "lineage": lineage,
        "verified_raw_export_sha256": {"texts": "test", "annotations": "test"},
        "verified_intermediate_sha256": {"logical_spans": "test"},
        "verified_logical_spans": 3, "verified_source_annotations": 3,
    }
    monkeypatch.setattr(mod, "audit_phase1_lineage", lambda *args: verified)
    return harmonized


def test_crosswalk_join_reconciles_groups_and_source_annotation_ids(tmp_path, monkeypatch):
    harmonized = _setup(tmp_path, monkeypatch)
    result = mod.analyze_component_source_crosswalk(
        tmp_path, harmonized, tmp_path, tmp_path, tmp_path,
        tmp_path, tmp_path, tmp_path, tmp_path,
        max_groups=4, max_per_document=2
    )
    assert result["by_phase"]["phase_1"]["components"] == 1
    assert result["by_phase"]["phase_1"]["spans_in_components"] == 2
    assert result["by_phase"]["phase_1"]["source_annotations_in_components"] == 2
    assert result["by_phase"]["phase_1"]["source_rows_with_revised_offsets"] == 2
    assert result["verified_phase1_SEG_after_vote_mapping"] == 3
    assert len(result["review_queue"][0]["source_rows"]) == 2
    assert result["training_ready"] is False


def test_crosswalk_fails_when_expected_source_span_missing(tmp_path, monkeypatch):
    harmonized = _setup(tmp_path, monkeypatch)
    def bad_lineage(*args):
        return {"lineage": [], "verified_raw_export_sha256": {},
                "verified_intermediate_sha256": {},
                "verified_logical_spans": 0, "verified_source_annotations": 0}
    monkeypatch.setattr(mod, "audit_phase1_lineage", bad_lineage)
    with pytest.raises(ValueError, match="SEG view differs"):
        mod.analyze_component_source_crosswalk(
            tmp_path, harmonized, tmp_path, tmp_path, tmp_path,
            tmp_path, tmp_path, tmp_path, tmp_path
        )


def test_crosswalk_rejects_invalid_sampling(tmp_path, monkeypatch):
    harmonized = _setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Invalid queue"):
        mod.analyze_component_source_crosswalk(
            tmp_path, harmonized, tmp_path, tmp_path, tmp_path,
            tmp_path, tmp_path, tmp_path, tmp_path, max_groups=0
        )
