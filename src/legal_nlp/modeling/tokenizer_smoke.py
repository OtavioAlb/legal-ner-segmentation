"""Offline-by-default smoke test for the five configured HF fast tokenizers.

Only synthetic text is used. Model weights and judicial documents are never loaded.
The CLI may download tokenizer configuration files only with --allow-download.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .hf_tokenizer_adapter import (
    decode_bilou, load_fast_tokenizer, prepare_bilou_document, stitch_window_tags,
)
from .token_alignment import Span


def run_smoke(config: Path, *, allow_download: bool = False) -> dict:
    cfg = json.loads(config.read_text(encoding="utf-8"))
    if cfg.get("training_ready") is not False or cfg.get("status") != "design_only":
        raise ValueError("Expected a design-only registry")
    encoders = cfg["encoder_benchmark"]["encoders"]
    if len(encoders) != 5 or len({e["key"] for e in encoders}) != 5:
        raise ValueError("Expected five distinct encoder candidates")

    text = "EMENTA. O Código Civil e a inteligência artificial são citados."
    start = text.index("Código Civil")
    end = start + len("Código Civil")
    expected = Span("synthetic", "NER", "ENT_LEI_CODIFICADA", start, end)
    results = []
    for item in encoders:
        key = item["key"]
        checkpoint = item["checkpoint"]
        try:
            tokenizer = load_fast_tokenizer(checkpoint, allow_download=allow_download)
            document, windows = prepare_bilou_document(
                tokenizer, "synthetic", text, "NER", [expected],
                max_length=512, stride=128,
            )
            reconstructed = stitch_window_tags(
                windows, [[tag or "O" for tag in w.bilou_tags] for w in windows],
                len(document.input_ids),
            )
            if decode_bilou(
                document, "NER", reconstructed, source_text=text
            ) != [expected]:
                raise ValueError("Round-trip span mismatch")
            results.append({
                "encoder": key, "checkpoint": checkpoint, "status": "passed",
                "token_count": len(document.input_ids),
                "window_count": len(windows),
            })
        except Exception as exc:
            results.append({
                "encoder": key, "checkpoint": checkpoint, "status": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
            })
    return {
        "schema_version": "tokenizer_smoke.v1",
        "synthetic_only": True,
        "download_opt_in": bool(allow_download),
        "results": results,
        "passed": sum(r["status"] == "passed" for r in results),
        "failed": sum(r["status"] == "failed" for r in results),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/model_experiments.v1.json"),
    )
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()
    report = run_smoke(args.config, allow_download=args.allow_download)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
