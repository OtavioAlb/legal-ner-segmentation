"""Synthetic regression for cross-project Phase 2 text identity."""
import json

import pytest

from legal_nlp.datasets.cross_project_text_integrity import compare_document_texts


def task(text, user):
    return {
        "id": 42, "data": {"idacordao": 42, "acordao": text},
        "updated_by": user,
        "annotations": [{"completed_by": user, "result": []}],
    }


def save(tmp_path, texts):
    paths = []
    for name, text, user in zip(("original", "11", "17"), texts, (8, 7, 5)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps([task(text, user)]), encoding="utf-8")
        paths.append(p)
    return paths


def test_equal_texts_verified_without_mutation(tmp_path):
    paths = save(tmp_path, ("ação\n", "ação\n", "ação\n"))
    before = [p.read_bytes() for p in paths]
    report = compare_document_texts(*paths)
    assert report["document_count"] == 1
    assert report["identical_document_count"] == 1
    assert report["different_document_count"] == 0
    assert all(p.read_bytes() == before[i] for i, p in enumerate(paths))


def test_different_texts_detected_even_equal_length(tmp_path):
    paths = save(tmp_path, ("AÇÃO", "ACAO", "AÇÃO"))
    report = compare_document_texts(*paths)
    assert report["different_document_count"] == 1
    item = report["different_documents"][0]
    assert item["idacordao"] == "42"
    assert item["lengths"] == {"original": 4, "11": 4, "17": 4}
    assert item["equals_original"] == {"11": False, "17": True}
    assert "AÇÃO" not in str(item)


def test_document_sets_must_match(tmp_path):
    paths = save(tmp_path, ("a", "a", "a"))
    paths[2].write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Document sets differ"):
        compare_document_texts(*paths)
