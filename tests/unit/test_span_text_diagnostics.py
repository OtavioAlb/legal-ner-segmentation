"""Synthetic tests: mismatch diagnostics are read-only and exhaustive."""
import json

from legal_nlp.datasets.span_text_diagnostics import (
    _classify, inspect_phase2_text,
)


def task(reviewer, excerpt, *, choice="Incorreto"):
    return {
        "id": 42, "data": {"idacordao": 42, "acordao": "abc\ndef"},
        "updated_by": reviewer,
        "annotations": [{
            "completed_by": reviewer, "result": [
                {"id": "r1", "type": "labels",
                 "value": {"labels": ["ENT_COMARCA"], "start": 0,
                           "end": 7, "text": excerpt}},
                {"id": "r1", "type": "choices", "value": {"choices": [choice]}},
            ],
        }],
    }


def test_literal_backslash_diagnostic():
    assert _classify("abc\\ndef", "abc\ndef") == "literal_backslash_escapes_in_span"
    assert _classify("abc\r\ndef", "abc\ndef") == "newline_style_difference"
    assert _classify(" abc ", "abc") == "edge_whitespace"


def test_diagnostic_finds_all_regions_without_modifying_sources(tmp_path):
    p = []
    for name, reviewer, excerpt in [
        ("o", 8, "abc\\ndef"),
        ("11", 7, "abc\ndef"),
        ("17", 5, "abc\ndef"),
    ]:
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps([task(reviewer, excerpt)]), encoding="utf-8")
        p.append(path)
    before = [x.read_bytes() for x in p]
    result = inspect_phase2_text(*p)
    assert result["candidate_count"] == 1
    assert result["categories"] == {"literal_backslash_escapes_in_span": 1}
    assert result["findings"][0]["region_id"] == "r1"
    assert "source_text_repr" not in result["findings"][0]
    assert [x.read_bytes() for x in p] == before


def test_excerpts_are_explicit_opt_in(tmp_path):
    p = []
    for name, reviewer, excerpt in [
        ("o", 8, "abc\\ndef"),
        ("11", 7, "abc\ndef"),
        ("17", 5, "abc\ndef"),
    ]:
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps([task(reviewer, excerpt)]), encoding="utf-8")
        p.append(path)
    result = inspect_phase2_text(*p, include_excerpts=True)
    assert result["findings"][0]["source_text_repr"] == repr("abc\\ndef")
    assert result["source_correction_performed"] is False
