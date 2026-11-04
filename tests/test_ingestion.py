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


def test_cp1252_csv_with_portuguese_accents(tmp_path):
    docs = tmp_path / "docs.csv"
    spans = tmp_path / "spans.csv"
    labels = tmp_path / "labels.json"
    aliases = tmp_path / "aliases.json"
    output = tmp_path / "out"

    docs.write_bytes('id;text\n1;"O acórdão contém perícia."\n'.encode("cp1252"))
    spans.write_bytes(
        'id_text;label_new;start_new;end_exclusive_new;span_text_new;annotator\n'
        '1;ENT_PROVA_PERICIA;17;24;perícia;A\n'.encode("cp1252")
    )
    labels.write_text(
        json.dumps({"schema_version": "1", "labels": ["ENT_PROVA_PERICIA"]}),
        encoding="utf-8",
    )
    aliases.write_text('{"aliases":{}}', encoding="utf-8")

    manifest = ingest_phase1(docs, spans, output, labels, aliases)
    assert manifest["input_encodings"] == {
        "texts": "cp1252",
        "annotations": "cp1252",
    }
    annotations = _jsonl(output / "annotations.jsonl")
    assert annotations[0]["span_text_source"] == "perícia"
    assert annotations[0]["validation_status"] == "structurally_valid"


def test_encoding_override_is_strict(tmp_path):
    from pytest import raises

    from legal_nlp.ingestion import _decode_csv

    raw = "ação, perícia, parágrafo".encode("cp1252")
    assert _decode_csv(raw, "cp1252")[0] == "ação, perícia, parágrafo"
    with raises(UnicodeDecodeError):
        _decode_csv(raw, "utf-8")

def test_document_id_normalization_is_conservative():
    from legal_nlp.ingestion import normalize_document_id

    assert normalize_document_id("290.0") == "290"
    assert normalize_document_id("290.000") == "290"
    assert normalize_document_id("00290.0") == "00290"
    assert normalize_document_id("290.1") == "290.1"
    assert normalize_document_id("TJ-290") == "TJ-290"
    assert normalize_document_id(None) is None


def test_document_linkage_preserves_unmatched_records(tmp_path):
    docs, spans = tmp_path / "docs.csv", tmp_path / "spans.csv"
    labels, aliases = tmp_path / "labels.json", tmp_path / "aliases.json"
    labels.write_text('{"schema_version":"1","labels":["ENT_RELATOR"]}', encoding="utf-8")
    aliases.write_text('{"aliases":{}}', encoding="utf-8")
    _csv(docs, ["id", "text"], [{"id": "290", "text": "Juiz"}])
    _csv(spans, ["id_text", "label_new", "start_new", "end_exclusive_new"], [
        {"id_text": "290.0", "label_new": "ENT_RELATOR", "start_new": "0",
         "end_exclusive_new": "4"},
        {"id_text": "999.0", "label_new": "ENT_RELATOR", "start_new": "0",
         "end_exclusive_new": "4"},
    ])
    out = tmp_path / "out"
    manifest = ingest_phase1(docs, spans, out, labels, aliases)
    assert manifest["document_linkage"]["matched_annotations"] == 1
    assert manifest["document_linkage"]["matched_after_normalization"] == 1
    assert manifest["document_linkage"]["unmatched_annotations"] == 1
    assert manifest["document_linkage"]["unmatched_source_id_counts"] == {"999.0": 1}
    rows = _jsonl(out / "annotations.jsonl")
    assert rows[0]["document_id"] == "phase1:290"
    assert rows[0]["source_document_id"] == "290.0"
    assert rows[0]["issues"] == []
    assert rows[1]["document_id"] is None
    assert "UNKNOWN_DOCUMENT" in rows[1]["issues"]


