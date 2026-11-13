"""Phase-2 deterministic audit, with immutable originals and checkbox conflicts isolated.

Outputs a single XLSX with nine tabs. Only synthetic tests and source belong in Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

SHEETS = ("Resumo", "Motivos_pendencia", "Revisao_originais", "Revisao_novas",
          "Consolidados", "Divergencia_checkbox", "Duplicatas_exatas",
          "Por_acordao", "Instrucoes")
NAMES = {"3": "Tiago", "4": "Mariana", "5": "Guilherme", "7": "Letícia",
         "8": "Emily", "9": "Giulia", "10": "Teresa", "12": "Maria"}


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


def geometry(r):
    return (r["label"], r["start"], r["end"]) if r else None


def identity(task):
    ann = annotation(task)
    completed, updated = str(ann.get("completed_by", "")), str(task.get("updated_by", ""))
    if (completed == "10" and updated == "3"
            and any(x.get("type") == "choices" for x in ann.get("result", []))):
        return "3", "substituição", True
    if completed == "10":
        return "10", "Teresa", False
    return completed, NAMES.get(completed, "ID " + completed), True


def decision(original, evaluated, explicit):
    if evaluated is None:
        return "nao_avaliada"
    if original is None:
        return "nova_regiao"
    if explicit:
        return {"certo": "correto", "incorreto": "incorreto",
                "limite impreciso": "limite_impreciso"}.get(
                    explicit.strip().casefold(), "julgamento_desconhecido")
    if original["label"] != evaluated["label"]:
        return "incorreto_automatico"
    if geometry(original) != geometry(evaluated):
        return "limite_impreciso_automatico"
    return "correto_automatico"


def audit(original, evaluation_11, evaluation_17):
    paths = {"original": Path(original), "11": Path(evaluation_11),
             "17": Path(evaluation_17)}
    sources = {key: load(path) for key, path in paths.items()}
    originals = sources["original"]
    if not originals or any(set(sources[p]) != set(originals) for p in ("11", "17")):
        raise ValueError("Document sets differ")
    sheets = {name: [] for name in SHEETS}
    counts, reasons = Counter(), Counter()
    for doc in sorted(originals, key=int):
        base_task = originals[doc]
        base, _, _ = extract(base_task)
        oid = str(annotation(base_task)["completed_by"])
        oname = NAMES.get(oid, "ID " + oid)
        review = {p: extract(sources[p][doc]) for p in ("11", "17")}
        people = {p: identity(sources[p][doc]) for p in ("11", "17")}
        complete = all(people[p][2] for p in ("11", "17"))
        perdoc = Counter()
        original_geometries = defaultdict(list)
        for rid, region in base.items():
            original_geometries[geometry(region)].append(rid)
        for geom, ids in sorted(original_geometries.items()):
            if len(ids) > 1:
                sheets["Duplicatas_exatas"].append({
                    "idacordao": doc, "label": geom[0], "start": geom[1],
                    "end": geom[2], "region_ids": ";".join(sorted(ids)),
                    "quantidade": len(ids)})
        for rid, old in sorted(base.items(), key=lambda x: (x[1]["start"], x[0])):
            r = {p: review[p][0].get(rid) for p in ("11", "17")}
            d = {p: decision(old, r[p], review[p][1].get(rid)) for p in ("11", "17")}
            same = (r["11"] is not None and r["17"] is not None
                    and geometry(r["11"]) == geometry(r["17"]))
            conflict = same and d["11"].removesuffix("_automatico") != d["17"].removesuffix("_automatico")
            if not complete:
                status, reason = "PENDENTE_SUBSTITUICAO", "aguardando_substituicao"
            elif not same:
                status, reason = "PENDENTE_GEOMETRIA", "ausencia_ou_divergencia_geometria"
            elif conflict:
                status, reason = "DIVERGENCIA_CHECKBOX", "checkbox_divergente_geometria_igual"
            elif geometry(old) == geometry(r["11"]):
                status, reason = "CONCORDANCIA_ORIGINAL", ""
            else:
                status, reason = "CONCORDANCIA_ALTERACAO", ""
            counts[status] += 1
            perdoc[status] += 1
            if reason:
                reasons[reason] += 1
            row = {
                "idacordao": doc, "region_id_original": rid,
                "anotador_original_id": oid, "anotador_original_nome": oname,
                "label_original": old["label"], "start_original": old["start"],
                "end_original": old["end"], "texto_original": old["text"],
                "tipo": "NER" if old["label"].startswith("ENT_") else
                        "SEG" if old["label"].startswith("SEG_") else "UNKNOWN"}
            for p in ("11", "17"):
                prefix, region = "projeto_" + p + "_", r[p]
                row.update({
                    prefix + "avaliador_id": people[p][0],
                    prefix + "avaliador_nome": people[p][1],
                    prefix + "task_id": sources[p][doc]["id"],
                    prefix + "region_id": rid if region else "",
                    prefix + "label": region["label"] if region else "",
                    prefix + "start": region["start"] if region else "",
                    prefix + "end": region["end"] if region else "",
                    prefix + "decisao": d[p],
                    prefix + "observacao": review[p][2].get(rid) or ""})
            row.update({"status": status, "motivo": reason})
            sheets["Revisao_originais"].append(row)
            if status.startswith("CONCORDANCIA_"):
                sheets["Consolidados"].append({
                    **row, "label_proposta_concordante": r["11"]["label"],
                    "start_proposta_concordante": r["11"]["start"],
                    "end_proposta_concordante": r["11"]["end"]})
            elif status == "DIVERGENCIA_CHECKBOX":
                sheets["Divergencia_checkbox"].append(row.copy())
        # Canonical ID is derived from (document, label, start, end) and never
        # replaces either reviewer source ID.
        new_groups = {}
        for p in ("11", "17"):
            groups = defaultdict(list)
            for rid, span in review[p][0].items():
                if rid not in base:
                    groups[geometry(span)].append(rid)
            new_groups[p] = groups
        consolidated_new = set()
        for geom in sorted(set(new_groups["11"]) & set(new_groups["17"])):
            ids11, ids17 = sorted(new_groups["11"][geom]), sorted(new_groups["17"][geom])
            if (not complete or len(ids11) != 1 or len(ids17) != 1
                    or original_geometries.get(geom)
                    or people["11"][0] == people["17"][0]):
                continue
            canonical = "new_" + hashlib.sha256(json.dumps(
                [doc, *geom], ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")).hexdigest()[:20]
            row = {
                "idacordao": doc, "region_id_original": "",
                "anotador_original_id": oid, "anotador_original_nome": oname,
                "label_original": "", "start_original": "", "end_original": "",
                "texto_original": "", "tipo": (
                    "NER" if geom[0].startswith("ENT_") else
                    "SEG" if geom[0].startswith("SEG_") else "UNKNOWN"),
            }
            for p, rid in (("11", ids11[0]), ("17", ids17[0])):
                prefix, span = "projeto_" + p + "_", review[p][0][rid]
                row.update({
                    prefix + "avaliador_id": people[p][0],
                    prefix + "avaliador_nome": people[p][1],
                    prefix + "task_id": sources[p][doc]["id"],
                    prefix + "region_id": rid,
                    prefix + "label": span["label"],
                    prefix + "start": span["start"],
                    prefix + "end": span["end"],
                    prefix + "decisao": "nova_regiao",
                    prefix + "observacao": review[p][2].get(rid) or "",
                })
            row.update({
                "status": "CONSOLIDADA_NOVA", "motivo": "",
                "canonical_region_id": canonical,
                "region_id_original_projeto_11": ids11[0],
                "region_id_original_projeto_17": ids17[0],
                "label_proposta_concordante": geom[0],
                "start_proposta_concordante": geom[1],
                "end_proposta_concordante": geom[2],
            })
            sheets["Consolidados"].append(row)
            consolidated_new.add(geom)
            counts["CONSOLIDADA_NOVA"] += 1
            perdoc["CONSOLIDADA_NOVA"] += 1
        # Each new region is an independent manual proposal by ONE reviewer.
        # Equal geometry across projects is diagnostic and never merges IDs.
        for p in ("11", "17"):
            for rid, span in sorted(review[p][0].items(),
                                    key=lambda item: (item[1]["start"], item[0])):
                if rid in base:
                    continue
                geom = geometry(span)
                other_p = "17" if p == "11" else "11"
                same_in_other = sorted(
                    other_id for other_id, other_span in review[other_p][0].items()
                    if other_id not in base and geometry(other_span) == geom)
                if geom in consolidated_new:
                    status, reason = "CONSOLIDADA_NOVA", ""
                elif not complete:
                    status, reason = "PENDENTE_NOVA", "nova_aguardando_substituicao"
                elif same_in_other and (
                        len(new_groups[p][geom]) != 1 or
                        len(new_groups[other_p][geom]) != 1):
                    status, reason = "PENDENTE_NOVA", "nova_ambigua_ids_duplicados"
                elif same_in_other and original_geometries.get(geom):
                    status, reason = "PENDENTE_NOVA", "nova_duplicada_do_original"
                elif same_in_other and people[p][0] == people[other_p][0]:
                    status, reason = "PENDENTE_NOVA", "nova_sem_avaliadores_distintos"
                elif same_in_other:
                    status, reason = "PENDENTE_NOVA", "nova_coincidente_pendente"
                else:
                    status, reason = "PENDENTE_NOVA", "nova_unilateral_pendente"
                if reason:
                    reasons[reason] += 1
                    perdoc["NOVAS_PENDENTES"] += 1
                canonical = ("new_" + hashlib.sha256(json.dumps(
                    [doc, *geom], ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")).hexdigest()[:20]) if geom in consolidated_new else ""
                sheets["Revisao_novas"].append({
                    "idacordao": doc,
                    "anotador_original_id": oid,
                    "anotador_original_nome": oname,
                    "projeto_avaliacao": int(p),
                    "avaliador_id": people[p][0],
                    "avaliador_nome": people[p][1],
                    "task_id_avaliacao": sources[p][doc]["id"],
                    "region_id_nova": rid,
                    "tipo": ("NER" if geom[0].startswith("ENT_") else
                             "SEG" if geom[0].startswith("SEG_") else "UNKNOWN"),
                    "label": span["label"],
                    "start": span["start"],
                    "end": span["end"],
                    "texto": span["text"],
                    "decisao": "nova_regiao",
                    "observacao": review[p][2].get(rid) or "",
                    "mesma_geometria_outro_projeto_ids": ";".join(same_in_other),
                    "mesma_geometria_original_ids":
                        ";".join(sorted(original_geometries.get(geom, []))),
                    "status": "PENDENTE_NOVA",
                    "motivo": reason,
                    "adjudicada": False,
                })
        sheets["Por_acordao"].append({
            "idacordao": doc, "originais": len(base),
            "concordancia_original": perdoc["CONCORDANCIA_ORIGINAL"],
            "concordancia_alteracao": perdoc["CONCORDANCIA_ALTERACAO"],
            "divergencia_checkbox": perdoc["DIVERGENCIA_CHECKBOX"],
            "pendentes_originais": len(base) - perdoc["CONCORDANCIA_ORIGINAL"]
                                  - perdoc["CONCORDANCIA_ALTERACAO"],
            "novas_consolidadas": perdoc["CONSOLIDADA_NOVA"],
            "novas_pendentes": perdoc["NOVAS_PENDENTES"],
            "avaliacao_completa": complete})
    metrics = {
        "acordaos": len(originals),
        "originais": len(sheets["Revisao_originais"]),
        "concordancia_original": counts["CONCORDANCIA_ORIGINAL"],
        "concordancia_alteracao": counts["CONCORDANCIA_ALTERACAO"],
        "consolidados_estruturais_sem_conflito_checkbox": counts["CONCORDANCIA_ORIGINAL"] + counts["CONCORDANCIA_ALTERACAO"],
        "isolados_checkbox_divergente": len(sheets["Divergencia_checkbox"]),
        "originais_pendentes": len(sheets["Revisao_originais"]) -
                              counts["CONCORDANCIA_ORIGINAL"] - counts["CONCORDANCIA_ALTERACAO"],
        "novas_candidatas": len(sheets["Revisao_novas"]),
        "novas_consolidadas": counts["CONSOLIDADA_NOVA"],
        "consolidados_totais": len(sheets["Consolidados"]),
        "novas_pendentes": sum(r["status"] == "PENDENTE_NOVA" for r in sheets["Revisao_novas"]),
        "novas_coincidentes": sum(
            bool(r["mesma_geometria_outro_projeto_ids"])
            for r in sheets["Revisao_novas"]),
        "pendencias_totais": len(sheets["Revisao_originais"]) -
                             counts["CONCORDANCIA_ORIGINAL"] -
                             counts["CONCORDANCIA_ALTERACAO"] +
                             sum(r["status"] == "PENDENTE_NOVA" for r in sheets["Revisao_novas"]),
        "acordaos_aguardando_substituicao": sum(
            not r["avaliacao_completa"] for r in sheets["Por_acordao"])}
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest()
              for key, path in paths.items()}
    sheets["Resumo"] = [{"metrica": key, "quantidade": value}
                        for key, value in metrics.items()]
    sheets["Motivos_pendencia"] = [
        {"motivo": key, "quantidade": value} for key, value in sorted(reasons.items())]
    notes = [
        ("Original", "Imutável; nunca substituir label/start/end originais."),
        ("Ordem", "Original, depois todas as colunas do projeto 11 e do projeto 17."),
        ("Consolidados", "Geometria igual; decisões normalizadas não conflitantes."),
        ("Divergencia_checkbox", "Geometria igual, julgamento discordante; excluído de consolidados."),
        ("Checkbox ausente", "Classificação determinística contra o original; a coluna decisao já registra o valor explícito ou automático."),
        ("Novas", "Uma linha por proposta e avaliador; o ID canônico vincula os dois IDs de origem."),
        ("Consolidacao_novas", "Exige 1 proposta por projeto, avaliadores distintos, substituição concluída e ausência de geometria idêntica no original."),
        ("Substituição", "completed_by=10 e updated_by=3 com choices: nome substituição."),
        ("Teresa", "Ainda não substituída: nenhuma aprovação inferida."),
        ("Interpretação", "Concordância estrutural, não Cohen Kappa nem gold."),
        *[(f"SHA256_{key}", value) for key, value in hashes.items()]]
    sheets["Instrucoes"] = [{"campo_regra": k, "descricao": v} for k, v in notes]
    return sheets, metrics, hashes


def columns(name, rows):
    if not rows:
        return ["sem_dados"]
    all_keys = list(rows[0])
    if name not in {"Revisao_originais", "Consolidados",
                    "Divergencia_checkbox"}:
        return all_keys
    p11 = [x for x in all_keys if x.startswith("projeto_11_")]
    p17 = [x for x in all_keys if x.startswith("projeto_17_")]
    tail = {"status", "motivo", "adjudicada", "mesma_geometria_original_ids",
            "label_proposta_concordante", "start_proposta_concordante",
            "end_proposta_concordante", "canonical_region_id",
            "region_id_original_projeto_11", "region_id_original_projeto_17"}
    initial = [x for x in all_keys if not x.startswith("projeto_") and x not in tail]
    return initial + p11 + p17 + [x for x in all_keys if x not in initial + p11 + p17]


def write(sheets, output):
    """Write a single workbook with the nine audit worksheets."""
    from artifact_tool import Workbook, SpreadsheetFile

    workbook = Workbook.create()
    for name in SHEETS:
        sh = workbook.worksheets.add(name)
        rows, keys = sheets[name], columns(name, sheets[name])
        sh.get_range_by_indexes(0, 0, 1, len(keys)).values = [keys]
        for offset in range(0, len(rows), 120):
            chunk = rows[offset:offset + 120]
            matrix = [[row.get(key, "") if row.get(key) is not None else ""
                       for key in keys] for row in chunk]
            sh.get_range_by_indexes(offset + 1, 0, len(chunk), len(keys)).values = matrix
        sh.get_range_by_indexes(0, 0, 1, len(keys)).format = {
            "fill": "#17365D",
            "font": {"bold": True, "color": "#FFFFFF"},
            "row_height": 32, "wrap_text": True}
        sh.freeze_panes.freeze_rows(1)
        for index, key in enumerate(keys):
            width = (38 if any(z in key for z in ("observacao", "texto", "descricao"))
                     else 24 if "nome" in key or "decisao" in key else 19)
            sh.get_range_by_indexes(0, index, 1, 1).format.column_width = width
    SpreadsheetFile.export_xlsx(workbook).save(str(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True)
    parser.add_argument("--evaluation-11", required=True)
    parser.add_argument("--evaluation-17", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    sheets, metrics, hashes = audit(
        args.original, args.evaluation_11, args.evaluation_17)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    write(sheets, path)
    print(json.dumps({"counts": metrics, "sha256": hashes},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
