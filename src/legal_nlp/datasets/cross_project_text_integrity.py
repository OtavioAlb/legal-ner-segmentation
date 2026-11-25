"""Check whether Phase 2 projects use exactly the same immutable decision texts.

No offsets, labels, statuses or content are corrected. Report contains only
hashes and lengths; it must still remain in the local gitignored data tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from ..io.label_studio import load
from .versioned_corpus import _text_from_task


def compare_document_texts(original, evaluation_11, evaluation_17):
    exports = {
        "original": load(original),
        "11": load(evaluation_11),
        "17": load(evaluation_17),
    }
    ids = set(exports["original"])
    if not ids or any(set(exports[p]) != ids for p in ("11", "17")):
        raise ValueError("Document sets differ")
    rows = []
    mismatches = []
    for doc in sorted(ids, key=int):
        texts = {
            name: _text_from_task(tasks[doc])
            for name, tasks in exports.items()
        }
        hashes = {
            name: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for name, value in texts.items()
        }
        exact = len(set(hashes.values())) == 1
        item = {
            "idacordao": doc,
            "exact_same_text_all_projects": exact,
            "sha256": hashes,
            "lengths": {name: len(text) for name, text in texts.items()},
            "equals_original": {
                p: hashes[p] == hashes["original"] for p in ("11", "17")
            },
        }
        rows.append(item)
        if not exact:
            mismatches.append(item)
    return {
        "schema_version": "1.0.0",
        "document_count": len(ids),
        "identical_document_count": len(ids) - len(mismatches),
        "different_document_count": len(mismatches),
        "different_documents": mismatches,
        "comparisons": rows,
        "source_modified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--evaluation-11", required=True, type=Path)
    parser.add_argument("--evaluation-17", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite report")
    if not args.output.parent.is_dir():
        raise FileNotFoundError("Output directory must already exist")
    result = compare_document_texts(
        args.original, args.evaluation_11, args.evaluation_17
    )
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "document_count": result["document_count"],
        "identical_document_count": result["identical_document_count"],
        "different_document_count": result["different_document_count"],
        "different_document_ids": [
            item["idacordao"] for item in result["different_documents"]
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
