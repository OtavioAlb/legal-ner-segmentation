"""Synthetic-only tests for tokenizer diagnostics; no external downloads."""
from legal_nlp.modeling.tokenizer_diagnostics import inspect


class FakeTokenizer:
    is_fast = True

    def __init__(self, offsets=None):
        self.offsets = offsets

    def __call__(self, text, **kwargs):
        if text == "":
            return {"input_ids": [101, 102], "special_tokens_mask": [1, 1]}
        offsets = self.offsets or [(i, i+1) for i in range(len(text))]
        return {"input_ids": list(range(len(offsets))), "offset_mapping": offsets}

    def convert_ids_to_tokens(self, token_id):
        return f"tok_{token_id}"

    def num_special_tokens_to_add(self, pair=False):
        assert not pair
        return 2


def test_diagnostic_reports_alignment_without_snapping():
    text = "abc def xyz"
    result = inspect(FakeTokenizer(), text, "def")
    assert result["target_span"] == [4, 7]
    assert result["target_aligned"]
    assert result["zero_length_offsets"] == []
    assert result["has_prepare_for_model"] is False
    assert result["empty_special_ids"] == [101, 102]


def test_diagnostic_reports_zero_offsets():
    text = "abc def xyz"
    offsets = [(0, 1), (1, 2), (2, 3), (3, 3), (4, 7), (8, 11)]
    result = inspect(FakeTokenizer(offsets), text, "def")
    assert result["target_aligned"]
    assert result["zero_length_offsets"] == [3]


def test_diagnostic_reports_boundary_mismatch():
    text = "abc def xyz"
    offsets = [(0, 3), (3, 7), (8, 11)]
    result = inspect(FakeTokenizer(offsets), text, "def")
    assert result["target_aligned"] is False
    assert result["neighbor_tokens"][1]["start"] == 3
