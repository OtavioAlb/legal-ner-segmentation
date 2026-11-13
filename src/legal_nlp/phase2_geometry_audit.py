"""Deterministic structural audit for Phase 2 Label Studio data.

Never edit original labels/offsets. A correction is a matching reviewer proposal,
not a corrected original. Choices are diagnostic only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

SHEETS = ("Resumo", "Motivos_pendencia", "Revisao_originais", "Revisao_novas",
          "Consolidados", "Duplicatas_exatas", "Por_acordao", "Instrucoes")


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("Expected list of tasks")
    tasks = {}
    for task in data:
        doc = str(task["data"]["idacordao"])
        if doc in tasks:
            raise ValueError(f"Duplicate document: {doc}")
        tasks[doc] = task
    return tasks


def annotation(task):
    active = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
    if len(active) != 1:
        raise ValueError(f"Expected one active annotation: {task.get('id')}")
    return active[0]


def extract(task):
    spans, choices, comments = {}, {}, defaultdict(list)
    for entry in annotation(task).get("result", []):
        kind, rid, v = entry.get("type"), entry.get("id"), entry.get("value") or {}
        if kind not in ("labels", "choices", "textarea"):
            continue
        if not rid:
            raise ValueError("Region without id")
        if kind == "labels":
            labels, start, end = v.get("labels") or [], v.get("start"), v.get("end")
            if (rid in spans or len(labels) != 1 or type(start) is not int
                    or type(end) is not int or not 0 <= start < end):
                raise ValueError(f"Invalid or duplicate span {rid}")
            spans[rid] = dict(label=labels[0], start=start, end=end, text=v.get("text", ""))
        elif kind == "choices":
            if rid in choices:
                raise ValueError(f"Repeated choice for {rid}")
            values = v.get("choices") or []
            choices[rid] = values[0] if len(values) == 1 else None
        else:
            value = v.get("text") or []
            comments[rid].extend(value if isinstance(value, list) else [value])
    return spans, choices, {k: " | ".join(map(str, v)) for k, v in comments.items()}


def geometry(region):
    if region is None:
        return None
    return region["label"], region["start"], region["end"]


def reviewer(task):
    ann = annotation(task)
    completed, updated = str(ann.get("completed_by", "")), str(task.get("updated_by", ""))
    has_choice = any(x.get("type") == "choices" for x in ann.get("result", []))
    # Replacement on 13 Nov retained Teresa's completed_by but Tiago updated the task.
    if completed == "10" and updated == "3" and has_choice:
        return "3", "substituicao_tiago", True
    if completed == "10":
        return "10", "teresa_nao_substituida", False
    return completed, "avaliacao_original", True


def audit(original, evaluation_11, evaluation_17):
    src = {"original": load(original), "11": load(evaluation_11),
           "17": load(evaluation_17)}
    originals, reviews = src["original"], {p: src[p] for p in ("11", "17")}
    if not originals or any(set(reviews[p]) != set(originals) for p in reviews):
        raise ValueError("Document sets must match")
    sheets = {name: [] for name in SHEETS}
    reasons, states = Counter(), Counter()
    for doc in sorted(originals, key=int):
        base, _, _ = extract(originals[doc])
        ev = {p: extract(reviews[p][doc]) for p in reviews}
        reviewer_info = {p: reviewer(reviews[p][doc]) for p in reviews}
        complete = all(reviewer_info[p][2] for p in reviews)
        originals_by_geometry = defaultdict(list)
        for rid, item in base.items():
            originals_by_geometry[geometry(item)].append(rid)
        for key, ids in sorted(originals_by_geometry.items()):
            if len(ids) > 1:
                sheets["Duplicatas_exatas"].append({
                    "idacordao": doc, "label": key[0], "start": key[1],
                    "end": key[2], "region_ids": ";".join(sorted(ids)),
                    "quantidade": len(ids)})
        per_document = Counter()
        for rid, old in sorted(base.items()):
            a, b = ev["11"][0].get(rid), ev["17"][0].get(rid)
            same = a is not None and b is not None and geometry(a) == geometry(b)
            if not complete:
                status, reason = "PENDENTE_AVALIADOR", "aguardando_substituicao_tiago"
            elif a is None or b is None:
                status, reason = "PENDENTE_AUSENCIA", "ausente_em_avaliacao"
            elif not same:
                status, reason = "PENDENTE_DIVERGENCIA", "divergencia_label_ou_offset"
            elif geometry(a) == geometry(old):
                status, reason = "CONCORDANCIA_ORIGINAL", ""
            else:
                status, reason = "CONCORDANCIA_ALTERACAO", ""
            per_document[status] += 1
            if reason:
                reasons[reason] += 1
            row = {
                "idacordao": doc, "region_id_original": rid,
                "label_original": old["label"], "start_original": old["start"],
                "end_original": old["end"], "texto_original": old["text"],
                "classe": "NER" if old["label"].startswith("ENT_") else
                "SEG" if old["label"].startswith("SEG_") else "UNKNOWN",
                "avaliador_11_id": reviewer_info["11"][0],
                "avaliador_17_id": reviewer_info["17"][0],
                "origem_11": reviewer_info["11"][1],
                "origem_17": reviewer_info["17"][1],
                "label_11": a["label"] if a else "",
                "start_11": a["start"] if a else "",
                "end_11": a["end"] if a else "",
                "label_17": b["label"] if b else "",
                "start_17": b["start"] if b else "",
                "end_17": b["end"] if b else "",
                "checkbox_11": ev["11"][1].get(rid, ""),
                "checkbox_17": ev["17"][1].get(rid, ""),
                "comentario_11": ev["11"][2].get(rid, ""),
                "comentario_17": ev["17"][2].get(rid, ""),
                "status": status, "motivo": reason,
            }
            sheets["Revisao_originais"].append(row)
            if status.startswith("CONCORDANCIA_"):
                sheets["Consolidados"].append({
                    **row, "label_proposta_concordante": a["label"],
                    "start_proposta_concordante": a["start"],
                    "end_proposta_concordante": a["end"],
                    "original_inalterado": geometry(a) == geometry(old),
                })
        new_groups = defaultdict(lambda: {"11": [], "17": []})
        for project in reviews:
            for rid, region in ev[project][0].items():
                if rid not in base:
                    new_groups[geometry(region)][project].append(rid)
        for geom, group in sorted(new_groups.items()):
            paired = bool(group["11"] and group["17"])
            reason = "nova_coincidente_pendente" if paired else "nova_unilateral_pendente"
            if not complete:
                reason = "nova_aguardando_tiago"
            reasons[reason] += 1
            per_document["NOVAS_PENDENTES"] += 1
            sheets["Revisao_novas"].append({
                "idacordao": doc, "label_proposto": geom[0],
                "start_proposto": geom[1], "end_proposto": geom[2],
                "ids_11": ";".join(sorted(group["11"])),
                "ids_17": ";".join(sorted(group["17"])),
                "avaliador_11_id": reviewer_info["11"][0],
                "avaliador_17_id": reviewer_info["17"][0],
                "presente_11": bool(group["11"]), "presente_17": bool(group["17"]),
                "mesma_geometria_original_ids":
                ";".join(sorted(originals_by_geometry.get(geom, []))),
                "situacao": reason, "adjudicada": False,
            })
        sheets["Por_acordao"].append({
            "idacordao": doc, "originais": len(base),
            "concordancia_original": per_document["CONCORDANCIA_ORIGINAL"],
            "concordancia_alteracao": per_document["CONCORDANCIA_ALTERACAO"],
            "pendentes_originais":
            sum(v for k, v in per_document.items() if k.startswith("PENDENTE_")),
            "novas_pendentes": per_document["NOVAS_PENDENTES"],
            "avaliacao_completa": complete,
        })
        states.update(per_document)
    sheets["Motivos_pendencia"] = [
        {"motivo": reason, "quantidade": count}
        for reason, count in sorted(reasons.items())]
    paths = {"original": original, "11": evaluation_11, "17": evaluation_17}
    hashes = {k: hashlib.sha256(Path(path).read_bytes()).hexdigest()
              for k, path in paths.items()}
    totals = [
        ("acordaos", len(originals)),
        ("regioes_originais", len(sheets["Revisao_originais"])),
        ("concordancia_original", states["CONCORDANCIA_ORIGINAL"]),
        ("concordancia_alteracao", states["CONCORDANCIA_ALTERACAO"]),
        ("pendentes_originais", sum(v for k, v in states.items()
                                   if k.startswith("PENDENTE_"))),
        ("novas_candidatas_distintas", len(sheets["Revisao_novas"])),
        ("novas_coincidentes", sum(r["presente_11"] and r["presente_17"]
                                  for r in sheets["Revisao_novas"])),
        ("acordaos_aguardando_tiago", sum(not r["avaliacao_completa"]
                                         for r in sheets["Por_acordao"])),
    ]
    sheets["Resumo"] = [{"metrica": key, "quantidade": value} for key, value in totals]
    instructions = [
        ("Imutabilidade", "Original nunca modificado; proposta concordante é outro campo."),
        ("Identidade", "Anotações originais por (idacordao, region_id)."),
        ("Concordancia", "label/start/end iguais entre projetos; checkbox ignorado."),
        ("Concordancia_alteracao", "Proposta igual entre revisores, diferente do original."),
        ("Novas", "ID ausente no original; agrupar geometria, manter pendente."),
        ("Tiago", "completed_by=10 updated_by=3 com choices indica substituição."),
        ("Checkbox", "Preservado para inspeção, não altera status estrutural."),
        ("Seguranca", "Não publicar JSONs, CSVs ou textos judiciais no GitHub público."),
        *[(f"SHA256_{key}", value) for key, value in hashes.items()],
    ]
    sheets["Instrucoes"] = [{"regra": k, "descricao": v} for k, v in instructions]
    return sheets, hashes


def write(sheets, hashes, output, xlsx=False):
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=True)
    for name in SHEETS:
        records = sheets[name]
        columns = list(records[0]) if records else ["vazio"]
        with (dest / (name + ".csv")).open("w", newline="", encoding="utf-8-sig") as fp:
            writer = csv.DictWriter(fp, fieldnames=columns)
            writer.writeheader()
            writer.writerows(records)
    summary = {
        "sha256_inputs": hashes,
        "counts": {row["metrica"]: row["quantidade"] for row in sheets["Resumo"]},
        "sheets": {key: len(value) for key, value in sheets.items()},
        "policy": "immutable original; geometry-only; checkbox diagnostic; new not gold",
    }
    (dest / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if xlsx:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font
        except ImportError as exc:
            raise RuntimeError('Install optional dependency: pip install -e ".[xlsx]"') from exc
        wb = Workbook()
        for i, name in enumerate(SHEETS):
            sh = wb.active if i == 0 else wb.create_sheet()
            sh.title = name
            data = sheets[name]
            columns = list(data[0]) if data else ["vazio"]
            sh.append(columns)
            for row in data:
                sh.append([row.get(k) for k in columns])
            sh.freeze_panes = "A2"
            sh.auto_filter.ref = sh.dimensions
            for cell in sh[1]:
                cell.font = Font(bold=True)
        wb.save(dest / "fase2_auditoria_geometria.xlsx")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True)
    parser.add_argument("--evaluation-11", required=True)
    parser.add_argument("--evaluation-17", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--xlsx", action="store_true")
    args = parser.parse_args()
    sheets, hashes = audit(args.original, args.evaluation_11, args.evaluation_17)
    print(json.dumps(write(sheets, hashes, args.output, args.xlsx),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
