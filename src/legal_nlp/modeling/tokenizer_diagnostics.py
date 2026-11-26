"""Diagnostic-only inspection of fast tokenizer offsets on synthetic text.

No judicial corpus, model weights, gold targets or offset corrections.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .hf_tokenizer_adapter import load_fast_tokenizer


TEXT = "EMENTA. O Código Civil e a inteligência artificial são citados."
SPAN_TEXT = "Código Civil"


def inspect(tokenizer, text: str = TEXT, span_text: str = SPAN_TEXT) -> dict:
    start = text.index(span_text)
    end = start + len(span_text)
    encoding = tokenizer(
        text, add_special_tokens=False, truncation=False, padding=False,
        return_offsets_mapping=True, return_attention_mask=False,
    )
    ids = list(encoding["input_ids"])
    offsets = [tuple(pair) for pair in encoding["offset_mapping"]]
    if len(ids) != len(offsets):
        raise ValueError("ID/offset lengths mismatch")
    nonempty = [(i, a, b) for i, (a, b) in enumerate(offsets) if a < b]
    intersects = [(i, a, b) for i, a, b in nonempty if a < end and start < b]
    left = intersects[0][0] if intersects else 0
    right = intersects[-1][0] + 1 if intersects else 0
    nearby = [
        {"index": i, "start": a, "end": b,
         "token": tokenizer.convert_ids_to_tokens(ids[i])}
        for i, (a, b) in enumerate(offsets)
        if max(0, left-2) <= i < min(len(ids), right+2)
    ]
    zero = [i for i, (a, b) in enumerate(offsets) if a == b]
    backtrack = [
        i for i in range(1, len(offsets))
        if offsets[i][0] < offsets[i-1][1]
        and offsets[i][0] != offsets[i][1]
    ]
    special_empty = tokenizer(
        "", add_special_tokens=True, return_special_tokens_mask=True,
    )
    return {
        "tokenizer_class": type(tokenizer).__name__,
        "is_fast": tokenizer.is_fast,
        "token_count": len(ids),
        "target_span": [start, end],
        "target_aligned": bool(intersects)
        and offsets[left][0] == start and offsets[right-1][1] == end,
        "zero_length_offsets": zero,
        "backtracking_nonempty_offsets": backtrack,
        "neighbor_tokens": nearby,
        "empty_special_ids": list(special_empty["input_ids"]),
        "empty_special_mask": list(special_empty["special_tokens_mask"]),
        "declared_special_count": tokenizer.num_special_tokens_to_add(pair=False),
        "has_prepare_for_model": callable(getattr(tokenizer, "prepare_for_model", None)),
        "has_build_inputs_with_special_tokens": callable(
            getattr(tokenizer, "build_inputs_with_special_tokens", None)
        ),
    }


def run(config: Path, *, allow_download: bool = False) -> dict:
    cfg = json.loads(config.read_text(encoding="utf-8"))
    if cfg.get("training_ready") is not False:
        raise ValueError("Expected design-only registry")
    results = []
    for item in cfg["encoder_benchmark"]["encoders"]:
        try:
            tokenizer = load_fast_tokenizer(
                item["checkpoint"], allow_download=allow_download,
            )
            result = inspect(tokenizer)
            results.append({"encoder": item["key"], "status": "inspected", **result})
        except Exception as exc:
            results.append({
                "encoder": item["key"], "status": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
            })
    return {
        "schema_version": "tokenizer_diagnostics.v1",
        "synthetic_only": True,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/model_experiments.v1.json"),
    )
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.config, allow_download=args.allow_download),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
