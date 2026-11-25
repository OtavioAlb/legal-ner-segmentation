"""Synthetic-only invariants for new contracts; legacy code is untouched."""

from dataclasses import FrozenInstanceError

import pytest

from legal_nlp.core import AdjudicationStatus, AnnotationRecord, Document, Span


def test_exact_text_and_exclusive_offsets():
    doc = Document(document_id="acordao-1", text="ação e revisão", source="test-fixture")
    span = Span(
        document_id="acordao-1", region_id="reg-1", task="NER",
        label="ENT_TERMO_IA", start=0, end=4, text="ação",
    )
    assert span.matches_document(doc)
    assert len(doc.sha256) == 64
    assert not Span(
        document_id="acordao-1", region_id="reg-2", task="NER",
        label="ENT_TERMO_IA", start=0, end=4, text="acao",
    ).matches_document(doc)


def test_overlaps_are_allowed_without_auto_consolidation():
    spans = [
        Span("a", "r1", "NER", "ENT_A", 0, 4, "abcd"),
        Span("a", "r2", "NER", "ENT_B", 2, 5, "cde"),
    ]
    assert len(spans) == 2
    assert spans[0].end > spans[1].start


@pytest.mark.parametrize("start,end", [(-1, 2), (1, 1), (2, 1), (False, 3)])
def test_invalid_offsets_are_rejected_for_canonical_spans(start, end):
    with pytest.raises((TypeError, ValueError)):
        Span("a", "r1", "SEG", "SEG_EMENTA", start, end, "abc")


def test_record_retains_reviewer_provenance_and_pending_state():
    span = Span("a", "reg", "SEG", "SEG_EMENTA", 0, 4, "abcd")
    row = AnnotationRecord(
        span=span,
        source_system="label_studio",
        source_annotation_id="original-10",
        original_reviewer_id="10",
        effective_reviewer_id="3",
    )
    assert row.adjudication_status is AdjudicationStatus.PENDING_REVIEW
    assert row.original_reviewer_id != row.effective_reviewer_id
    with pytest.raises(FrozenInstanceError):
        row.source_system = "changed"


def test_invalid_status_rejected():
    span = Span("a", "reg", "NER", "ENT_A", 0, 1, "x")
    with pytest.raises(TypeError):
        AnnotationRecord(span, "label_studio", "1", adjudication_status="consolidated")
