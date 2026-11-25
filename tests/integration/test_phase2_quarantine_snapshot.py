"""Regression for conservative Phase 2 source-text quarantine."""
import json

import pytest

from legal_nlp.datasets.versioned_corpus import build_diagnostic_corpus
from legal_nlp.datasets.readiness import analyze_readiness
from legal_nlp.io.jsonl import read_jsonl
from test_versioned_corpus import fixture_paths


def _rewrite_label_excerpt(path, raw):
    tasks = json.loads(path.read_text(encoding="utf-8"))
    for region in tasks[0]["annotations"][0]["result"]:
        if region["type"] == "labels":
            region["value"]["text"] = raw
    path.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")


def test_strict_checks_all_projects_even_when_reviews_agree(tmp_path):
    paths = fixture_paths(tmp_path)
    # Source text in project 11 disagrees, although the offsets/label still agree.
    _rewrite_label_excerpt(paths[2], "xyz")
    out = tmp_path / "snapshot_strict"
    with pytest.raises(ValueError, match="Unresolved Phase 2 source text mismatch"):
        build_diagnostic_corpus(*paths, out, version="strict_v1")
    assert not out.exists()


def test_quarantine_retains_source_lineage_without_promoting_gold(tmp_path):
    paths = fixture_paths(tmp_path)
    _rewrite_label_excerpt(paths[2], "xyz")
    out = tmp_path / "snapshot_quarantined"
    result = build_diagnostic_corpus(
        *paths, out, version="quarantine_v1", quarantine_unresolved=True
    )
    assert result["training_ready"] is False
    assert result["quarantine_enabled"] is True
    assert result["quarantine_normalized_rows"] == 1
    assert result["quarantine_record_count"] == 2
    assert result["annotation_count"] == 1  # phase1 survives
    rows = read_jsonl(out / "annotations.jsonl")
    assert rows[0]["phase"] == "phase_1"
    quarantine = read_jsonl(out / "quarantine.jsonl")
    assert len(quarantine) == 2
    assert {r["region_id"] for r in quarantine} == {"r1"}
    assert any(r.get("project") == "11" for r in quarantine)
    assert all("text" not in r for r in quarantine)
    readiness = analyze_readiness(out)
    assert readiness["training_ready"] is False
    assert readiness["quarantine_record_count"] == 2
    assert "source_text_quarantine_empty" in readiness["blockers"]


def test_normal_snapshot_does_not_create_quarantine_file(tmp_path):
    paths = fixture_paths(tmp_path)
    out = tmp_path / "snapshot_clean"
    manifest = build_diagnostic_corpus(*paths, out, version="normal_v1")
    assert manifest["quarantine_enabled"] is False
    assert manifest["quarantine_record_count"] == 0
    assert not (out / "quarantine.jsonl").exists()


def test_project_document_text_mismatch_is_never_quarantined(tmp_path):
    paths = fixture_paths(tmp_path)
    tasks = json.loads(paths[2].read_text(encoding="utf-8"))
    tasks[0]["data"]["acordao"] = "different text"
    paths[2].write_text(json.dumps(tasks), encoding="utf-8")
    out = tmp_path / "unsafe"
    with pytest.raises(ValueError, match="Different document text"):
        build_diagnostic_corpus(
            *paths, out, version="different_v1", quarantine_unresolved=True
        )
    assert not out.exists()
