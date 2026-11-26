"""Synthetic adapter tests: no network, weights, or private judicial text."""
import hashlib

import pytest

from legal_nlp.modeling.token_alignment import AlignmentError, Span
from legal_nlp.modeling.hf_tokenizer_adapter import (
    TokenizerAdapterError, decode_bilou, encode_windows,
    load_fast_tokenizer, prepare_bilou_document,
    stitch_window_tags, tokenize_document,
)


class FakeFastTokenizer:
    is_fast = True

    def __init__(self, specials=(101, 102), bad_mask=False):
        self.specials = specials
        self.bad_mask = bad_mask

    def __call__(self, text, **kwargs):
        if kwargs.get("add_special_tokens"):
            ids = [self.specials[0], *[ord(char) for char in text], *self.specials[1:]]
            mask = [1, *([0] * len(text)), *([1] * (len(self.specials) - 1))]
            if self.bad_mask:
                mask[-1] = 2
            return {"input_ids": ids, "special_tokens_mask": mask}
        assert kwargs == {
            "add_special_tokens": False,
            "return_offsets_mapping": True,
            "truncation": False,
            "padding": False,
            "return_attention_mask": False,
        }
        return {
            "input_ids": [ord(char) for char in text],
            "offset_mapping": [(i, i + 1) for i in range(len(text))],
        }

    def num_special_tokens_to_add(self, pair=False):
        assert pair is False
        return len(self.specials)

    def prepare_for_model(self, tokens, **kwargs):
        assert kwargs["add_special_tokens"] is True
        assert kwargs["truncation"] is False
        ids = [self.specials[0], *tokens, *self.specials[1:]]
        special_mask = [1, *([0] * len(tokens)), *([1] * (len(self.specials) - 1))]
        if self.bad_mask:
            special_mask[-1] = 0
        return {
            "input_ids": ids,
            "special_tokens_mask": special_mask,
            "attention_mask": [1] * len(ids),
            "token_type_ids": [0] * len(ids),
        }


class SlowTokenizer(FakeFastTokenizer):
    is_fast = False


def test_unicode_round_trip_multiple_windows():
    text = "É ótima!"
    gold = Span("doc", "NER", "ENT_TERMO_IA", 2, 7)
    doc, windows = prepare_bilou_document(
        FakeFastTokenizer(), "doc", text, "NER", [gold],
        max_length=6, stride=1,
    )
    assert doc.text_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert len(windows) > 1
    assert all(len(w.input_ids) <= 6 for w in windows)
    assert all(w.offset_mapping[0] is None and w.loss_mask[0] == 0 for w in windows)
    preds = [[tag or "O" for tag in w.bilou_tags] for w in windows]
    stitched = stitch_window_tags(windows, preds, len(doc.input_ids))
    assert decode_bilou(doc, "NER", stitched) == [gold]


def test_one_special_token_layout():
    tokenizer = FakeFastTokenizer(specials=(11,))
    doc = tokenize_document(tokenizer, "id", "abcdef")
    windows = encode_windows(tokenizer, doc, max_length=4, stride=1)
    assert windows[0].special_tokens_mask == (1, 0, 0, 0)
    assert all(len(w.input_ids) <= 4 for w in windows)


def test_three_special_tokens_reduce_payload():
    tokenizer = FakeFastTokenizer(specials=(5, 6, 7))
    doc = tokenize_document(tokenizer, "id", "abcdef")
    windows = encode_windows(tokenizer, doc, max_length=5, stride=1)
    assert windows[0].token_end - windows[0].token_start == 2


def test_single_loss_owner_per_global_token():
    tokenizer = FakeFastTokenizer()
    doc = tokenize_document(tokenizer, "id", "a" * 25)
    windows = encode_windows(tokenizer, doc, max_length=8, stride=2)
    owners = [
        index for w in windows
        for index, active in zip(w.global_token_indices, w.loss_mask)
        if active
    ]
    assert sorted(owners) == list(range(25))
    assert all(w.bilou_tags == (None,) * len(w.input_ids) for w in windows)


def test_reject_slow_tokenizer():
    with pytest.raises(TokenizerAdapterError, match="fast tokenizer"):
        tokenize_document(SlowTokenizer(), "id", "abc")


