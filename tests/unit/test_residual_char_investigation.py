"""Tests for optional codepoint diagnostics without modifying source data."""
import json

from legal_nlp.datasets.residual_text_fingerprints import (
    character_operations, inspect_residuals,
)


def _task(user, raw):
    return {
        "id": 42,
        "data": {"idacordao": 42, "acordao": "AÇÃO e lei"},
        "updated_by": user,
        "annotations": [{
            "completed_by": user,
            "result": [{
                "id": "r1", "type": "labels",
                "value": {"labels": ["ENT_PARTE_ATIVA"], "start": 0,
                          "end": 4, "text": raw},
            }],
        }],
    }


def test_codepoint_report_identifies_changed_characters():
    details = character_operations("ACAO", "AÇÃO")
    assert len(details) >= 1
    codes = [
        item["codepoint"] for change in details
        for item in change["document_codepoints"]
    ]
    assert "U+00C7" in codes
    assert "U+00C3" in codes
    assert all("unicode_name" in item for change in details
               for item in change["document_codepoints"])


def test_codepoints_are_opt_in_and_no_source_mutated(tmp_path):
    files = []
    for name, user in (("original", 8), ("11", 7), ("17", 5)):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps([_task(user, "ACAO")]), encoding="utf-8")
        files.append(path)
    before = [p.read_bytes() for p in files]
    default = inspect_residuals(*files)
    assert "character_operations" not in default["regions"][0]["projects"][0]
    assert default["codepoints_included"] is False
    detailed = inspect_residuals(*files, include_codepoints=True)
    assert detailed["codepoints_included"] is True
    assert detailed["regions"][0]["projects"][0]["character_operations"]
    assert "AÇÃO" not in json.dumps(detailed, ensure_ascii=False)
    assert [p.read_bytes() for p in files] == before
