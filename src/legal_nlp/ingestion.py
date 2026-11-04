"""Lossless Phase 1 importer for judicial decisions and individual annotations.

Records are preserved even when structurally invalid. No majority voting,
deduplication, span trimming, or overlap removal is performed.
"""
from __future__ import annotations

import codecs
import csv
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_csv(payload: bytes, encoding: str = "auto") -> tuple[str, str]:
    """Decode CSV strictly; record the encoding used for reproducibility.

    Automatic detection prefers UTF-8 and then legacy Windows/Latin-1 encodings.
    The fallback is not definitive detection; use an explicit encoding if needed.
    """
    if encoding != "auto":
        return payload.decode(encoding, errors="strict"), encoding

    if payload.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return payload.decode("utf-16", errors="strict"), "utf-16"

    for candidate in ("utf-8-sig", "cp1252", "iso-8859-1"):
        try:
            return payload.decode(candidate, errors="strict"), candidate
        except UnicodeDecodeError:
            continue
    raise UnicodeError("Could not decode the CSV with supported encodings")


def _load_rows(
    path: Path, encoding: str = "auto"
) -> tuple[list[dict[str, Any]], str]:
    if path.suffix.lower() == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("Install with: pip install -e '.[xlsx]'") from exc
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            rows = sheet.iter_rows(values_only=True)
            header = next(rows)
            names = [str(v).strip() if v is not None else "" for v in header]
            return [dict(zip(names, values)) for values in rows], "xlsx"
        finally:
            workbook.close()
    if path.suffix.lower() != ".csv":
        raise ValueError(f"Unsupported input: {path.suffix}")
    content, used_encoding = _decode_csv(path.read_bytes(), encoding)
    with io.StringIO(content, newline="") as stream:
        sample = stream.read(8192)
        stream.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            delim = dialect.delimiter
        except csv.Error:
            delim = ","
        return list(csv.DictReader(stream, delimiter=delim)), used_encoding


