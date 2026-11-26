"""Synthetic contract tests; no access to judicial documents or model weights."""
import pytest

from legal_nlp.modeling.token_alignment import (
    AlignmentError, Span, plan_windows, project_bilou, slice_tags,
)


def test_single_and_multi_token_spans():
    text = "art. Código Civil"
    offsets = [(0, 3), (3, 4), (5, 11), (12, 17)]
    spans = [
        Span("a", "NER", "ENT_NORMA_ARTIGO", 0, 4),
        Span("a", "NER", "ENT_LEI_CODIFICADA", 5, 17),
    ]
    assert project_bilou(text, "a", "NER", spans, offsets) == [
        "B-ENT_NORMA_ARTIGO", "L-ENT_NORMA_ARTIGO",
        "B-ENT_LEI_CODIFICADA", "L-ENT_LEI_CODIFICADA",
    ]


def test_one_token_unit_label():
    assert project_bilou("art.", "a", "NER", [
        Span("a", "NER", "ENT_NORMA_ARTIGO", 0, 4)
    ], [(0, 4)]) == ["U-ENT_NORMA_ARTIGO"]


def test_unicode_offsets_are_source_codepoints():
    text = "É decisão válida"
    assert project_bilou(text, "a", "SEG", [
        Span("a", "SEG", "SEG_FUNDAMENTO_DECISAO", 2, 9)
    ], [(0, 1), (2, 9), (10, 16)]) == [
        "O", "U-SEG_FUNDAMENTO_DECISAO", "O"
    ]


def test_overlap_is_rejected_without_pruning():
    with pytest.raises(AlignmentError, match="Overlapping"):
        project_bilou("abcdef", "a", "NER", [
            Span("a", "NER", "ENT_TERMO_IA", 0, 4),
            Span("a", "NER", "ENT_CLASSE", 2, 6),
        ], [(0, 2), (2, 4), (4, 6)])


def test_nested_span_is_rejected_without_pruning():
    with pytest.raises(AlignmentError, match="Overlapping"):
        project_bilou("abcdef", "a", "SEG", [
            Span("a", "SEG", "SEG_RELATORIO", 0, 6),
            Span("a", "SEG", "SEG_CONTEXTO_IA", 2, 4),
        ], [(0, 2), (2, 4), (4, 6)])


def test_boundary_mismatch_is_explicit():
    with pytest.raises(AlignmentError, match="boundary"):
        project_bilou("Código", "a", "NER", [
            Span("a", "NER", "ENT_TERMO_IA", 1, 6),
        ], [(0, 6)])


def test_zero_token_document():
    assert plan_windows(0) == []


def test_invalid_window_configurations():
    for kwargs in [
        {"max_length": 2},
        {"max_length": 5, "stride": 3},
        {"max_length": 6, "stride": -1},
    ]:
        with pytest.raises(ValueError):
            plan_windows(6, **kwargs)


def test_windows_cover_every_token_once_in_loss():
    windows = plan_windows(1100, max_length=512, stride=128)
    assert len(windows) == 3
    tags = ["O"] * 1100
    coverage = [0] * 1100
    for window in windows:
        _, mask = slice_tags(tags, window)
        for offset, supervised in enumerate(mask, window.start):
            coverage[offset] += supervised
    assert set(coverage) == {1}


def test_global_segmentation_boundaries_survive_windows():
    text = "x" * 1000
    offsets = [(i, i + 1) for i in range(1000)]
    tags = project_bilou(text, "a", "SEG", [
        Span("a", "SEG", "SEG_RELATORIO", 100, 900),
    ], offsets)
    assert tags[100] == "B-SEG_RELATORIO"
    assert tags[899] == "L-SEG_RELATORIO"
    windows = plan_windows(1000, max_length=512, stride=128)
    assert any(
        any(tag == "I-SEG_RELATORIO" for tag in slice_tags(tags, w)[0])
        and "B-SEG_RELATORIO" not in slice_tags(tags, w)[0]
        for w in windows[1:]
    )
