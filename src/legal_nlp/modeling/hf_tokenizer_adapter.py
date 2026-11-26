"""Fast Hugging Face tokenizer adapter; source character offsets stay canonical.

Full-document tokenization is untruncated, without special tokens. Model-
specific special tokens are inserted per window. No training or gold promotion.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Sequence

from .token_alignment import Span, plan_windows, project_bilou


class TokenizerAdapterError(ValueError):
    """Tokenizer metadata cannot preserve the requested mapping."""


@dataclass(frozen=True)
class TokenizedDocument:
    document_id: str
    text_sha256: str
    input_ids: tuple[int, ...]
    offsets: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class PreparedWindow:
    document_id: str
    index: int
    token_start: int
    token_end: int
    input_ids: tuple[int, ...]
    attention_mask: tuple[int, ...]
    special_tokens_mask: tuple[int, ...]
    global_token_indices: tuple[int | None, ...]
    offset_mapping: tuple[tuple[int, int] | None, ...]
    loss_mask: tuple[int, ...]
    bilou_tags: tuple[str | None, ...]
    token_type_ids: tuple[int, ...] | None = None


def _check_fast(tokenizer: Any) -> None:
    if getattr(tokenizer, "is_fast", False) is not True:
        raise TokenizerAdapterError("A fast tokenizer with offset_mapping is mandatory")


def load_fast_tokenizer(checkpoint: str, *, allow_download: bool = False) -> Any:
    """Load with local cache only by default; network downloads are opt-in."""
    if not isinstance(checkpoint, str) or not checkpoint.strip():
        raise ValueError("Checkpoint must be nonempty")
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Install the optional 'tokenization' dependencies") from exc
    tokenizer = AutoTokenizer.from_pretrained(
        checkpoint, use_fast=True, local_files_only=not allow_download,
    )
    _check_fast(tokenizer)
    return tokenizer


def tokenize_document(tokenizer: Any, document_id: str, text: str) -> TokenizedDocument:
    """Return global subtoken IDs and source-text character offsets."""
    _check_fast(tokenizer)
    if not isinstance(document_id, str) or not document_id:
        raise ValueError("document_id is required")
    if not isinstance(text, str):
        raise TypeError("Original text must be a string")
    raw = tokenizer(
        text, add_special_tokens=False, return_offsets_mapping=True,
        truncation=False, padding=False, return_attention_mask=False,
    )
    ids, offsets = raw["input_ids"], raw["offset_mapping"]
    if (not isinstance(ids, (list, tuple))
            or not isinstance(offsets, (list, tuple)) or len(ids) != len(offsets)):
        raise TokenizerAdapterError("Invalid untruncated fast-tokenizer encoding")
    previous_end = 0
    for token_id, pair in zip(ids, offsets):
        if type(token_id) is not int:
            raise TokenizerAdapterError("Token IDs must be integers")
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or any(type(v) is not int for v in pair)):
            raise TokenizerAdapterError("Invalid offset pair")
        start, end = pair
        if not 0 <= start < end <= len(text) or start < previous_end:
            raise TokenizerAdapterError("Offsets are not monotonic nonempty character intervals")
        previous_end = end
    return TokenizedDocument(
        document_id=document_id,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        input_ids=tuple(ids),
        offsets=tuple(tuple(pair) for pair in offsets),
    )


def encode_windows(
    tokenizer: Any,
    document: TokenizedDocument,
    *,
    tags: Sequence[str] | None = None,
    max_length: int = 512,
    stride: int = 128,
) -> list[PreparedWindow]:
    """Create model-ready windows and loss masks without double supervision.

    All labels are determined on the global document before windowing. This
    preserves cross-window B/I/L sequences (but does not repair predictions).
    """
    _check_fast(tokenizer)
    if tags is not None and len(tags) != len(document.input_ids):
        raise TokenizerAdapterError("BILOU vector length differs from global tokens")
    count = tokenizer.num_special_tokens_to_add(pair=False)
    if type(count) is not int or count < 0:
        raise TokenizerAdapterError("Invalid number of special tokens")
    windows = plan_windows(
        len(document.input_ids), max_length=max_length, stride=stride,
        special_tokens_count=count,
    )
    outputs: list[PreparedWindow] = []
    for index, bounds in enumerate(windows):
        raw_ids = list(document.input_ids[bounds.start:bounds.end])
        prepared = tokenizer.prepare_for_model(
            raw_ids, add_special_tokens=True, truncation=False, padding=False,
            return_attention_mask=True, return_special_tokens_mask=True,
        )
        ids = prepared["input_ids"]
        masks = prepared["special_tokens_mask"]
        attention = prepared["attention_mask"]
        types = prepared.get("token_type_ids")
        if not all(isinstance(x, (tuple, list)) for x in (ids, masks, attention)):
            raise TokenizerAdapterError("Malformed tokenizer window")
        if len(ids) > max_length or not (len(ids) == len(masks) == len(attention)):
            raise TokenizerAdapterError("Window exceeds model length")
        if any(type(m) is not int or m not in (0, 1) for m in masks):
            raise TokenizerAdapterError("Malformed special token mask")
        if any(type(a) is not int or a != 1 for a in attention):
            raise TokenizerAdapterError("Unexpected unpadded attention mask")
        if sum(m == 0 for m in masks) != len(raw_ids):
            raise TokenizerAdapterError("Special-token insertion changed content count")
        if [tok for tok, mask in zip(ids, masks) if mask == 0] != raw_ids:
            raise TokenizerAdapterError("Special-token insertion changed source tokens")
        if types is not None and len(types) != len(ids):
            raise TokenizerAdapterError("Malformed token_type_ids")
        global_indices: list[int | None] = []
        source_offsets: list[tuple[int, int] | None] = []
        window_tags: list[str | None] = []
        loss_mask: list[int] = []
        position = bounds.start
        for mask in masks:
            if mask:
                global_indices.append(None)
                source_offsets.append(None)
                window_tags.append(None)
                loss_mask.append(0)
            else:
                global_indices.append(position)
                source_offsets.append(document.offsets[position])
                window_tags.append(tags[position] if tags is not None else None)
                loss_mask.append(int(bounds.loss_start <= position < bounds.loss_end))
                position += 1
        if position != bounds.end:
            raise TokenizerAdapterError("Global token mapping failed")
        outputs.append(PreparedWindow(
            document_id=document.document_id, index=index,
            token_start=bounds.start, token_end=bounds.end,
            input_ids=tuple(ids), attention_mask=tuple(attention),
            special_tokens_mask=tuple(masks),
            global_token_indices=tuple(global_indices),
            offset_mapping=tuple(source_offsets),
            loss_mask=tuple(loss_mask),
            bilou_tags=tuple(window_tags),
            token_type_ids=tuple(types) if types is not None else None,
        ))
    return outputs


def prepare_bilou_document(
    tokenizer: Any,
    document_id: str,
    text: str,
    task: str,
    spans: Sequence[Span],
    *,
    max_length: int = 512,
    stride: int = 128,
) -> tuple[TokenizedDocument, list[PreparedWindow]]:
    """Strict projection of explicitly supplied spans; no gold assumption."""
    doc = tokenize_document(tokenizer, document_id, text)
    tags = project_bilou(text, document_id, task, spans, doc.offsets)
    return doc, encode_windows(
        tokenizer, doc, tags=tags, max_length=max_length, stride=stride,
    )


def stitch_window_tags(
    windows: Sequence[PreparedWindow],
    predicted_tags: Sequence[Sequence[str]],
    total_tokens: int,
) -> list[str]:
    """Reassemble one document-global tag for each token using loss ownership."""
    if type(total_tokens) is not int or total_tokens < 0:
        raise ValueError("Invalid global token count")
    if len(windows) != len(predicted_tags):
        raise TokenizerAdapterError("Window and prediction counts differ")
    out: list[str | None] = [None] * total_tokens
    for window, preds in zip(windows, predicted_tags):
        if len(preds) != len(window.input_ids):
            raise TokenizerAdapterError("Prediction length does not match window")
        for token_index, owns, tag in zip(
            window.global_token_indices, window.loss_mask, preds,
        ):
            if not owns:
                continue
            if (token_index is None or not 0 <= token_index < total_tokens
                    or out[token_index] is not None):
                raise TokenizerAdapterError("Duplicate or invalid prediction ownership")
            if not isinstance(tag, str) or not tag:
                raise TokenizerAdapterError("Missing owned-token prediction")
            out[token_index] = tag
    if any(item is None for item in out):
        raise TokenizerAdapterError("Document tokens lack predictions")
    return [item for item in out if item is not None]


def decode_bilou(
    document: TokenizedDocument, task: str, tags: Sequence[str],
) -> list[Span]:
    """Strict document-global BILOU decoder to source character intervals."""
    if task not in {"NER", "SEG"} or len(tags) != len(document.offsets):
        raise TokenizerAdapterError("Invalid task or BILOU length")
    output: list[Span] = []
    current_label: str | None = None
    current_start: int | None = None
    for tag, (start, end) in zip(tags, document.offsets):
        if not isinstance(tag, str):
            raise TokenizerAdapterError("Non-string BILOU tag")
        if tag == "O":
            if current_label is not None:
                raise TokenizerAdapterError("Unclosed span before O")
            continue
        if len(tag) < 3 or tag[0] not in "BILU" or tag[1] != "-":
            raise TokenizerAdapterError("Malformed BILOU tag")
        prefix, label = tag[0], tag[2:]
        if not label.startswith("ENT_" if task == "NER" else "SEG_"):
            raise TokenizerAdapterError("BILOU label/task mismatch")
        if prefix == "U":
            if current_label is not None:
                raise TokenizerAdapterError("Unclosed span before U")
            output.append(Span(document.document_id, task, label, start, end))
        elif prefix == "B":
            if current_label is not None:
                raise TokenizerAdapterError("Unclosed span before B")
            current_label, current_start = label, start
        elif prefix == "I":
            if current_label != label:
                raise TokenizerAdapterError("Invalid I transition")
        else:
            if current_label != label or current_start is None:
                raise TokenizerAdapterError("Invalid L transition")
            output.append(Span(
                document.document_id, task, label, current_start, end,
            ))
            current_label, current_start = None, None
    if current_label is not None:
        raise TokenizerAdapterError("Unclosed trailing span")
    return output