def test_ambiguous_normalized_identifiers_are_not_joined(tmp_path):
    docs, spans = tmp_path / "docs.csv", tmp_path / "spans.csv"
    labels, aliases = tmp_path / "labels.json", tmp_path / "aliases.json"
    labels.write_text('{"schema_version":"1","labels":["ENT_RELATOR"]}', encoding="utf-8")
    aliases.write_text('{"aliases":{}}', encoding="utf-8")
    _csv(docs, ["id", "text"], [
        {"id": "290", "text": "Juiz"},
        {"id": "290.0", "text": "Juiz"},
    ])
    _csv(spans, ["id_text", "label_new", "start_new", "end_exclusive_new"], [
        {"id_text": "290.0", "label_new": "ENT_RELATOR",
         "start_new": "0", "end_exclusive_new": "4"}
    ])
    out = tmp_path / "out"
    manifest = ingest_phase1(docs, spans, out, labels, aliases)
    assert manifest["document_linkage"]["matched_annotations"] == 0
    assert manifest["document_linkage"]["ambiguous_annotations"] == 1
    rows = _jsonl(out / "annotations.jsonl")
    assert "AMBIGUOUS_DOCUMENT_ID" in rows[0]["issues"]


def test_span_text_whitespace_is_preserved(tmp_path):
    docs, spans = tmp_path / "docs.csv", tmp_path / "spans.csv"
    labels, aliases = tmp_path / "labels.json", tmp_path / "aliases.json"
    labels.write_text('{"schema_version":"1","labels":["ENT_RELATOR"]}', encoding="utf-8")
    aliases.write_text('{"aliases":{}}', encoding="utf-8")
    _csv(docs, ["id", "text"], [{"id": "290", "text": " Juiz "}])
    _csv(spans, ["id_text", "label_new", "start_new", "end_exclusive_new",
                 "span_text_new"], [
        {"id_text": "290.0", "label_new": "ENT_RELATOR", "start_new": "0",
         "end_exclusive_new": "6", "span_text_new": " Juiz "}
    ])
    out = tmp_path / "out"
    manifest = ingest_phase1(docs, spans, out, labels, aliases)
    rows = _jsonl(out / "annotations.jsonl")
    assert rows[0]["span_text_source"] == " Juiz "
    assert rows[0]["issues"] == []
    assert manifest["annotation_status_counts"] == {"structurally_valid": 1}


def test_missing_revised_span_is_not_resurrected(tmp_path):
    docs, spans = tmp_path / "docs.csv", tmp_path / "spans.csv"
    labels, aliases = tmp_path / "labels.json", tmp_path / "aliases.json"
    labels.write_text('{"schema_version":"1","labels":["ENT_RELATOR"]}', encoding="utf-8")
    aliases.write_text('{"aliases":{}}', encoding="utf-8")
    _csv(docs, ["id", "text"], [{"id": "290", "text": " Juiz "}])
    _csv(spans, ["id_text", "label_new", "start_new", "end_exclusive_new",
                 "span_text_new", "span_text"], [
        {"id_text": "290.0", "label_new": "ENT_RELATOR", "start_new": "0",
         "end_exclusive_new": "6", "span_text_new": "", "span_text": " Juiz "}
    ])
    out = tmp_path / "out"
    ingest_phase1(docs, spans, out, labels, aliases)
    rows = _jsonl(out / "annotations.jsonl")
    assert rows[0]["span_text_source"] is None
    assert rows[0]["fields_original"]["span_text"] == " Juiz "
    assert rows[0]["fields_revised"]["span_text"] is None
    assert rows[0]["review_state"] == "revised_incomplete"
    assert "EMPTY_REVISED_SPAN_TEXT_NEW" in rows[0]["review_flags"]
    assert rows[0]["issues"] == []


