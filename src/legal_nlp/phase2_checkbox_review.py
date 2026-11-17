"""Prepare individual checkbox consistency review sheets for phase 2.

Usage:
    python -m legal_nlp.phase2_checkbox_review \
      --original data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json \
      --evaluation-11 data/raw/phase_2/project-11-at-2026-11-16-19-26-8e88e5ca.json \
      --evaluation-17 data/raw/phase_2/project-17-at-2026-11-16-19-26-e84e7244.json \
      --output-dir data/interim/phase_2/revisao_checkbox_2026-11-16

Source data are immutable; no manual adjudication is performed.
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from collections import defaultdict
from pathlib import Path

from .phase2_audit_v2 import annotation, extract, identity, load

FIELDS = (
    "idacordao",
    "label original",
    "trecho anotado originalmente",
    "decisão checkbox",
    "label avaliado",
    "idregiao",
    "trecho anotado",
    "problema de divergencia",
)


def divergence_problem(original, evaluated, checkbox):
    """Describe a reviewer's internal inconsistency, without adjudicating it."""
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


def review_rows(original, evaluation_11, evaluation_17):
    """Identify individual checkbox inconsistencies regardless of cross-review outcome.

    Routing uses the initial task owner. A completed_by=10/updated_by=3
    replacement is assigned to Teresa's worksheet and provenance stays in Control.
    """
    from hashlib import sha256

    paths = {
        "original": Path(original),
        "11": Path(evaluation_11),
        "17": Path(evaluation_17),
    }
    sources = {key: load(path) for key, path in paths.items()}
    originals = sources["original"]
    if not originals or any(
        set(sources[project]) != set(originals) for project in ("11", "17")
    ):
        raise ValueError("Document sets differ")

    grouped = defaultdict(list)
    control = []
    for doc in sorted(originals, key=int):
        original_spans, _, _ = extract(originals[doc])
        for project in ("11", "17"):
            task = sources[project][doc]
            spans, choices, _ = extract(task)
            effective_id, _, complete = identity(task)
            if not complete:
                continue
            owner_id = str(annotation(task).get("completed_by", ""))
            substituted = owner_id == "10" and effective_id == "3"
            group_id = owner_id if substituted else effective_id
            for rid, region in spans.items():
                if rid not in original_spans:
                    continue
                checkbox = choices.get(rid)
                if not checkbox:
                    continue
                problem = divergence_problem(original_spans[rid], region, checkbox)
                if problem is None:
                    continue
                grouped[group_id].append({
                    "idacordao": int(doc),
                    "label original": original_spans[rid]["label"],
                    "trecho anotado originalmente": original_spans[rid]["text"],
                    "decisão checkbox": checkbox,
                    "label avaliado": region["label"],
                    "idregiao": rid,
                    "trecho anotado": region["text"],
                    "problema de divergencia": problem,
                    "_start": region["start"],
                    "_region_id": rid,
                    "_project": project,
                })
                control.append({
                    "idacordao": int(doc),
                    "region_id": rid,
                    "projeto_avaliacao": int(project),
                    "grupo_planilha": reviewer_name(group_id),
                    "avaliador_original_id": owner_id,
                    "avaliador_efetivo_id": effective_id,
                    "substituicao_por_tiago": substituted,
                    "decisão checkbox": checkbox,
                    "problema de divergencia": problem,
                    "label_original": original_spans[rid]["label"],
                    "label_avaliado": region["label"],
                    "start_original": original_spans[rid]["start"],
                    "end_original": original_spans[rid]["end"],
                    "start_avaliado": region["start"],
                    "end_avaliado": region["end"],
                })

    for records in grouped.values():
        records.sort(key=lambda row: (
            row["idacordao"], row["_start"], row["_region_id"], row["_project"]
        ))
    control.sort(key=lambda row: (
        row["idacordao"], row["region_id"], row["projeto_avaliacao"]
    ))
    if sum(map(len, grouped.values())) != len(control):
        raise AssertionError("Individual checkbox review count does not reconcile")
    metrics = {
        "inconsistencias_individuais": len(control),
        "avaliadores_ou_grupos": len(grouped),
        "substituicoes_por_tiago": sum(
            row["substituicao_por_tiago"] for row in control
        ),
    }
    hashes = {name: sha256(path.read_bytes()).hexdigest()
              for name, path in paths.items()}
    return dict(grouped), control, metrics, hashes


def reviewer_name(reviewer_id):
    from .phase2_audit_v2 import NAMES
    return NAMES.get(str(reviewer_id), "ID " + str(reviewer_id))


def safe_filename(name):
    normalized = unicodedata.normalize("NFKD", name)
    stem = "".join(c for c in normalized if not unicodedata.combining(c))
    return "".join(c.lower() if c.isalnum() else "_" for c in stem).strip("_")


def write_workbooks(grouped, control, output_dir):
    """Create ONE workbook: internal control and one eight-column tab per reviewer."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    header_fill = PatternFill("solid", fgColor="17365D")
    header_font = Font(bold=True, color="FFFFFF")
    widths = (18, 31, 95, 27, 31, 23, 95, 48)

    def populate(book, title, columns, rows):
        sheet = book.create_sheet(title)
        sheet.append(list(columns))
        for row in rows:
            values = []
            for key in columns:
                value = row.get(key, "")
                if isinstance(value, str):
                    value = ILLEGAL_CHARACTERS_RE.sub("", value)
                    if value.startswith(("=", "+", "-", "@")):
                        value = "'" + value
                values.append(value)
            sheet.append(values)
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        sheet.row_dimensions[1].height = 32
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for col_idx in range(1, len(columns) + 1):
            width = widths[col_idx - 1] if columns == FIELDS else 26
            sheet.column_dimensions[get_column_letter(col_idx)].width = width
        return sheet

    workbook = Workbook()
    workbook.remove(workbook.active)
    control_headers = (
        "idacordao", "region_id", "projeto_avaliacao", "grupo_planilha",
        "avaliador_original_id", "avaliador_efetivo_id", "substituicao_por_tiago",
        "decisão checkbox", "problema de divergencia", "label_original",
        "label_avaliado", "start_original", "end_original",
        "start_avaliado", "end_avaliado",
    )
    populate(workbook, "Controle", control_headers, control)
    for reviewer_id in sorted(grouped, key=lambda n: (reviewer_name(n).casefold(), n)):
        name = reviewer_name(reviewer_id)
        public_rows = [{key: row[key] for key in FIELDS} for row in grouped[reviewer_id]]
        populate(workbook, name[:31], FIELDS, public_rows)

    output_path = out / "revisao_checkbox_por_avaliador.xlsx"
    workbook.save(output_path)
    return output_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True)
    parser.add_argument("--evaluation-11", required=True)
    parser.add_argument("--evaluation-17", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    grouped, control, metrics, hashes = review_rows(
        args.original, args.evaluation_11, args.evaluation_17
    )
    workbook_path = write_workbooks(grouped, control, args.output_dir)
    print(json.dumps({
        "inconsistencias_individuais": len(control),
        "tarefas": sum(map(len, grouped.values())),
        "por_avaliador": {
            reviewer_name(key): len(value) for key, value in grouped.items()
        },
        "planilha_unica": str(workbook_path),
        "sha256": hashes,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
