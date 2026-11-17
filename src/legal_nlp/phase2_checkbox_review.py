"""Prepare independent checkbox-disagreement review sheets for phase 2.

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
from collections import Counter, defaultdict
from pathlib import Path

from .phase2_audit_v2 import audit, annotation, extract, identity, load

FIELDS = (
    "idacordao",
    "decisão checkbox",
    "label avaliado",
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
    if normalized == "certo" and (
        original["label"], original["start"], original["end"]
    ) != (evaluated["label"], evaluated["start"], evaluated["end"]):
        return "checkbox certo com anotação diferente do original"
    return "checkbox divergente entre avaliadores"


def review_rows(original, evaluation_11, evaluation_17):
    """Return independent rows, one per evaluator and conflicted original region."""
    sheets, metrics, hashes = audit(original, evaluation_11, evaluation_17)
    sources = {
        "original": load(original),
        "11": load(evaluation_11),
        "17": load(evaluation_17),
    }
    grouped = defaultdict(list)
    control = []

    for item in sheets["Divergencia_checkbox"]:
        doc, rid = str(item["idacordao"]), str(item["region_id_original"])
        original_spans, _, _ = extract(sources["original"][doc])
        original_region = original_spans[rid]
        reviewers = {}
        for project in ("11", "17"):
            spans, choices, _ = extract(sources[project][doc])
            reviewer_id, _, complete = identity(sources[project][doc])
            if not complete:
                raise ValueError(f"Unresolved reviewer replacement on document {doc}")
            if rid not in spans:
                raise ValueError(f"Missing evaluated region {doc}/{project}/{rid}")
            region = spans[rid]
            normalized = item[f"projeto_{project}_decisao"]
            checkbox = choices.get(rid)
            decision_label = checkbox if checkbox else normalized + " (automático)"
            problem = divergence_problem(original_region, region, checkbox)
            reviewers[project] = {
                "reviewer_id": reviewer_id,
                "region": region,
                "checkbox": decision_label,
                "problem": problem,
            }
            grouped[reviewer_id].append({
                "idacordao": int(doc),
                "decisão checkbox": decision_label,
                "label avaliado": region["label"],
                "trecho anotado": region["text"],
                "problema de divergencia": problem,
                "_start": region["start"],
                "_region_id": rid,
                "_project": project,
            })
        control.append({
            "idacordao": int(doc),
            "region_id": rid,
            "avaliador_11_id": reviewers["11"]["reviewer_id"],
            "checkbox_11": reviewers["11"]["checkbox"],
            "problema_11": reviewers["11"]["problem"],
            "avaliador_17_id": reviewers["17"]["reviewer_id"],
            "checkbox_17": reviewers["17"]["checkbox"],
            "problema_17": reviewers["17"]["problem"],
        })

    for records in grouped.values():
        records.sort(key=lambda row: (
            row["idacordao"], row["_start"], row["_region_id"], row["_project"]
        ))
    control.sort(key=lambda row: (row["idacordao"], row["region_id"]))
    if sum(map(len, grouped.values())) != 2 * len(control):
        raise AssertionError("Each checkbox disagreement must reach two reviewers")
    if len(control) != metrics["isolados_checkbox_divergente"]:
        raise AssertionError("Checkbox discrepancy count did not reconcile")
    return dict(grouped), control, metrics, hashes


def reviewer_name(reviewer_id):
    from .phase2_audit_v2 import NAMES
    return NAMES.get(str(reviewer_id), "ID " + str(reviewer_id))


def safe_filename(name):
    normalized = unicodedata.normalize("NFKD", name)
    stem = "".join(c for c in normalized if not unicodedata.combining(c))
    return "".join(c.lower() if c.isalnum() else "_" for c in stem).strip("_")


def write_workbooks(grouped, control, output_dir):
    """Export exactly the five requested columns per reviewer, no counterpart decision."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from zipfile import ZipFile, ZIP_DEFLATED

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    header_fill = PatternFill("solid", fgColor="17365D")
    header_font = Font(bold=True, color="FFFFFF")
    widths = (18, 27, 31, 95, 48)

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

    control_book = Workbook()
    control_book.remove(control_book.active)
    control_headers = (
        "idacordao", "region_id", "avaliador_11_id", "checkbox_11", "problema_11",
        "avaliador_17_id", "checkbox_17", "problema_17",
    )
    populate(control_book, "Controle", control_headers, control)
    created = []
    for reviewer_id in sorted(grouped, key=lambda n: (reviewer_name(n).casefold(), n)):
        name = reviewer_name(reviewer_id)
        rows = grouped[reviewer_id]
        public_rows = [{key: row[key] for key in FIELDS} for row in rows]
        populate(control_book, name[:31], FIELDS, public_rows)
        personal = Workbook()
        personal.remove(personal.active)
        populate(personal, "Revisao_checkbox", FIELDS, public_rows)
        path = out / f"revisao_checkbox_{safe_filename(name)}.xlsx"
        personal.save(path)
        created.append(path)

    control_path = out / "controle_checkbox.xlsx"
    control_book.save(control_path)
    zip_path = out / "planilhas_individuais.zip"
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for path in created:
            archive.write(path, arcname=path.name)
    return control_path, zip_path


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
    control_path, zip_path = write_workbooks(grouped, control, args.output_dir)
    print(json.dumps({
        "divergencias": len(control),
        "tarefas": sum(map(len, grouped.values())),
        "por_avaliador": {
            reviewer_name(key): len(value) for key, value in grouped.items()
        },
        "controle": str(control_path),
        "individuais_zip": str(zip_path),
        "sha256": hashes,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