def test_original_reviewed_values_and_reviewer_opinions_remain_separate(tmp_path):
    docs, spans = tmp_path / "docs.csv", tmp_path / "spans.csv"
    labels, aliases = tmp_path / "labels.json", tmp_path / "aliases.json"
    labels.write_text('{"schema_version":"1","labels":["ENT_RELATOR"]}', encoding="utf-8")
    aliases.write_text('{"aliases":{}}', encoding="utf-8")
    _csv(docs, ["id", "text"], [{"id": "290", "text": "Juiz"}])
    _csv(spans, ["id_text", "label", "label_new", "start", "start_new",
                 "end_exclusive", "end_exclusive_new", "span_text", "span_text_new",
                 "concorda_Emily", "comentario_Emily"], [{
        "id_text": "290.0", "label": "ENT_RELATOR", "label_new": "",
        "start": "0", "start_new": "", "end_exclusive": "4",
        "end_exclusive_new": "", "span_text": "Juiz", "span_text_new": "",
        "concorda_Emily": "NÃO", "comentario_Emily": "Revisar",
    }])
    out = tmp_path / "out"
    manifest = ingest_phase1(docs, spans, out, labels, aliases)
    ann = _jsonl(out / "annotations.jsonl")[0]
    assert ann["fields_original"]["label"] == "ENT_RELATOR"
    assert ann["fields_revised"]["label"] is None
    assert ann["label_original"] is None
    assert ann["label_canonical"] is None
    assert ann["start"] is None and ann["end"] is None
    assert "MISSING_LABEL" in ann["issues"]
    assert "INVALID_OFFSETS" in ann["issues"]
    assert ann["review_state"] == "revised_all_empty"
    assert len(ann["review_flags"]) == 4
    assert ann["reviewer_opinions"]["Emily"] == {
        "agreement_raw": "NÃO", "comment_raw": "Revisar"
    }
    assert manifest["review_state_counts"] == {"revised_all_empty": 1}


def test_explicit_disagreement_requires_correction_verification(tmp_path):
    from legal_nlp.ingestion import normalize_review_vote

    assert normalize_review_vote("NÃO ") == "disagree"
    assert normalize_review_vote("NAO") == "disagree"
    assert normalize_review_vote("sim") == "agree"
    assert normalize_review_vote(" ") == "not_recorded"
    assert normalize_review_vote(None) == "not_recorded"
    assert normalize_review_vote("corrigir texto") == "other_not_interpreted"

    docs, spans = tmp_path / "docs.csv", tmp_path / "spans.csv"
    labels, aliases = tmp_path / "labels.json", tmp_path / "aliases.json"
    labels.write_text('{"schema_version":"1","labels":["SEG_EMENTA","SEG_RELATORIO"]}', encoding="utf-8")
    aliases.write_text('{"aliases":{}}', encoding="utf-8")
    _csv(docs, ["id", "text"], [{"id": "290", "text": "Juiz"}])
    columns = [
        "id_text", "label", "label_new", "start", "start_new",
        "end_exclusive", "end_exclusive_new", "span_text", "span_text_new",
        "concorda_A", "concorda_B", "concorda_C",
    ]
    base = {
        "id_text": "290.0", "label": "SEG_EMENTA",
        "start": "0", "start_new": "0", "end_exclusive": "4",
        "end_exclusive_new": "4", "span_text": "Juiz", "span_text_new": "Juiz",
        "concorda_A": "SIM", "concorda_B": "NÃO", "concorda_C": "",
    }
    rows = [
        {**base, "label_new": "SEG_RELATORIO"},
        {**base, "label_new": "SEG_EMENTA"},
    ]
    _csv(spans, columns, rows)
    output = tmp_path / "out"
    manifest = ingest_phase1(docs, spans, output, labels, aliases)
    anns = _jsonl(output / "annotations.jsonl")

    assert anns[0]["reviewer_opinions"]["A"]["status"] == "agree"
    assert anns[0]["reviewer_opinions"]["B"]["status"] == "disagree"
    assert anns[0]["reviewer_opinions"]["C"]["status"] == "not_recorded"
    assert anns[0]["disagreement_reviewers"] == ["B"]
    assert anns[0]["changed_review_fields"] == ["label"]
    assert anns[0]["correction_status"] == "revised_fields_differ_pending_verification"
    assert anns[1]["correction_status"] == "no_field_change_located"
    assert manifest["correction_status_counts"] == {
        "revised_fields_differ_pending_verification": 1,
        "no_field_change_located": 1,
    }
