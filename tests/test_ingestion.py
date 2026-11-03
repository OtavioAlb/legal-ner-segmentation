import csv
import json

from legal_nlp.ingestion import ingest_phase1


def _csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_ingestion_preserves_duplicates_and_reports_problems(tmp_path):
    docs = tmp_path / "docs.csv"
    spans = tmp_path / "spans.csv"
    labels = tmp_path / "labels.json"
    aliases = tmp_path / "aliases.json"
    out = tmp_path / "processed"

    labels.write_text(json.dumps({"schema_version": "1.0.0", "labels": [
        "ENT_NORMA_ARTIGO", "SEG_EMENTA"]}), encoding="utf-8")
    aliases.write_text(json.dumps({"aliases": {
        "ENT_NORM_ARTIGO": "ENT_NORMA_ARTIGO"}}), encoding="utf-8")
    _csv(docs, ["id", "idacordao", "text"], [
        {"id": "101", "idacordao": "AC-1", "text": "Art. 5 define a ementa."}])
    rows = [
        {"id_text": "101", "label_new": "ENT_NORM_ARTIGO",
         "start_new": "0", "end_exclusive_new": "6", "span_text_new": "Art. 5",
         "annotator": "A"},
        {"id_text": "101", "label_new": "ENT_NORM_ARTIGO",
         "start_new": "0", "end_exclusive_new": "6", "span_text_new": "Art. 5",
         "annotator": "B"},
        {"id_text": "101", "label_new": "SEG_EMENTA",
         "start_new": "0", "end_exclusive_new": "21",
         "span_text_new": "Art. 5 define a ementa.", "annotator": "A"},
        {"id_text": "101", "label_new": "ENT_UNKNOWN",
         "start_new": "0", "end_exclusive_new": "200",
         "span_text_new": "", "annotator": "A"},
    ]
    _csv(spans, list(rows[0]), rows)
    manifest = ingest_phase1(docs, spans, out, labels, aliases)
    annotations = _jsonl(out / "annotations.jsonl")
    assert manifest["annotation_row_count"] == 4
    assert len(annotations) == 4
    assert annotations[0]["label_canonical"] == "ENT_NORMA_ARTIGO"
    assert annotations[0]["annotator_id"] == "A"
    assert annotations[1]["annotator_id"] == "B"
    assert annotations[2]["task"] == "SEG"
    assert "UNKNOWN_LABEL" in annotations[3]["issues"]
    assert "END_OUT_OF_BOUNDS" in annotations[3]["issues"]


def test_ingestion_is_reproducible(tmp_path):
    docs, spans = tmp_path / "d.csv", tmp_path / "a.csv"
    labels, aliases = tmp_path / "l.json", tmp_path / "m.json"
    labels.write_text('{"schema_version":"1","labels":["ENT_RELATOR"]}', encoding="utf-8")
    aliases.write_text('{"aliases":{}}', encoding="utf-8")
    _csv(docs, ["id", "text"], [{"id": "1", "text": "Juiz"}])
    _csv(spans, ["id_text", "label_new", "start_new", "end_exclusive_new"], [
        {"id_text": "1", "label_new": "ENT_RELATOR", "start_new": "0",
         "end_exclusive_new": "4"}])
    ingest_phase1(docs, spans, tmp_path / "one", labels, aliases)
    ingest_phase1(docs, spans, tmp_path / "two", labels, aliases)
    for filename in ["documents.jsonl", "annotations.jsonl", "validation_issues.jsonl",
                     "dataset_manifest.json"]:
        assert (tmp_path / "one" / filename).read_bytes() == (
            tmp_path / "two" / filename).read_bytes()
