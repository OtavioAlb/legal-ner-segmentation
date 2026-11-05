import hashlib
import json

import pytest

from legal_nlp.document_dataset import build_document_dataset


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _document(i, text=None):
    text = text if text is not None else f"Acórdão sintético #{i}: conteúdo diferente"
    return {
        "document_id": f"phase1:{i}",
        "source_id": str(i),
        "idacordao": f"AC-{i}",
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _span(i, task="NER", start=0, end=7, label=None):
    label = label or ("ENT_RELATOR" if task == "NER" else "SEG_EMENTA")
    # Unique per logical span: same document/task can have different labels
    # at identical offsets, which is valid for span-based annotation.
    key = f"{i}_{task}_{start}_{end}_{label}"
    return {
        "logical_span_id": f"ls_{key}",
        "document_id": f"phase1:{i}",
        "task": task,
        "start": start,
        "end": end,
        "label": label,
        "source_annotation_count": 2,
        "provenance": [
            {"annotation_id": f"a{key}_1", "source_row": i * 2 + 1},
            {"annotation_id": f"a{key}_2", "source_row": i * 2 + 2},
        ],
    }


def test_document_dataset_has_disjoint_deterministic_5_fold_split(tmp_path):
    documents = [_document(i) for i in range(25)]
    # Same geometry but two different NER labels is valid (span-based).
    spans = [_span(i) for i in range(25)]
    spans.append(_span(0, task="SEG", start=0, end=20))
    spans.append(_span(1, task="NER", label="ENT_CLASSE"))
    docpath = tmp_path / "documents.jsonl"
    spanpath = tmp_path / "logical_spans.jsonl"
    out = tmp_path / "out"
    _write_jsonl(docpath, documents)
    _write_jsonl(spanpath, spans)
    result = build_document_dataset(docpath, spanpath, out)
    assert result["document_count"] == 25
    assert result["logical_span_count"] == 27
    assert result["source_annotation_count_preserved"] == 54
    assert result["logical_span_count_by_task"] == {"NER": 26, "SEG": 1}
    assert result["fold_sizes"] == [5, 5, 5, 5, 5]
    folds = json.loads((out / "document_folds.json").read_text(encoding="utf-8"))
    seen = set()
    for fold in folds["fold_assignments"]:
        train = set(fold["training_document_ids"])
        val = set(fold["validation_document_ids"])
        assert len(train) == 20
        assert len(val) == 5
        assert not train & val
        assert seen.isdisjoint(val)
        seen.update(val)
    assert len(seen) == 25
    rows = [json.loads(x) for x in (out / "document_spans.jsonl").read_text().splitlines()]
    assert len(rows) == 25
    assert rows[0]["spans"]["SEG"]
    assert len(rows[1]["spans"]["NER"]) == 2
    previous = (out / "document_folds.json").read_bytes()
    previous_spans = (out / "document_spans.jsonl").read_bytes()
    # Input file order must not affect folds or outputs.
    _write_jsonl(docpath, reversed(documents))
    _write_jsonl(spanpath, reversed(spans))
    assert build_document_dataset(docpath, spanpath, out) == result
    assert (out / "document_folds.json").read_bytes() == previous
    assert (out / "document_spans.jsonl").read_bytes() == previous_spans


def test_document_dataset_rejects_identical_document_text(tmp_path):
    docs = [_document(1, "Mesma decisão"), _document(2, "Mesma decisão")]
    docpath = tmp_path / "documents.jsonl"
    spanpath = tmp_path / "spans.jsonl"
    _write_jsonl(docpath, docs)
    _write_jsonl(spanpath, [])
    with pytest.raises(ValueError, match="Identical text"):
        build_document_dataset(docpath, spanpath, tmp_path / "out", folds=2)


def test_document_dataset_rejects_unknown_span_document(tmp_path):
    docpath = tmp_path / "documents.jsonl"
    spanpath = tmp_path / "spans.jsonl"
    _write_jsonl(docpath, [_document(1), _document(2)])
    _write_jsonl(spanpath, [_span(3)])
    with pytest.raises(ValueError, match="unknown document"):
        build_document_dataset(docpath, spanpath, tmp_path / "out", folds=2)


def test_document_dataset_rejects_invalid_source_hash(tmp_path):
    doc = _document(1)
    doc["text_sha256"] = "not-a-hash"
    docpath = tmp_path / "documents.jsonl"
    spanpath = tmp_path / "spans.jsonl"
    _write_jsonl(docpath, [doc, _document(2)])
    _write_jsonl(spanpath, [])
    with pytest.raises(ValueError, match="checksum mismatch"):
        build_document_dataset(docpath, spanpath, tmp_path / "out", folds=2)


def test_document_dataset_rejects_shared_acordao_id(tmp_path):
    docs = [_document(1), _document(2)]
    docs[1]["idacordao"] = docs[0]["idacordao"]
    docpath = tmp_path / "documents.jsonl"
    spanpath = tmp_path / "spans.jsonl"
    _write_jsonl(docpath, docs)
    _write_jsonl(spanpath, [])
    with pytest.raises(ValueError, match="Repeated idacordao"):
        build_document_dataset(docpath, spanpath, tmp_path / "out", folds=2)


def test_document_dataset_rejects_duplicate_logical_span_id(tmp_path):
    docpath = tmp_path / "documents.jsonl"
    spanpath = tmp_path / "spans.jsonl"
    _write_jsonl(docpath, [_document(1), _document(2)])
    a = _span(1)
    b = _span(2)
    b["logical_span_id"] = a["logical_span_id"]
    _write_jsonl(spanpath, [a, b])
    with pytest.raises(ValueError, match="duplicate logical span ID"):
        build_document_dataset(docpath, spanpath, tmp_path / "out", folds=2)