def _value(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        result = str(value).strip()
        if result and result.lower() not in {"nan", "none", "null"}:
            return result
    return None


def _raw_span_text(row: dict[str, Any], *keys: str) -> str | None:
    """Read an annotated excerpt without stripping meaningful whitespace."""
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = value if isinstance(value, str) else str(value)
        if text and text.strip().lower() not in {"nan", "none", "null"}:
            return text
    return None


def normalize_document_id(identifier: str | None) -> str | None:
    """Normalize spreadsheet artifacts like '290.0' to '290', preserving other IDs.

    Do not coerce arbitrary identifiers to numbers: leading zeros, identifiers
    with meaningful decimal components, and nonnumeric IDs are preserved.
    """
    if identifier is None:
        return None
    cleaned = identifier.strip()
    match = re.fullmatch(r"([0-9]+)\.0+", cleaned)
    return match.group(1) if match else cleaned


def _offset(row: dict[str, Any], *keys: str) -> int | None:
    value = _value(row, *keys)
    if value is None:
        return None
    try:
        number = float(value)
        return int(number) if number.is_integer() else None
    except ValueError:
        return None


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def ingest_phase1(
    texts_path: str | Path,
    annotations_path: str | Path,
    output_dir: str | Path,
    labels_path: str | Path,
    aliases_path: str | Path,
    texts_encoding: str = "auto",
    annotations_encoding: str = "auto",
) -> dict[str, Any]:
    """Import Phase 1 into canonical documents, per-annotator annotations and issues.

    Inputs are required to contain:
      documents: id, text (or acordao)
      annotations: id_text, label_new, start_new, end_exclusive_new
    """
    texts_path = Path(texts_path)
    annotations_path = Path(annotations_path)
    output_dir = Path(output_dir)
    label_config = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    alias_config = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
    labels = set(label_config["labels"])
    aliases = alias_config["aliases"]
    if not all(target in labels for target in aliases.values()):
        raise ValueError("Aliases contain unknown target labels")
    texts, decoded_texts_as = _load_rows(texts_path, texts_encoding)
    raw_annotations, decoded_annotations_as = _load_rows(
        annotations_path, annotations_encoding
    )
    if texts and not ({"id", "text"} <= set(texts[0]) or
                      {"id", "acordao"} <= set(texts[0])):
        raise ValueError("Documents must include id and text/acordao")
    if raw_annotations and not {
        "id_text", "label_new", "start_new", "end_exclusive_new"
    } <= set(raw_annotations[0]):
        raise ValueError("Annotations must contain id_text, label_new, start_new, end_exclusive_new")

    documents: list[dict[str, Any]] = []
    document_by_source: dict[str, dict[str, Any]] = {}
    ambiguous_keys: set[str] = set()
    issues: list[dict[str, Any]] = []
    for index, row in enumerate(texts, start=2):
        source_id = _value(row, "id")
        normalized_id = normalize_document_id(source_id)
        text = row.get("text") if row.get("text") is not None else row.get("acordao")
        if not source_id or not isinstance(text, str):
            issues.append({"scope": "document", "source_row": index,
                           "code": "INVALID_DOCUMENT"})
            continue
        if normalized_id in document_by_source or normalized_id in ambiguous_keys:
            previous = document_by_source.pop(normalized_id, None)
            ambiguous_keys.add(normalized_id)
            issues.append({
                "scope": "document",
                "source_row": index,
                "code": "AMBIGUOUS_DOCUMENT_ID",
                "source_id": source_id,
                "normalized_source_id": normalized_id,
                "previous_source_id": previous["source_id"] if previous else None,
            })
            continue
        document = {
            "document_id": f"phase1:{source_id}",
            "source_id": source_id,
            "normalized_source_id": normalized_id,
            "idacordao": _value(row, "idacordao"),
            "phase": 1,
            "text": text,
            "text_sha256": _sha256(text.encode("utf-8")),
            "source_row": index,
        }
        documents.append(document)
        document_by_source[normalized_id] = document

    annotations: list[dict[str, Any]] = []
    for index, row in enumerate(raw_annotations, start=2):
        source_id = _value(row, "id_text")
        normalized_id = normalize_document_id(source_id)
        original = _value(row, "label_new", "label")
        canonical = aliases.get(original, original) if original else None
        task = ("NER" if canonical and canonical.startswith("ENT_") else
                "SEG" if canonical and canonical.startswith("SEG_") else None)
        start = _offset(row, "start_new", "start")
        end = _offset(row, "end_exclusive_new", "end")
        document = document_by_source.get(normalized_id or "")
        record_id = "phase1:" + _sha256(
            f"{annotations_path.name}:{index}".encode("utf-8")
        )[:20]
        errors: list[str] = []
        if not document:
            errors.append(
                "AMBIGUOUS_DOCUMENT_ID"
                if normalized_id in ambiguous_keys else "UNKNOWN_DOCUMENT"
            )
        if not original:
            errors.append("MISSING_LABEL")
        elif canonical not in labels:
            errors.append("UNKNOWN_LABEL")
        if start is None or end is None or start < 0 or start >= end:
            errors.append("INVALID_OFFSETS")
        elif document and end > len(document["text"]):
            errors.append("END_OUT_OF_BOUNDS")
        selected_text = _raw_span_text(row, "span_text_new", "span_text")
        if (document and start is not None and end is not None
                and 0 <= start < end <= len(document["text"])
                and selected_text is not None
                and document["text"][start:end] != selected_text):
            errors.append("SPAN_TEXT_MISMATCH")
        annotation = {
            "annotation_id": record_id,
            "document_id": document["document_id"] if document else None,
            "source_document_id": source_id,
            "normalized_source_document_id": normalized_id,
            "phase": 1,
            "source_row": index,
            "annotator_id": _value(row, "annotator"),
            "label_original": original,
            "label_canonical": canonical if canonical in labels else None,
            "task": task,
            "start": start,
            "end": end,
            "span_text_source": selected_text,
            "validation_status": "issues_found" if errors else "structurally_valid",
            "issues": errors,
        }
        annotations.append(annotation)
        for code in errors:
            issues.append({
                "scope": "annotation",
                "annotation_id": record_id,
                "source_row": index,
                "source_document_id": source_id,
                "normalized_source_document_id": normalized_id,
                "code": code,
            })
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "documents.jsonl", documents)
    _write_jsonl(output_dir / "annotations.jsonl", annotations)
    _write_jsonl(output_dir / "validation_issues.jsonl", issues)
    unmatched = Counter(
        a["source_document_id"] or "<MISSING>"
        for a in annotations
        if "UNKNOWN_DOCUMENT" in a["issues"]
    )
    matching = {
        "matched_annotations": sum(a["document_id"] is not None for a in annotations),
        "matched_after_normalization": sum(
            a["document_id"] is not None
            and a["source_document_id"] != document_by_source[
                a["normalized_source_document_id"]
            ]["source_id"]
            for a in annotations
        ),
        "unmatched_annotations": sum(unmatched.values()),
        "unmatched_source_id_counts": dict(sorted(unmatched.items())),
        "ambiguous_annotations": sum(
            "AMBIGUOUS_DOCUMENT_ID" in a["issues"] for a in annotations
        ),
    }
    manifest = {
        "schema_version": label_config["schema_version"],
        "phase": 1,
        "document_count": len(documents),
        "annotation_row_count": len(annotations),
        "issues_count": len(issues),
        "document_linkage": matching,
        "annotation_status_counts": dict(Counter(a["validation_status"] for a in annotations)),
        "task_counts": dict(Counter(a["task"] or "UNCLASSIFIED" for a in annotations)),
        "input_encodings": {
            "texts": decoded_texts_as,
            "annotations": decoded_annotations_as,
        },
        "input_sha256": {
            "texts": _sha256(texts_path.read_bytes()),
            "annotations": _sha256(annotations_path.read_bytes()),
            "labels": _sha256(Path(labels_path).read_bytes()),
            "aliases": _sha256(Path(aliases_path).read_bytes()),
        },
    }
    (output_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
