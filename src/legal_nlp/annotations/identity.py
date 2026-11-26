"""Determine effective Phase 2 reviewer; preserve Teresa/Tiago replacement behavior."""
from __future__ import annotations

from ..io.label_studio import annotation

NAMES = {"3": "Tiago", "4": "Mariana", "5": "Guilherme", "7": "Letícia",
         "8": "Emily", "9": "Giulia", "10": "Teresa", "12": "Mariana"}
def identity(task):
    ann = annotation(task)
    completed, updated = str(ann.get("completed_by", "")), str(task.get("updated_by", ""))
    if (completed == "10" and updated == "3"
            and any(x.get("type") == "choices" for x in ann.get("result", []))):
        return "3", "substituição", True
    if completed == "10":
        return "10", "Teresa", False
    return completed, NAMES.get(completed, "ID " + completed), True


