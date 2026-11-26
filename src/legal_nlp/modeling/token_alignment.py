"""Lossless character-span -> global subtoken BILOU projection and window planning.

The caller supplies fast-tokenizer offset_mapping for the *entire document*
with add_special_tokens=False. It must NOT be normalized or truncated.
This component is purely computational and never interprets pending spans as gold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


class AlignmentError(ValueError):
    """The requested flat token representation cannot preserve the source spans."""


@dataclass(frozen=True)
class Span:
    document_id: str
    task: str
    label: str
    start: int
    end: int


@dataclass(frozen=True)
class TokenWindow:
    """Indices in the global tokenizer output; end is exclusive."""
    start: int
    end: int
    loss_start: int
    loss_end: int


def project_bilou(
    text: str,
    document_id: str,
    task: str,
    spans: Sequence[Span],
    offsets: Sequence[tuple[int, int]],
) -> list[str]:
    """Strict flat BILOU tags over all subtokens, without boundary snapping.

    For overlapping/nested regions use a separate representable layer or a
    span-oriented model. Across ENT/SEG tasks, call this independently.
    """
    if task not in {"NER", "SEG"} or not document_id or not isinstance(text, str):
        raise ValueError("Invalid document/task/text")
    previous_start = -1
    for start, end in offsets:
        if any(type(x) is not int for x in (start, end)):
            raise AlignmentError("Tokenizer offsets must be integers")
        if not 0 <= start < end <= len(text) or start < previous_start:
            raise AlignmentError("Global subtoken offsets must have monotonic starts and valid bounds")
        # Some tokenizers return overlapping intervals; validate actual
        # conflicts only inside a supervised span, never hide them globally.
        previous_start = start

    ordered = sorted(spans, key=lambda s: (s.start, s.end, s.label))
    for s in ordered:
        if s.document_id != document_id or s.task != task:
            raise AlignmentError("Mixed document or annotation task")
        if not s.label.startswith("ENT_" if task == "NER" else "SEG_"):
            raise AlignmentError("Invalid label prefix for task")
        if type(s.start) is not int or type(s.end) is not int or not 0 <= s.start < s.end <= len(text):
            raise AlignmentError("Invalid character-span geometry")
    for left, right in zip(ordered, ordered[1:]):
        if left.end > right.start:
            raise AlignmentError("Overlapping or nested spans cannot be represented in flat BILOU")

    tags = ["O"] * len(offsets)
    for span in ordered:
        # For whitespace-prefixed tokenizers, [start_of_space, end) and
        # [start_of_word, end) can yield identical BILOU tags. The decoder
        # consistently excludes leading whitespace; consequently a gold
        # span that *includes* it is NOT losslessly representable.
        # Preserve the gold unchanged and require an alternative
        # span/boundary model or explicit adjudication for such regions.
        if text[span.start].isspace():
            raise AlignmentError(
                "Leading-whitespace annotation boundary is ambiguous in flat BILOU"
            )
        indexes = [
            i for i, (a, b) in enumerate(offsets)
            if a < span.end and span.start < b
        ]
        if not indexes:
            raise AlignmentError("Span has no tokenizer coverage")
        first_start, first_end = offsets[indexes[0]]
        # ByteLevel tokenizers may include the space preceding a word:
        # [9,16) for a source annotation beginning at 10. Trim only
        # whitespace in a *derived alignment boundary*, not source gold.
        if first_start != span.start and not (
            first_start < span.start < first_end
            and text[first_start:span.start].isspace()
        ):
            raise AlignmentError("Span start boundary does not align with tokenizer offsets")
        if offsets[indexes[-1]][1] != span.end:
            raise AlignmentError("Span end boundary does not align with tokenizer offsets")
        previous_content_end = -1
        for i in indexes:
            a, b = offsets[i]
            if a < span.start and not text[a:span.start].isspace():
                raise AlignmentError("Tokenizer subtoken crosses span boundary")
            if b > span.end:
                raise AlignmentError("Tokenizer subtoken crosses span boundary")
            content_start = max(a, span.start)
            if content_start < previous_content_end and not text[content_start:previous_content_end].isspace():
                raise AlignmentError("Ambiguous overlapping token offsets inside annotated span")
            previous_content_end = max(previous_content_end, b)
        if any(tags[i] != "O" for i in indexes):
            raise AlignmentError("Multiple spans would supervise the same token")
        if len(indexes) == 1:
            tags[indexes[0]] = "U-" + span.label
        else:
            tags[indexes[0]] = "B-" + span.label
            for i in indexes[1:-1]:
                tags[i] = "I-" + span.label
            tags[indexes[-1]] = "L-" + span.label
    return tags


def plan_windows(
    token_count: int,
    *,
    max_length: int = 512,
    stride: int = 128,
    special_tokens_count: int = 2,
) -> list[TokenWindow]:
    """Document-global windows with overlap as context, never duplicate loss.

    The next window's overlapped prefix provides context but is not
    supervised a second time. Global BILOU tags may start/end outside a
    window; do not re-encode fragments as new entities.
    """
    for n in (token_count, max_length, stride, special_tokens_count):
        if type(n) is not int:
            raise ValueError("Window arguments must be integers")
    usable = max_length - special_tokens_count
    if token_count < 0 or usable <= 0 or stride < 0 or stride >= usable:
        raise ValueError("Invalid window lengths or stride")
    if token_count == 0:
        return []
    step = usable - stride
    result: list[TokenWindow] = []
    pos = 0
    covered_until = 0
    while pos < token_count:
        end = min(pos + usable, token_count)
        result.append(TokenWindow(
            start=pos,
            end=end,
            loss_start=max(pos, covered_until),
            loss_end=end,
        ))
        covered_until = end
        if end == token_count:
            break
        pos += step
    return result


def slice_tags(tags: Sequence[str], window: TokenWindow) -> tuple[list[str], list[int]]:
    """Return window-local tags and 0/1 loss mask for global token indices."""
    if not (0 <= window.start <= window.loss_start <= window.loss_end == window.end <= len(tags)):
        raise ValueError("Invalid window bounds")
    selected = list(tags[window.start:window.end])
    mask = [int(window.loss_start <= i < window.loss_end)
            for i in range(window.start, window.end)]
    return selected, mask
