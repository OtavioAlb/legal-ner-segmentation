"""Label Studio Phase 2 export adapter.

Preserves the exact legacy parsing/validation contract. Broader normalization
must be a separate, regression-tested change.
"""
from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict

def load(path):
    tasks = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(tasks, list):
        raise ValueError("Expected list of Label Studio tasks")
    result = {}
    for task in tasks:
        key = str(task["data"]["idacordao"])
        if key in result:
            raise ValueError(f"Duplicate document: {key}")
        result[key] = task
    return result


def annotation(task):
    active = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
    if len(active) != 1:
        raise ValueError(f"Expected one active annotation: {task.get('id')}")
    return active[0]


def extract(task):
    spans, choices, comments = {}, {}, defaultdict(list)
    for item in annotation(task).get("result", []):
        kind, rid, value = item.get("type"), item.get("id"), item.get("value") or {}
        if kind not in {"labels", "choices", "textarea"}:
            continue
        if not rid:
            raise ValueError("Missing region_id")
        if kind == "labels":
            labels, start, end = value.get("labels") or [], value.get("start"), value.get("end")
            if (rid in spans or len(labels) != 1 or type(start) is not int
                    or type(end) is not int or not 0 <= start < end):
                raise ValueError(f"Invalid or duplicate region {rid}")
            spans[rid] = {"label": labels[0], "start": start,
                          "end": end, "text": value.get("text", "")}
        elif kind == "choices":
            if rid in choices:
                raise ValueError(f"Duplicate choice for {rid}")
            values = value.get("choices") or []
            choices[rid] = values[0] if len(values) == 1 else None
        else:
            values = value.get("text") or []
            comments[rid].extend(values if isinstance(values, list) else [values])
    return spans, choices, {k: " | ".join(map(str, v)) for k, v in comments.items()}