def test_reject_alignment_without_silent_snapping():
    class Trimmed(FakeFastTokenizer):
        def __call__(self, text, **kwargs):
            return {
                "input_ids": [1],
                "offset_mapping": [(0, len(text) - 1)],
            }

    with pytest.raises(AlignmentError, match="boundary"):
        prepare_bilou_document(
            Trimmed(), "id", "abc", "NER",
            [Span("id", "NER", "ENT_TERMO_IA", 0, 3)],
        )


def test_reject_wrong_special_mask():
    tokenizer = FakeFastTokenizer(bad_mask=True)
    doc = tokenize_document(tokenizer, "id", "abc")
    with pytest.raises(TokenizerAdapterError, match="[Ss]pecial"):
        encode_windows(tokenizer, doc)


def test_missing_predictions_are_rejected():
    tokenizer = FakeFastTokenizer()
    doc = tokenize_document(tokenizer, "id", "a" * 14)
    windows = encode_windows(tokenizer, doc, max_length=6, stride=1)
    predictions = [["O"] * len(w.input_ids) for w in windows]
    with pytest.raises(TokenizerAdapterError, match="lack predictions"):
        stitch_window_tags(windows[:1], predictions[:1], len(doc.input_ids))
    with pytest.raises(TokenizerAdapterError, match="counts differ"):
        stitch_window_tags(windows, predictions[:-1], len(doc.input_ids))


def test_invalid_bilou_transitions_are_rejected():
    doc = tokenize_document(FakeFastTokenizer(), "id", "abc")
    with pytest.raises(TokenizerAdapterError, match="Invalid I"):
        decode_bilou(doc, "NER", ["I-ENT_TERMO_IA", "O", "O"])
    with pytest.raises(TokenizerAdapterError, match="Unclosed"):
        decode_bilou(doc, "NER", ["B-ENT_TERMO_IA", "O", "O"])


def test_load_tokenizer_does_not_download_by_default(monkeypatch):
    import builtins

    importer = builtins.__import__
    calls = []

    class AutoTokenizerStub:
        @staticmethod
        def from_pretrained(name, **kwargs):
            calls.append((name, kwargs))
            return FakeFastTokenizer()

    class TransformersStub:
        AutoTokenizer = AutoTokenizerStub

    def fake_import(name, *args, **kwargs):
        if name == "transformers":
            return TransformersStub()
        return importer(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    load_fast_tokenizer("local/checkpoint")
    assert calls == [
        ("local/checkpoint", {"use_fast": True, "local_files_only": True})
    ]


def test_bytelevel_prefix_whitespace_roundtrip():
    from legal_nlp.modeling.token_alignment import project_bilou
    text = "O Código Civil"
    offsets = [(0, 1), (1, 8), (8, 14)]
    gold = Span("id", "NER", "ENT_LEI_CODIFICADA", 2, 14)
    tags = project_bilou(text, "id", "NER", [gold], offsets)
    assert tags == ["O", "B-ENT_LEI_CODIFICADA", "L-ENT_LEI_CODIFICADA"]
    from legal_nlp.modeling.hf_tokenizer_adapter import TokenizedDocument
    doc = TokenizedDocument(
        "id", hashlib.sha256(text.encode("utf-8")).hexdigest(),
        (1, 2, 3), tuple(offsets),
    )
    assert decode_bilou(doc, "NER", tags, source_text=text) == [gold]


def test_overlapping_offsets_outside_gold_do_not_block_projection():
    from legal_nlp.modeling.token_alignment import project_bilou
    text = "a b Código"
    # Two tokenizer tokens cover the same initial non-entity character.
    offsets = [(0, 2), (0, 1), (2, 3), (3, 4), (4, 10)]
    gold = Span("id", "NER", "ENT_TERMO_IA", 4, 10)
    assert project_bilou(text, "id", "NER", [gold], offsets)[-1] == "U-ENT_TERMO_IA"


def test_overlapping_non_whitespace_inside_gold_is_rejected():
    from legal_nlp.modeling.token_alignment import project_bilou
    text = "Código"
    offsets = [(0, 4), (2, 6)]
    with pytest.raises(AlignmentError, match="Ambiguous overlapping"):
        project_bilou(text, "id", "NER", [
            Span("id", "NER", "ENT_TERMO_IA", 0, 6),
        ], offsets)
