"""Refine Phase 2 structural alerts; never modify or adjudicate annotations.

Only structural metadata is emitted. Raw documents and individual evaluation
outputs remain local and must not be committed to the public repository.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from .phase2_auto_review import docid, labels_index, load, only_annotation


def _signature(item):
    v = item["value"]
    return tuple(v["labels"]), v["start"], v["end"]


def _family(labels):
    if labels and labels[0].startswith("ENT_"):
        return "NER"
    if labels and labels[0].startswith("SEG_"):
        return "SEG"
    return "UNKNOWN"


def _choices(items):
    out = {}
    for item in items:
        if item.get("type") == "choices":
            out.setdefault(item.get("id"), []).append(item)
    return out


def _choice_evidence(entries):
    values, origins = [], []
    for entry in entries:
        values.extend((entry.get("value") or {}).get("choices") or [])
        origins.append(str(entry.get("origin") or "unknown"))
    return {
        "choice_values": values,
        "choice_origins": origins,
        "explicit_nonautomatic": bool(values)
        and not any("automatic" in x.lower() for x in origins),
    }


def _read_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8-sig") as fp:
        for i, line in enumerate(fp, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"Invalid triage line: {i}")
                rows.append(row)
    return rows


def refine(evaluations, new_region_rows):
    """Provide mutually exclusive primary categories plus independent evidence.

    The category is diagnostic only; do not automatically remove duplicate
    annotations, replace original IDs, or use these regions as gold.
    """
    tasks = {}
    for task in evaluations:
        did, project = docid(task), str(task.get("project"))
        if project not in {"11", "17"} or (did, project) in tasks:
            raise ValueError(f"Duplicate or invalid review: {did}/{project}")
        ann = only_annotation(task)
        original = labels_index((ann.get("prediction") or {}).get("result") or [])
        if not original:
            raise ValueError(f"Missing verified original snapshot: {did}/{project}")
        reviewed = labels_index(ann.get("result") or [])
        tasks[did, project] = ann, original, reviewed, _choices(ann.get("result") or [])

    summary, findings, seen = Counter(), [], set()
    for row in new_region_rows:
        flags = row.get("structural_flags") or []
        if not isinstance(flags, list):
            raise ValueError("structural_flags must be a list")
        if not flags:
            continue
        did, project, rid = str(row["idacordao"]), str(row["project"]), str(row["region_id"])
        key = did, project, rid
        if key in seen:
            raise ValueError(f"Duplicate triage region: {key}")
        seen.add(key)
        if (did, project) not in tasks:
            raise ValueError(f"Unmatched triage review: {key}")
        ann, original, reviewed, choices = tasks[did, project]
        if rid in original or rid not in reviewed:
            raise ValueError(f"Alert must refer to a new ID: {key}")
        sig = _signature(reviewed[rid])
        if sig != (tuple(row.get("labels") or []), row.get("start"), row.get("end")):
            raise ValueError(f"Triage signature differs: {key}")
        if choices.get(rid):
            raise ValueError(f"Already evaluated region: {key}")

        exact = row.get("original_exact_ids") or []
        different = row.get("same_boundary_other_label_ids") or []
        new_duplicates = row.get("duplicate_new_ids") or []
        overlaps = row.get("strong_overlap_original_ids") or []
        for name, ids in (("exact", exact), ("different", different),
                          ("new_duplicates", new_duplicates), ("overlaps", overlaps)):
            if not isinstance(ids, list):
                raise ValueError(f"{name} must be a list")

        originals_evidence = []
        for oid in sorted(set(exact + different + overlaps)):
            if oid not in original:
                raise ValueError(f"Unknown original ID {oid}: {key}")
            old = _signature(original[oid])
            existing = _signature(reviewed[oid]) if oid in reviewed else None
            originals_evidence.append({
                "original_region_id": oid,
                "original_label": list(old[0]),
                "original_start": old[1],
                "original_end": old[2],
                "original_family": _family(old[0]),
                "original_region_still_present": existing is not None,
                "original_region_relabelled": bool(existing and old[0] != existing[0]),
                "reviewed_label_for_original_id": list(existing[0]) if existing else None,
                "reviewed_start_for_original_id": existing[1] if existing else None,
                "reviewed_end_for_original_id": existing[2] if existing else None,
                **_choice_evidence(choices.get(oid, [])),
            })

        duplicate_evidence = []
        for nid in new_duplicates:
            if nid == rid or nid in original or nid not in reviewed:
                raise ValueError(f"Invalid new-region duplicate ID {nid}: {key}")
            if _signature(reviewed[nid]) != sig:
                raise ValueError(f"Non-identical duplicate candidate: {key}")
            duplicate_evidence.append({
                "region_id": nid,
                **_choice_evidence(choices.get(nid, [])),
            })

        if exact:
            category, action = (
                "copia_exata_do_original",
                "revisar_copia_original_e_eventual_reclassificacao")
        elif new_duplicates:
            category, action = (
                "duplicacao_entre_novas_regioes",
                "revisar_regioes_novas_com_mesma_assinatura")
        elif different:
            families = {_family(_signature(original[oid])[0]) for oid in different}
            family = _family(sig[0])
            if family not in {"NER", "SEG"} or "UNKNOWN" in families:
                category = "coincidencia_rotulo_ambigua"
            elif families == ({"SEG"} if family == "NER" else {"NER"}):
                category = "coincidencia_ner_seg"
            elif families == {family}:
                category = "rotulo_alternativo_mesma_tarefa"
            else:
                category = "coincidencia_mista"
            action = ("verificar_sobreposicao_ner_seg_sem_exclusao_automatica"
                      if category == "coincidencia_ner_seg"
                      else "revisar_reclassificacao_e_votos_existentes")
        elif overlaps:
            category, action = "ajuste_de_limite_possivel", "revisar_limite_e_eventual_substituicao"
        else:
            raise ValueError(f"Alert has no supported candidate evidence: {key}")

        findings.append({
            "idacordao": did, "project": project,
            "reviewer_id": ann.get("completed_by"), "region_id": rid,
            "new_label": list(sig[0]), "new_start": sig[1], "new_end": sig[2],
            "new_family": _family(sig[0]),
            "comment_category": row.get("comment_category", "not_recorded"),
            "structural_flags": flags,
            "primary_category": category,
            "recommended_action": action,
            "original_evidence": originals_evidence,
            "duplicate_new_evidence": duplicate_evidence,
            "crossreview_exact_signatures": row.get("crossreview_exact_signatures") or [],
            "decision_status": "pending_human_adjudication",
            "gold_status": "not_adjudicated",
        })
        summary["alerts"] += 1
        summary[f"category:{category}"] += 1
        summary[f"project:{project}"] += 1
        if any(x["explicit_nonautomatic"] for x in originals_evidence):
            summary["alerts_with_related_explicit_human_choice"] += 1
        if any(x["explicit_nonautomatic"] for x in duplicate_evidence):
            summary["alerts_with_related_new_region_human_choice"] += 1
        if row.get("comment_category") not in {"sem_observacao", None}:
            summary["alerts_with_comment_evidence"] += 1

    return {
        "schema_version": "1.0",
        "evaluation_records": len(evaluations),
        "counts": dict(sorted(summary.items())),
        "policy": "Diagnostic evidence only; NER/SEG overlaps may be valid; no gold or automatic deletion.",
    }, findings


def run(evaluations_path, triage_path, output_dir):
    evaluations_path, triage_path, output_dir = (
        Path(evaluations_path), Path(triage_path), Path(output_dir))
    targets = [
        output_dir / "structural_alerts_summary.json",
        output_dir / "structural_alerts_refined.jsonl",
        output_dir / "structural_alerts_refined.csv",
    ]
    inputs = {evaluations_path.resolve(), triage_path.resolve()}
    if any(target.resolve() in inputs for target in targets):
        raise ValueError("Output would overwrite an input")
    report, rows = refine(load(evaluations_path), _read_jsonl(triage_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    with targets[1].open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    columns = [
        "idacordao", "project", "reviewer_id", "region_id", "new_label",
        "new_start", "new_end", "comment_category", "structural_flags",
        "primary_category", "recommended_action", "original_evidence",
        "duplicate_new_evidence", "decision_status", "gold_status",
    ]
    with targets[2].open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: json.dumps(row[field], ensure_ascii=False)
                if isinstance(row.get(field), list) else row.get(field)
                for field in columns
            })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluations", type=Path, required=True)
    parser.add_argument("--triage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.evaluations, args.triage, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
