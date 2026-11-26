"""Synthetic evidence checks: individual votes, geometry, and raw-export integrity."""
import json
import pytest

from legal_nlp.datasets import phase1_evaluator_evidence as m
from legal_nlp.io.jsonl import write_jsonl


def fixture(tmp_path, monkeypatch):
    raw = tmp_path / "source.csv"
    raw.write_text(
        "id_text,concorda_A,concorda_B,comentario_A,comentario_B\n"
        "1,Sim,Não,,limite grande\n"
        "1,Sim,Sim,,\n"
        "1,Sim,,,\n",
        encoding="utf-8"
    )
    ing = tmp_path / "ing"
    ing.mkdir()
    from legal_nlp.ingestion import _load_rows, normalize_review_vote
    parsed, _ = _load_rows(raw)
    anns = []
    for i, r in enumerate(parsed):
        votes = {
            name: {"agreement_raw": r.get("concorda_" + name),
                   "comment_raw": r.get("comentario_" + name),
                   "status": normalize_review_vote(r.get("concorda_" + name))}
            for name in ("A", "B")
        }
        anns.append({
            "annotation_id": f"a{i}", "source_row": i + 2,
            "source_fields": {str(k): None if v is None else str(v) for k, v in r.items()},
            "reviewer_opinions": votes,
            "review_agree_count": sum(v["status"] == "agree" for v in votes.values()),
            "review_disagree_count": sum(v["status"] == "disagree" for v in votes.values()),
        })
    write_jsonl(ing / "annotations.jsonl", anns)
    group = {
        "document_id": "phase_1:phase1:1", "label": "SEG_RELATORIO",
        "number_of_regions": 2,
        "regions": [
            {"region_id": "ls0", "start": 0, "end": 10},
            {"region_id": "ls1", "start": 0, "end": 9},
        ],
        "source_rows": [
            {"logical_span_id": "ls0", "annotation_id": "a0", "source_row": 2,
             "selection_status": "reviewed_final"},
            {"logical_span_id": "ls1", "annotation_id": "a1", "source_row": 3,
             "selection_status": "reviewed_final"},
        ],
    }
    report = {
        "review_queue": [group], "components_total": 1,
        "by_phase": {"phase_1": {"source_annotations_in_components": 2}},
        "verified_source_manifest_sha256": {"texts": "x", "annotations": "y"},
    }
    monkeypatch.setattr(m, "analyze_component_source_crosswalk",
                        lambda *args, **kwargs: report)
    return raw, ing


def _call(tmp_path, raw, ing):
    return m.analyze_evaluator_evidence(
        tmp_path, tmp_path, tmp_path, tmp_path, raw,
        ing, tmp_path, tmp_path, tmp_path
    )


def test_verified_votes_and_same_reviewer_support_for_two_geometries(tmp_path, monkeypatch):
    raw, ing = fixture(tmp_path, monkeypatch)
    result = _call(tmp_path, raw, ing)
    assert result["summary"]["families"] == 1
    assert result["summary"]["families_with_same_reviewer_supporting_alternatives"] == 1
    assert result["summary"]["families_with_negative_votes"] == 1
    assert result["review_queue"][0]["evidence_category"] == "conflicting_positive_geometries"
    text = json.dumps(result)
    assert "limite grande" not in text
    assert "comentario" not in text
    assert "reviewer_aliases_supporting_multiple_geometries" in text
    assert result["training_ready"] is False


def test_raw_row_mutation_is_rejected(tmp_path, monkeypatch):
    raw, ing = fixture(tmp_path, monkeypatch)
    raw.write_text(raw.read_text(encoding="utf-8").replace(
        "1,Sim,Não", "1,Não,Não"), encoding="utf-8")
    with pytest.raises(ValueError, match="raw source fields differ"):
        _call(tmp_path, raw, ing)


def test_vote_total_mutation_is_rejected(tmp_path, monkeypatch):
    raw, ing = fixture(tmp_path, monkeypatch)
    rows = m.read_jsonl(ing / "annotations.jsonl")
    rows[0]["review_agree_count"] = 99
    write_jsonl(ing / "annotations.jsonl", rows)
    with pytest.raises(ValueError, match="Reviewer totals differ"):
        _call(tmp_path, raw, ing)


def test_reject_invalid_queue_limit(tmp_path, monkeypatch):
    raw, ing = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Queue limits"):
        m.analyze_evaluator_evidence(
            tmp_path, tmp_path, tmp_path, tmp_path, raw,
            ing, tmp_path, tmp_path, tmp_path, max_groups=0
        )
