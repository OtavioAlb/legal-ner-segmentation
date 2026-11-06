"""Non-destructive, reproducible Phase 1 sanitization.

Only source-validated spans are emitted for supervised use. No voting,
LLM correction, annotation deduplication, or overlap pruning occurs.
Private generated data remains local beneath data/interim/.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .audit import classify_mismatch


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def sanitize_phase1(
    dataset_dir: str | Path,
    output_dir: str | Path,
    labels_path: str | Path = "configs/labels.json",
    rules_path: str | Path = "configs/sanitization_rules.json",
) -> dict[str, Any]:
    """Build a new supervised view, preserving all ingested source records."""
    dataset_dir, output_dir = Path(dataset_dir), Path(output_dir)
    docs = _read_jsonl(dataset_dir / "documents.jsonl")
    anns = _read_jsonl(dataset_dir / "annotations.jsonl")
    label_config = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    rules = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    known = set(label_config["labels"])
    aliases = rules["approved_label_aliases"]
    allowed_mismatch = set(rules["accepted_text_equivalences"])
    if not set(aliases.values()) <= known:
        raise ValueError("Sanitization rules refer to unknown canonical labels")
    if not allowed_mismatch <= {"case_only"}:
        raise ValueError("Only case_only is authorized without offset reconciliation")

    by_id = {doc["document_id"]: doc for doc in docs}
    if len(by_id) != len(docs):
        raise ValueError("Duplicate document identifiers make linkage unsafe")

    accepted: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    issue_counts: Counter[str] = Counter()
    recovery_counts: Counter[str] = Counter()
    initial_eligible = 0
    source_ids: set[str] = set()

    for ann in anns:
        annotation_id = ann["annotation_id"]
        if annotation_id in source_ids:
            raise ValueError("Duplicate annotation identifiers in input")
        source_ids.add(annotation_id)
        original_issues = set(ann.get("issues") or [])
        selection = ann.get("target_selection_status")
        reasons: list[str] = []
        pending: list[dict[str, Any]] = []
        baseline_valid = not original_issues and selection in {
            "reviewed_final", "original_confirmed_by_reviewers"
        }
        if baseline_valid:
            initial_eligible += 1

        if selection not in {"reviewed_final", "original_confirmed_by_reviewers"}:
            reasons.append("NO_VALIDATED_TARGET_SELECTION")

        # These are not reparable by the narrow, explicitly approved rules.
        unsupported_issues = original_issues - {
            "UNKNOWN_DOCUMENT", "UNKNOWN_LABEL", "SPAN_TEXT_MISMATCH"
        }
        reasons.extend(sorted(unsupported_issues))

        start, end = ann.get("start"), ann.get("end")
        if (
            not isinstance(start, int) or isinstance(start, bool)
            or not isinstance(end, int) or isinstance(end, bool)
            or start < 0 or end <= start
        ):
            reasons.append("INVALID_SPAN_BOUNDS")

        document_id = ann.get("document_id")
        doc = by_id.get(document_id)
        excerpt = ann.get("span_text_source")

        if doc is None and not reasons:
            # Only truly absent source IDs are eligible, not invalid/ambiguous IDs.
            source_id = ann.get("source_document_id")
            if source_id is not None and str(source_id).strip():
                reasons.append("DOCUMENT_ID_PRESENT_BUT_UNRESOLVED")
            elif not isinstance(excerpt, str) or not excerpt:
                reasons.append("DOCUMENT_LINKAGE_REQUIRES_EXACT_EXCERPT")
            else:
                matches = [
                    candidate for candidate in docs
                    if end <= len(candidate["text"])
                    and candidate["text"][start:end] == excerpt
                ]
                if len(matches) == 1:
                    doc = matches[0]
                    document_id = doc["document_id"]
                    pending.append({
                        "annotation_id": annotation_id,
                        "source_row": ann["source_row"],
                        "rule": "unique_exact_document_span",
                        "field": "document_id",
                        "before": None,
                        "after": document_id,
                        "candidate_count": 1,
                    })
                else:
                    reasons.append(
                        "DOCUMENT_LINKAGE_ZERO_CANDIDATES"
                        if not matches else "DOCUMENT_LINKAGE_AMBIGUOUS"
                    )
        if doc is None and not reasons:
            reasons.append("DOCUMENT_NOT_FOUND")

        label_before = ann.get("label_original")
        canonical = ann.get("label_canonical")
        if canonical is None and isinstance(label_before, str):
            target = aliases.get(label_before)
            if target in known:
                canonical = target
                pending.append({
                    "annotation_id": annotation_id,
                    "source_row": ann["source_row"],
                    "rule": "explicit_lexical_alias",
                    "field": "label_canonical",
                    "before": label_before,
                    "after": target,
                })
        if canonical not in known:
            reasons.append("UNRESOLVED_CANONICAL_LABEL")

        if not reasons and end > len(doc["text"]):
            reasons.append("END_OUT_OF_BOUNDS")

        text_equivalence = "not_supplied"
        if not reasons and isinstance(excerpt, str):
            actual_text = doc["text"][start:end]
            if actual_text == excerpt:
                text_equivalence = "exact"
            else:
                kind = classify_mismatch(actual_text, excerpt)
                if kind in allowed_mismatch:
                    text_equivalence = kind
                    pending.append({
                        "annotation_id": annotation_id,
                        "source_row": ann["source_row"],
                        "rule": "verified_case_only_text_equivalence",
                        "field": "span_text_source",
                        "before": excerpt,
                        "after": actual_text,
                        "offsets_unchanged": True,
                    })
                else:
                    reasons.append("UNRESOLVED_SPAN_TEXT_MISMATCH")

        if reasons:
            unique_reasons = sorted(set(reasons))
            issue_counts.update(unique_reasons)
            excluded.append({
                "annotation_id": annotation_id,
                "source_row": ann.get("source_row"),
                "original_issues": sorted(original_issues),
                "target_selection_status": selection,
                "reasons": unique_reasons,
                "final_status": "excluded_from_sanitized_supervision",
            })
            continue

        task = "NER" if canonical.startswith("ENT_") else "SEG"
        if not (canonical.startswith("ENT_") or canonical.startswith("SEG_")):
            raise ValueError("Unexpected canonical label prefix")
        accepted.append({
            "annotation_id": annotation_id,
            "source_row": ann["source_row"],
            "document_id": document_id,
            "annotator_id": ann.get("annotator_id"),
            "task": task,
            "label": canonical,
            "start": start,
            "end": end,
            "source_of_truth": (
                "original_confirmed_by_reviewers"
                if selection == "original_confirmed_by_reviewers"
                else "evaluator_reviewed_fields"
            ),
            "text_equivalence": text_equivalence,
            "sanitization_rule_ids": [action["rule"] for action in pending],
        })
        actions.extend(pending)
        recovery_counts.update(action["rule"] for action in pending)

    if len(accepted) + len(excluded) != len(anns):
        raise AssertionError("Sanitization must account for every annotation")
    if len(accepted) < initial_eligible:
        raise AssertionError("Sanitization must not remove previously eligible annotations")

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "sanitized_annotations.jsonl", accepted)
    _write_jsonl(output_dir / "sanitization_actions.jsonl", actions)
    _write_jsonl(output_dir / "sanitization_exclusions.jsonl", excluded)
    summary = {
        "sanitization_schema_version": "1.0.0",
        "input_annotation_count": len(anns),
        "baseline_eligible_count": initial_eligible,
        "sanitized_supervised_count": len(accepted),
        "newly_eligible_count": len(accepted) - initial_eligible,
        "excluded_count": len(excluded),
        "actions_count": len(actions),
        "recovery_by_rule": dict(sorted(recovery_counts.items())),
        "exclusion_reason_counts": dict(sorted(issue_counts.items())),
        "task_counts": dict(sorted(Counter(row["task"] for row in accepted).items())),
        "policy": "explicit deterministic rules; preserve provenance; exclude unresolved",
    }
    (output_dir / "sanitization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Sanitize Phase 1 without modifying raw inputs")
    parser.add_argument("--dataset", type=Path, default=Path("data/interim/phase_1"))
    parser.add_argument("--output", type=Path, default=Path("data/interim/phase_1/sanitized"))
    parser.add_argument("--labels", type=Path, default=Path("configs/labels.json"))
    parser.add_argument("--rules", type=Path, default=Path("configs/sanitization_rules.json"))
    args = parser.parse_args()
    print(json.dumps(sanitize_phase1(args.dataset, args.output, args.labels, args.rules),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
