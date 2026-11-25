"""Fail-closed examination of all source regions in all Phase 2 exports.

Textual mismatches are *not* corrections to annotations. They identify regions
that must be quarantined in an opt-in diagnostic snapshot. References are
kept by project; full source evidence remains in immutable input exports.
"""
from __future__ import annotations

from collections import Counter

from ..io.label_studio import extract, load


def scan_phase2_regions(original, review_11, review_17, text_from_task) -> tuple[set[tuple[str, str]], list[dict], dict]:
    exports = {
        "original": load(original), "11": load(review_11), "17": load(review_17),
    }
    original_ids = set(exports["original"])
    if not original_ids or any(set(exports[p]) != original_ids for p in ("11", "17")):
        raise ValueError("Document sets differ")
    affected = set()
    findings = []
    categories = Counter()
    for doc in sorted(original_ids, key=int):
        canonical_text = text_from_task(exports["original"][doc])
        for project in ("original", "11", "17"):
            project_text = text_from_task(exports[project][doc])
            if project_text != canonical_text:
                raise ValueError(f"Different document text across Phase 2 projects: {doc}")
            spans, _, _ = extract(exports[project][doc])
            for rid, span in sorted(spans.items()):
                start, end, raw = span["start"], span["end"], span["text"]
                if end > len(canonical_text):
                    category = "invalid_offsets"
                elif not isinstance(raw, str) or not raw:
                    category = "source_excerpt_unavailable"
                else:
                    expected = canonical_text[start:end]
                    if raw == expected:
                        category = "exact"
                    elif raw.replace("\\n", "\n").replace("\\t", "\t") == expected:
                        category = "verified_literal_backslash_escapes"
                    else:
                        category = "unresolved_text_mismatch"
                categories[category] += 1
                if category in {"exact", "verified_literal_backslash_escapes"}:
                    continue
                affected.add((doc, rid))
                findings.append({
                    "idacordao": doc,
                    "region_id": rid,
                    "project": project,
                    "label": span["label"],
                    "start": start,
                    "end": end,
                    "reason": category,
                })
    return affected, findings, dict(sorted(categories.items()))
