"""Regression of verified escape-only equivalence in Phase 2 spans."""
import pytest

from legal_nlp.datasets.corpus_adapters import resolve_text


def record(text, *, status="pending_review", source_status="PENDENTE_GEOMETRIA"):
    return {
        "phase": "phase_2",
        "document_id": "14498623",
        "region_id": "OZQWnOfz12",
        "task": "SEG", "label": "SEG_FOLHA_ROSTO",
        "start": 0, "end": 7, "text": text,
        "status": status, "source_status": source_status,
        "provenance": {"original_region_id": "OZQWnOfz12"},
    }


def test_literal_escapes_are_accepted_only_when_full_slice_matches():
    raw = "abc\\ndef"
    result = resolve_text([record(raw)], {"14498623": "abc\ndef"})[0]
    assert result["text"] == "abc\ndef"
    assert result["source_text_raw"] == raw
    assert result["text_equivalence"] == "verified_literal_backslash_escapes"
    assert result["start"] == 0 and result["end"] == 7
    assert result["status"] == "pending_review"
    assert result["source_status"] == "PENDENTE_GEOMETRIA"


def test_explicit_conflicting_checkbox_status_not_promoted():
    raw = record("abc\\ndef", status="pending_review",
                 source_status="DIVERGENCIA_CHECKBOX")
    result = resolve_text([raw], {"14498623": "abc\ndef"})[0]
    assert result["status"] == "pending_review"
    assert result["source_status"] == "DIVERGENCIA_CHECKBOX"


def test_exact_is_not_marked_as_escaped():
    row = resolve_text([record("abc\ndef")], {"14498623": "abc\ndef"})[0]
    assert row["text_equivalence"] == "exact"
    assert "source_text_raw" not in row


def test_non_equivalent_text_still_blocks_processing():
    with pytest.raises(ValueError, match="Span-text mismatch"):
        resolve_text([record("abc\\ndex")], {"14498623": "abc\ndef"})


def test_raw_unavailable_explicitly_marked():
    row = resolve_text([record("", status="consolidated",
                               source_status="CONCORDANCIA_ORIGINAL")],
                       {"14498623": "abc\ndef"})[0]
    assert row["text_equivalence"] == "source_excerpt_unavailable"
    assert row["text"] == "abc\ndef"


def test_ambiguous_sequences_not_over_normalized():
    # JSON literal slash text must not be normalized unless it equals original slice.
    with pytest.raises(ValueError, match="Span-text mismatch"):
        resolve_text([record("abc\\ndef")], {"14498623": "abcXdef"})
