"""Phase 2: read-only evidence triage for new Label Studio region IDs.

New comments are *reviewer declarations*, not positive votes or gold labels.
Results contain IDs, offsets and reviewer comments and MUST remain local/ignored.
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from .phase2_auto_review import docid, existing_choice_index, labels_index, load, only_annotation


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).strip()


def _comments(items: list[dict], region_id: str) -> list[str]:
    found = []
    for item in items:
        if item.get("id") != region_id or item.get("type") != "textarea":
            continue
        texts = (item.get("value") or {}).get("text") or []
        for item_text in texts if isinstance(texts, list) else [texts]:
            if isinstance(item_text, str) and item_text.strip():
                found.append(item_text)
    return found


def _comment_category(comments: list[str]) -> str:
    normalized = _normalize(" | ".join(comments))
    if not normalized:
        return "sem_observacao"
    if normalized == "nova anotacao":
        return "nova_anotacao_exata"
    if "nova anotacao" in normalized or "novas anotacoes" in normalized:
        return "nova_anotacao_com_contexto"
    if any(term in normalized for term in
           ("nova observacao", "nova notacao", "nova classificacao")):
        return "possivel_declaracao_variante"
    return "outra_observacao"


def _signature(region: dict) -> tuple[tuple[str, ...], int, int]:
    value = region["value"]
    return tuple(value["labels"]), value["start"], value["end"]


def _iou(a: tuple, b: tuple) -> float:
    _, start_a, end_a = a
    _, start_b, end_b = b
    intersection = max(0, min(end_a, end_b) - max(start_a, start_b))
    union = max(end_a, end_b) - min(start_a, start_b)
    return intersection / union if union else 0.0


def triage(evaluations: list[dict]):
    """Return summary, new-ID rows and missing-original rows; never mutate input."""
    reviews = {}
    document_snapshots = {}
    for task in evaluations:
        document, project = docid(task), str(task.get("project"))
        if project not in {"11", "17"} or (document, project) in reviews:
            raise ValueError(f"Invalid or duplicate evaluated document/project: {document}/{project}")
        ann = only_annotation(task)
        snapshot = labels_index((ann.get("prediction") or {}).get("result") or [])
        present = labels_index(ann.get("result") or [])
        if not snapshot:
            raise ValueError(f"Missing verified original snapshot: {document}/{project}")
        signatures = {rid: _signature(region) for rid, region in snapshot.items()}
        if document in document_snapshots and document_snapshots[document] != signatures:
            raise ValueError(f"Original snapshots disagree across reviews: {document}")
        document_snapshots[document] = signatures
        reviews[(document, project)] = (ann, snapshot, present)

    # Index additions across independent reviews; exact matches are evidence only.
    new_signatures = defaultdict(list)
    for (document, project), (_, snapshot, present) in reviews.items():
        for rid, region in present.items():
            if rid not in snapshot:
                new_signatures[document, _signature(region)].append((project, rid))

    rows = []
    missing_rows = []
    summary = Counter()
    for (document, project), (ann, snapshot, present) in sorted(reviews.items()):
        original_signatures = {rid: _signature(region) for rid, region in snapshot.items()}
        new_ids = set(present) - set(snapshot)
        choices = existing_choice_index(ann.get("result") or [])
        absent_ids = set(snapshot) - set(present)
        summary["reviews"] += 1
        for rid in sorted(absent_ids):
            old = original_signatures[rid]
            possible = [nid for nid in new_ids if _iou(old, _signature(present[nid])) > 0 and
                        (old[0] == _signature(present[nid])[0] or
                         _iou(old, _signature(present[nid])) >= 0.8)]
            missing_rows.append({"idacordao": document, "project": project,
                                 "region_id": rid, "candidate_new_ids": sorted(possible),
                                 "status": "original_ausente_pendente"})
            summary["originals_missing"] += 1
            if possible:
                summary["missing_with_replacement_candidates"] += 1

        for rid in sorted(new_ids):
            if choices.get(rid):
                summary["new_with_existing_choice"] += 1
                continue
            sig = _signature(present[rid])
            comments = _comments(ann["result"], rid)
            category = _comment_category(comments)
            exact_original = sorted(oid for oid, old in original_signatures.items() if old == sig)
            same_boundary_other_label = sorted(
                oid for oid, old in original_signatures.items()
                if old[1:] == sig[1:] and old[0] != sig[0]
            )
            duplicate_new = sorted(
                nid for nid in new_ids if nid != rid and _signature(present[nid]) == sig
            )
            strong_overlap = sorted(
                oid for oid, old in original_signatures.items()
                if old[0] == sig[0] and _iou(old, sig) >= 0.8
            )
            crossreview = sorted(f"{pr}:{other_id}" for pr, other_id in
                                 new_signatures[document, sig] if pr != project)
            flags = []
            if exact_original:
                flags.append("exact_original_duplicate")
            if duplicate_new:
                flags.append("duplicate_new_in_same_review")
            if same_boundary_other_label:
                flags.append("same_boundary_different_label")
            if strong_overlap:
                flags.append("strong_overlap_same_label")
            if flags:
                triage_status = "inspecionar_possivel_duplicacao_ou_substituicao"
            elif category in {"nova_anotacao_exata", "nova_anotacao_com_contexto"}:
                triage_status = "candidato_inclusao_declarada"
            elif category == "possivel_declaracao_variante":
                triage_status = "candidato_inclusao_variante"
            else:
                triage_status = "inclusao_nao_confirmada"

            rows.append({
                "idacordao": document, "project": project,
                "reviewer_id": ann.get("completed_by"), "region_id": rid,
                "labels": list(sig[0]), "start": sig[1], "end": sig[2],
                "observacoes": comments, "comment_category": category,
                "structural_flags": flags,
                "original_exact_ids": exact_original,
                "same_boundary_other_label_ids": same_boundary_other_label,
                "duplicate_new_ids": duplicate_new,
                "strong_overlap_original_ids": strong_overlap,
                "crossreview_exact_signatures": crossreview,
                "triage_status": triage_status,
                "gold_status": "not_adjudicated",
            })
            summary["new_without_choice"] += 1
            summary[f"comment:{category}"] += 1
            summary[f"triage:{triage_status}"] += 1
            if crossreview:
                summary["crossreview_exact_signature"] += 1

    report = {"schema_version": "1.0", "counts": dict(sorted(summary.items())),
              "policy": "Observations/overlap are triage evidence, not gold or an explicit correctness vote."}
    return report, rows, missing_rows


def run(input_path: Path, output_dir: Path):
    input_path, output_dir = Path(input_path), Path(output_dir)
    if output_dir.resolve() == input_path.resolve() or output_dir.resolve() in input_path.resolve().parents:
        raise ValueError("Output directory must not contain an input")
    report, new_rows, missing_rows = triage(load(input_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "triage_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for file, records in (("new_regions_triage.jsonl", new_rows),
                          ("missing_originals_triage.jsonl", missing_rows)):
        with (output_dir / file).open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluations", type=Path, required=True,
                        help="Output JSON from phase2_auto_review with original snapshots verified")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.evaluations, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
