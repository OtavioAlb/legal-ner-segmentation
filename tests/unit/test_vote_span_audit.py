"""Synthetic vote span audit: keep ENT/SEG distinct and inspect geometry."""
import json

from legal_nlp.datasets.vote_span_audit import analyze_votes
from legal_nlp.io.jsonl import write_jsonl


def task(user, text, labels):
    return {
        "id": 42, "data": {"idacordao": 42, "acordao": text},
        "updated_by": user,
        "annotations": [{"completed_by": user, "result": [
            {"id": f"r{i}", "type": "labels",
             "value": {"labels": [label], "start": start,
                       "end": end, "text": text[start:end]}}
            for i, (label, start, end) in enumerate(labels)
        ]}],
    }


def test_vote_span_lengths_overlap_and_raw_absence(tmp_path):
    root = tmp_path / "snapshot"
    root.mkdir()
    doc_text = "A" * 100
    write_jsonl(root / "documents.jsonl", [
        {"document_id": "phase_2:42", "phase": "phase_2", "text": doc_text}
    ])
    write_jsonl(root / "annotations.jsonl", [
        {"document_id": "phase_2:42", "phase": "phase_2", "region_id": "ent",
         "label": "ENT_DECISAO_VOTO_VENCEDOR", "task": "NER",
         "status": "pending_review", "start": 10, "end": 30,
         "text": doc_text[10:30]},
        {"document_id": "phase_2:42", "phase": "phase_2", "region_id": "seg",
         "label": "SEG_FUNDAMENTO_DECISAO", "task": "SEG",
         "status": "consolidated", "start": 0, "end": 50,
         "text": doc_text[:50]},
    ])
    (root / "dataset_manifest.json").write_text(json.dumps({
        "training_ready": False, "document_count": 1,
        "annotation_count": 2, "corpus_version": "test"
    }), encoding="utf-8")
    paths = []
    for name, user in (("o", 8), ("11", 7), ("17", 5)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps([task(user, doc_text, [
            ("ENT_DECISAO_VOTO_VENCEDOR", 10, 30)
        ])]), encoding="utf-8")
        paths.append(path)
    result = analyze_votes(root, *paths)
    ent = next(x for x in result["label_statistics"] if x["phase"] == "phase_2"
               and x["label"] == "ENT_DECISAO_VOTO_VENCEDOR")
    assert ent["pending_review"] == 1
    assert ent["character_lengths"]["median"] == 20
    span = next(x for x in result["spans"] if x["label"] == "ENT_DECISAO_VOTO_VENCEDOR")
    assert span["overlapping_segments"][0]["entity_contained_by_segment"] is True
    assert result["phase2_raw_label_counts"]["11"]["SEG_JURISPRUDENCIA_VOTO_VENCIDO"]["region_occurrences"] == 0


def test_vote_vencido_segment_is_not_mapped_to_entity(tmp_path):
    root = tmp_path / "snapshot"
    root.mkdir()
    doc_text = "um dois tres"
    write_jsonl(root / "documents.jsonl", [
        {"document_id": "phase_1:1", "phase": "phase_1", "text": doc_text}
    ])
    write_jsonl(root / "annotations.jsonl", [
        {"document_id": "phase_1:1", "phase": "phase_1", "region_id": "v",
         "label": "SEG_DECISAO_VOTO_VENCIDO", "task": "SEG",
         "status": "consolidated", "start": 0, "end": 7,
         "text": doc_text[:7]},
    ])
    (root / "dataset_manifest.json").write_text(json.dumps({
        "training_ready": False, "document_count": 1,
        "annotation_count": 1, "corpus_version": "test2"
    }), encoding="utf-8")
    report = analyze_votes(root)
    seg = next(x for x in report["label_statistics"] if x["phase"] == "phase_1"
               and x["label"] == "SEG_DECISAO_VOTO_VENCIDO")
    ent = next(x for x in report["label_statistics"] if x["phase"] == "phase_1"
               and x["label"] == "ENT_DECISAO_VOTO_VENCIDO")
    assert seg["occurrences"] == 1
    assert ent["occurrences"] == 0
