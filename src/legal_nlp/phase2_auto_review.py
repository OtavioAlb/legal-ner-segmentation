"""Fase 2: excluir um avaliador e classificar escolhas ausentes por comparação estrutural.

As escolhas humanas são imutáveis. Comparações automáticas descrevem APENAS a
igualdade/mudança relativa à anotação original; NÃO atestam correção semântica.
Requer --original, exceto quando se autoriza explicitamente um snapshot embutido
que tenha sido previamente verificado contra o original.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

CHOICES = {
    "correto_automatico", "incorreto_automatico", "limite_impreciso_automatico"
}
FIELD_NAMES = ["idacordao", "projeto", "avaliador_id", "task_id", "region_id", "status",
               "rotulo_original", "rotulo_avaliado", "inicio_original", "fim_original",
               "inicio_avaliado", "fim_avaliado", "label_alterado", "offset_alterado", "proveniencia"]
ISSUE_FIELDS = ["idacordao", "projeto", "avaliador_id", "task_id", "region_id", "motivo"]


def load(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, list) or any(not isinstance(d, dict) for d in value):
        raise ValueError(f"Esperada lista de objetos JSON: {path}")
    return value


def docid(task):
    data = task.get("data")
    val = data.get("idacordao") if isinstance(data, dict) else None
    if isinstance(val, bool) or not isinstance(val, (str, int)) or not str(val).strip():
        raise ValueError("idacordao inválido")
    return str(val).strip()


def only_annotation(task):
    anns = task.get("annotations")
    if not isinstance(anns, list) or len(anns) != 1 or not isinstance(anns[0], dict):
        raise ValueError(f"Esperada 1 anotação: {docid(task)}")
    if anns[0].get("was_cancelled"):
        raise ValueError(f"Anotação cancelada: {docid(task)}")
    return anns[0]


def labels_index(items):
    index = {}
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "labels":
            continue
        rid = item.get("id")
        if not isinstance(rid, str) or not rid or rid in index:
            raise ValueError(f"ID de região inválido/duplicado: {rid!r}")
        val = item.get("value", {})
        lab = val.get("labels")
        start, end = val.get("start"), val.get("end")
        if not isinstance(lab, list) or not lab or any(not isinstance(x, str) for x in lab):
            raise ValueError(f"Label inválido: {rid}")
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in [start, end]) or start < 0 or start >= end:
            raise ValueError(f"Offset inválido: {rid}")
        index[rid] = item
    return index


def existing_choice_index(items):
    out = defaultdict(list)
    for item in items:
        if isinstance(item, dict) and item.get("type") == "choices":
            out[item.get("id")].append(item)
    return out


def identity(value):
    v = value["value"]
    return (tuple(v["labels"]), v["start"], v["end"])


def key_for_comparison(x):
    v = x.get("value", {})
    return v.get("labels"), v.get("start"), v.get("end"), v.get("text")


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def process(originals, projects, *, excluded_user_id, require_original=True):
    if require_original and originals is None:
        raise ValueError("É necessário o arquivo original de anotações")
    orig_lookup = {}
    if originals is not None:
        for task in originals:
            k = docid(task)
            if k in orig_lookup:
                raise ValueError(f"Acórdão original duplicado: {k}")
            orig_lookup[k] = task
    seen = set()
    filtered = []
    automatic = []
    issues = []
    removed = []
    counts = Counter()
    docs = set()
    for expected_project, tasks in projects.items():
        for src in tasks:
            doc = docid(src)
            project = str(src.get("project"))
            if project != str(expected_project):
                raise ValueError(f"Projeto inesperado: {doc}/{project}")
            if (doc, project) in seen:
                raise ValueError(f"Par doc/projeto duplicado: {doc}/{project}")
            seen.add((doc, project))
            src_annotation = only_annotation(src)
            uid = src_annotation.get("completed_by")
            if isinstance(uid, bool) or not isinstance(uid, int):
                raise ValueError(f"Avaliador inválido: {doc}/{project}")
            if uid == excluded_user_id:
                removed.append({"idacordao": doc, "projeto": project, "avaliador_id": uid, "task_id": src.get("id")})
                counts["avaliacoes_excluidas"] += 1
                continue
            task = copy.deepcopy(src)
            ann = only_annotation(task)
            label_map = labels_index(ann.get("result") or [])
            choice_map = existing_choice_index(ann.get("result") or [])
            if originals is not None:
                if doc not in orig_lookup:
                    raise ValueError(f"Original inexistente: {doc}")
                orig_task = orig_lookup[doc]
                if task.get("data", {}).get("acordao") != orig_task.get("data", {}).get("acordao"):
                    raise ValueError(f"Texto do acórdão divergente: {doc}")
                reference = labels_index(only_annotation(orig_task).get("result") or [])
                embedded = labels_index((ann.get("prediction") or {}).get("result") or [])
                if set(reference) != set(embedded) or any(key_for_comparison(reference[r]) != key_for_comparison(embedded[r]) for r in reference):
                    raise ValueError(f"Snapshot do original divergente: {doc}")
            else:
                reference = labels_index((ann.get("prediction") or {}).get("result") or [])
                if not reference:
                    raise ValueError(f"Snapshot sem regiões: {doc}/{project}")
            counts["avaliacoes_incluidas"] += 1
            docs.add(doc)
            metadata = []
            for rid, orig in reference.items():
                if rid not in label_map:
                    issues.append({"idacordao": doc, "projeto": project, "avaliador_id": uid,
                                   "task_id": task.get("id"), "region_id": rid,
                                   "motivo": "regiao_original_ausente_na_avaliacao"})
                    counts["originais_ausentes_na_avaliacao"] += 1
                    continue
                ch = choice_map.get(rid, [])
                if ch:
                    if len(ch) != 1 or not isinstance(ch[0].get("value", {}).get("choices"), list) or len(ch[0]["value"]["choices"]) != 1:
                        raise ValueError(f"Checkbox ambíguo: {doc}/{project}/{rid}")
                    counts["julgamentos_humanos_preservados"] += 1
                    continue
                evaluated = label_map[rid]
                old, new = identity(orig), identity(evaluated)
                label_changed = old[0] != new[0]
                offset_changed = old[1:] != new[1:]
                if label_changed:
                    status = "incorreto_automatico"
                elif offset_changed:
                    status = "limite_impreciso_automatico"
                else:
                    status = "correto_automatico"
                val = evaluated["value"]
                automatic_result = {
                    "id": rid, "type": "choices",
                    "value": {"start": val["start"], "end": val["end"],
                              "choices": [status]},
                    "to_name": evaluated.get("to_name", "text"),
                    "from_name": "confianca_anotacao",
                    "origin": "automatic-comparison"
                }
                if "text" in val:
                    automatic_result["value"]["text"] = val["text"]
                ann["result"].append(automatic_result)
                metadata.append({"region_id": rid, "status": status,
                                 "original": {"labels": list(old[0]), "start": old[1], "end": old[2]},
                                 "reviewed": {"labels": list(new[0]), "start": new[1], "end": new[2]},
                                 "label_changed": label_changed, "offset_changed": offset_changed,
                                 "method": "same_id_original_label_offsets"})
                automatic.append({"idacordao": doc, "projeto": project, "avaliador_id": uid,
                                  "task_id": task.get("id"), "region_id": rid, "status": status,
                                  "rotulo_original": "|".join(old[0]), "rotulo_avaliado": "|".join(new[0]),
                                  "inicio_original": old[1], "fim_original": old[2],
                                  "inicio_avaliado": new[1], "fim_avaliado": new[2],
                                  "label_alterado": label_changed, "offset_alterado": offset_changed,
                                  "proveniencia": "comparacao_deterministica_original"})
                counts[status] += 1
            for rid in label_map.keys() - reference.keys():
                if choice_map.get(rid):
                    counts["novas_regioes_com_julgamento_humano"] += 1
                else:
                    issues.append({"idacordao": doc, "projeto": project, "avaliador_id": uid,
                                   "task_id": task.get("id"), "region_id": rid,
                                   "motivo": "nova_regiao_sem_id_no_original"})
                    counts["novas_regioes_sem_referencia"] += 1
            task["automatic_review_metadata"] = {
                "schema_version": "1.0", "method": "exact_id_label_and_offset_comparison",
                "reference": "original_annotations" if originals is not None else "embedded_original_snapshot_externally_verified",
                "decisions": metadata
            }
            filtered.append(task)
    filtered.sort(key=lambda t: (int(docid(t)), int(t["project"])))
    automatic.sort(key=lambda a: (int(a["idacordao"]), int(a["projeto"]), a["region_id"]))
    issues.sort(key=lambda a: (int(a["idacordao"]), int(a["projeto"]), a["motivo"], a["region_id"]))
    removed.sort(key=lambda a: (int(a["idacordao"]), int(a["projeto"])))
    summary = {
        "schema_version": "1.0", "policy": "Não é uma adjudicação semântica; automático indica igualdade ou mudança vs original.",
        "reviewer_excluded_id": excluded_user_id, "counts": dict(sorted(counts.items())),
        "documents_preserved": len(docs), "review_records_retained": len(filtered),
        "review_records_removed": len(removed), "automatic_statuses": dict(Counter(x["status"] for x in automatic)),
        "unresolved_reasons": dict(Counter(x["motivo"] for x in issues)),
        "original_source": "original_file" if originals is not None else "embedded_prediction_verified_against_original_outside_script",
        "manual_decisions_preserved": counts["julgamentos_humanos_preservados"],
        "no_semantic_gold_generated": True,
    }
    return filtered, automatic, issues, removed, summary


def run(args):
    inputs = [args.project_11, args.project_17] + ([args.original] if args.original else [])
    dest = args.output_dir
    if any(p.resolve() == dest.resolve() or dest.resolve() in p.resolve().parents for p in inputs):
        raise ValueError("Diretório de saída não pode conter os arquivos de entrada")
    if args.original is None and not args.allow_verified_embedded:
        raise ValueError("Informe --original ou, com verificação externa prévia, --allow-verified-embedded")
    projects = {"11": load(args.project_11), "17": load(args.project_17)}
    originals = load(args.original) if args.original else None
    filtered, auto, issues, removed, summary = process(originals, projects, excluded_user_id=args.exclude_user_id,
                                                       require_original=not args.allow_verified_embedded)
    summary["input_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    # Todas as validações acima ocorrem antes de escrever qualquer saída.
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "evaluations_filtered_automatic.json").write_text(json.dumps(filtered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dest / "auto_review_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dest / "removed_reviewer_records.json").write_text(json.dumps(removed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(dest / "automatic_decisions.csv", FIELD_NAMES, auto)
    write_csv(dest / "pending_manual_review.csv", ISSUE_FIELDS, issues)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--original", type=Path)
    p.add_argument("--project-11", type=Path, required=True)
    p.add_argument("--project-17", type=Path, required=True)
    p.add_argument("--exclude-user-id", type=int, default=10)
    p.add_argument("--allow-verified-embedded", action="store_true",
                   help="Usar snapshot original embutido somente se previamente comparado ao arquivo de anotação original")
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()