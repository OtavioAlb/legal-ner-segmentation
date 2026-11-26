"""Synthetic regression checks for shared JSONL formatting and legacy aliases."""
from __future__ import annotations

import json

import pytest

from legal_nlp.io.jsonl import read_jsonl, write_jsonl
from legal_nlp import audit, sanitization, logical_spans, document_dataset
from legal_nlp import reviewer_priority, span_diagnostics


@pytest.mark.parametrize("module", [
    audit, sanitization, logical_spans, document_dataset, reviewer_priority,
])
def test_legacy_io_aliases_match_shared_implementation(module):
    assert module._read_jsonl is read_jsonl
    assert module._write_jsonl is write_jsonl


def test_span_diagnostics_writer_alias():
    assert span_diagnostics._write_jsonl is write_jsonl


def test_jsonl_preserves_unicode_order_and_lf(tmp_path):
    path = tmp_path / "example.jsonl"
    rows = [
        {"z": "ação", "a": 1, "label": "SEG_EMENTA"},
        {"start": 12, "end": 18, "text": "revisão"},
    ]
    write_jsonl(path, rows)
    expected = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    assert path.read_bytes() == expected.encode("utf-8")
    assert read_jsonl(path) == rows


def test_jsonl_skips_blank_lines_without_silent_recovery(tmp_path):
    path = tmp_path / "example.jsonl"
    path.write_text('\n  \n {"a": 1}\n\t\n', encoding="utf-8")
    assert read_jsonl(path) == [{"a": 1}]
    path.write_text('{"a": 1}\ninvalid\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        read_jsonl(path)


def test_jsonl_write_does_not_make_parent_directories(tmp_path):
    path = tmp_path / "missing" / "output.jsonl"
    with pytest.raises(FileNotFoundError):
        write_jsonl(path, [])
