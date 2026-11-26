"""Synthetic tests for escape normalization; all inputs are invented."""
import json
import pytest
from legal_nlp.phase2_span_text_normalization import normalize_rows, normalize_files

def row(text, excerpt):
    return {"id": 1, "data": {"idacordao": 123, "acordao": text},
            "annotations": [{"result": [{"type": "labels", "value": {
                "start": 0, "end": len(text), "text": excerpt,
                "labels": ["ENT_CLASSE"]}}]}]}

def test_escape_normalization():
    source = [row("a\nb", r"a\nb")]
    output, actions, summary = normalize_rows(source, "original")
    assert output[0]["annotations"][0]["result"][0]["value"]["text"] == "a\nb"
    assert source[0]["annotations"][0]["result"][0]["value"]["text"] == r"a\nb"
    assert len(actions) == summary["normalized"] == 1

def test_unresolved_not_modified():
    source = [row("abc", "xyz")]
    output, actions, summary = normalize_rows(source, "evaluation")
    assert output == source
    assert not actions
    assert summary["unresolved_mismatch"] == 1

def test_idempotent():
    normalized, _, _ = normalize_rows([row("a\nb", r"a\nb")], "original")
    second, changes, summary = normalize_rows(normalized, "original")
    assert second == normalized
    assert not changes
    assert summary["already_exact"] == 1

def test_expected_count_gate(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps([row("a\nb", r"a\nb")]))
    b.write_text("[]")
    dest = tmp_path / "output"
    with pytest.raises(ValueError, match="nothing written"):
        normalize_files(a, b, dest, 2)
    assert not dest.exists()
    report = normalize_files(a, b, dest, 1)
    assert report["total_normalized"] == 1
    assert json.loads((dest / "normalization_summary.json").read_text()) == report
