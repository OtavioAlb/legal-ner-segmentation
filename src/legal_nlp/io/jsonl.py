"""Shared JSON Lines serialization used by legacy Phase 1 pipelines.

Exact compatibility contract: UTF-8; skip empty/whitespace-only input lines;
UTF-8 output, one JSON object per line with ensure_ascii=False,
sort_keys=True, and LF line endings. No normalization or adjudication.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    with Path(path).open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
