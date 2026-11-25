"""Internal consistency between a reviewer's explicit checkbox and evaluated span.

This is NOT the cross-review decision disagreement test.
"""
from __future__ import annotations


def divergence_problem(original, evaluated, checkbox):
    """Return one deterministic individual inconsistency, or None.

    Keep legacy wording so existing worksheets and human workflows remain stable.
    """
    if original is None or evaluated is None:
        raise ValueError("Checkbox conflict requires original and evaluated regions")
    normalized = (checkbox or "").strip().casefold()
    if normalized == "limite impreciso" and (
        original["start"], original["end"]
    ) == (evaluated["start"], evaluated["end"]):
        return "limite igual original"
    if normalized == "incorreto" and original["label"] == evaluated["label"]:
        return "label igual original"
    if normalized == "certo":
        label_changed = original["label"] != evaluated["label"]
        limit_changed = (
            original["start"], original["end"]
        ) != (evaluated["start"], evaluated["end"])
        if label_changed and limit_changed:
            return "checkbox certo com label e limite diferentes do original"
        if label_changed:
            return "checkbox certo com label diferente do original"
        if limit_changed:
            return "checkbox certo com limite diferente do original"
    return None
