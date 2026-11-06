import json

from legal_nlp.sanitization import sanitize_phase1


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _case(tmp_path, docs, anns):
    source = tmp_path / "dataset"
    source.mkdir()
    _write_jsonl(source / "documents.jsonl", docs)
    _write_jsonl(source / "annotations.jsonl", anns)
    labels = tmp_path / "labels.json"
    rules = tmp_path / "rules.json"
    labels.write_text(json.dumps({"labels": ["ENT_RELATOR", "ENT_NORMA_LEI", "SEG_EMENTA"]}))
    rules.write_text(json.dumps({
        "approved_label_aliases": {"ENT_NORM_LEI": "ENT_NORMA_LEI"},
        "accepted_text_equivalences": ["case_only"],
    }))
    return source, tmp_path / "sanitized", labels, rules


def _run(paths):
    return sanitize_phase1(*paths)


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _ann(identifier, **changes):
    base = {
        "annotation_id": identifier, "source_row": 2,
        "document_id": "phase1:1", "source_document_id": "1",
        "label_original": "ENT_RELATOR", "label_canonical": "ENT_RELATOR",
        "start": 0, "end": 4, "span_text_source": "Juiz",
        "task": "NER", "annotator_id": "A",
        "issues": [], "target_selection_status": "reviewed_final",
    }
    return {**base, **changes}


def test_sanitization_keeps_baseline_and_restores_lexical_alias(tmp_path):
    docs = [{"document_id": "phase1:1", "text": "Juiz lei"}]
    anns = [
        _ann("baseline"),
        _ann("alias", source_row=3, start=5, end=8,
             span_text_source="lei", label_original="ENT_NORM_LEI",
             label_canonical=None, issues=["UNKNOWN_LABEL"]),
    ]
    paths = _case(tmp_path, docs, anns)
    summary = _run(paths)
    assert summary["baseline_eligible_count"] == 1
    assert summary["sanitized_supervised_count"] == 2
    assert summary["newly_eligible_count"] == 1
    assert summary["recovery_by_rule"] == {"explicit_lexical_alias": 1}
    result = _rows(paths[1] / "sanitized_annotations.jsonl")
    assert result[1]["label"] == "ENT_NORMA_LEI"
    assert result[1]["sanitization_rule_ids"] == ["explicit_lexical_alias"]
    assert _rows(paths[1] / "sanitization_exclusions.jsonl") == []
    # Repeat to verify deterministic, idempotent output.
    previous = (paths[1] / "sanitization_summary.json").read_bytes()
    assert _run(paths) == summary
    assert (paths[1] / "sanitization_summary.json").read_bytes() == previous


def test_unique_exact_document_match_only_without_original_id(tmp_path):
    docs = [
        {"document_id": "phase1:1", "text": "JUiZ"},
        {"document_id": "phase1:2", "text": "Juiz"},
        {"document_id": "phase1:3", "text": "Casa"},
    ]
    anns = [
        _ann("recover", document_id=None, source_document_id=None,
             issues=["UNKNOWN_DOCUMENT"]),
        _ann("refuse_id", source_row=3, document_id=None,
             source_document_id="unknown", issues=["UNKNOWN_DOCUMENT"]),
        _ann("no_match", source_row=4, document_id=None,
             source_document_id=None, span_text_source="zzzz",
             issues=["UNKNOWN_DOCUMENT"]),
    ]
    paths = _case(tmp_path, docs, anns)
    summary = _run(paths)
    assert summary["sanitized_supervised_count"] == 1
    assert summary["excluded_count"] == 2
    assert _rows(paths[1] / "sanitized_annotations.jsonl")[0]["document_id"] == "phase1:2"
    exclusions = _rows(paths[1] / "sanitization_exclusions.jsonl")
    assert "DOCUMENT_ID_PRESENT_BUT_UNRESOLVED" in exclusions[0]["reasons"]
    assert "DOCUMENT_LINKAGE_ZERO_CANDIDATES" in exclusions[1]["reasons"]


def test_ambiguous_linkage_and_conflicts_fail_closed(tmp_path):
    docs = [
        {"document_id": "phase1:1", "text": "Juiz"},
        {"document_id": "phase1:2", "text": "Juiz"},
    ]
    anns = [
        _ann("ambiguous", document_id=None, source_document_id=None,
             issues=["UNKNOWN_DOCUMENT"]),
        _ann("conflict", source_row=3,
             target_selection_status="conflicting_votes_without_correction",
             issues=["MISSING_LABEL", "INVALID_OFFSETS"],
             label_canonical=None, start=None, end=None),
        _ann("unmapped", source_row=4, issues=["UNKNOWN_LABEL"],
             label_original="ENT_JUR_DECISAO", label_canonical=None),
    ]
    paths = _case(tmp_path, docs, anns)
    summary = _run(paths)
    assert summary["sanitized_supervised_count"] == 0
    assert summary["excluded_count"] == 3
    exclusions = _rows(paths[1] / "sanitization_exclusions.jsonl")
    assert "DOCUMENT_LINKAGE_AMBIGUOUS" in exclusions[0]["reasons"]
    assert "NO_VALIDATED_TARGET_SELECTION" in exclusions[1]["reasons"]
    assert "UNRESOLVED_CANONICAL_LABEL" in exclusions[2]["reasons"]


def test_case_only_text_is_accepted_but_whitespace_and_other_are_not(tmp_path):
    docs = [{"document_id": "phase1:1", "text": "Juiz juiz outro"}]
    anns = [
        _ann("case", span_text_source="juiz", issues=["SPAN_TEXT_MISMATCH"]),
        _ann("space", source_row=3, start=5, end=9, span_text_source=" juiz",
             issues=["SPAN_TEXT_MISMATCH"]),
        _ann("other", source_row=4, start=10, end=15, span_text_source="alter",
             issues=["SPAN_TEXT_MISMATCH"]),
    ]
    paths = _case(tmp_path, docs, anns)
    summary = _run(paths)
    assert summary["sanitized_supervised_count"] == 1
    assert summary["recovery_by_rule"] == {"verified_case_only_text_equivalence": 1}
    result = _rows(paths[1] / "sanitized_annotations.jsonl")[0]
    assert (result["start"], result["end"]) == (0, 4)
    assert result["text_equivalence"] == "case_only"
    assert summary["excluded_count"] == 2


def test_only_positive_original_confirmation_is_eligible(tmp_path):
    docs = [{"document_id": "phase1:1", "text": "Juiz"}]
    anns = [
        _ann("confirmed", target_selection_status="original_confirmed_by_reviewers"),
        _ann("no_vote", source_row=3,
             target_selection_status="no_evaluation_no_correction"),
    ]
    paths = _case(tmp_path, docs, anns)
    summary = _run(paths)
    assert summary["sanitized_supervised_count"] == 1
    assert _rows(paths[1] / "sanitized_annotations.jsonl")[0]["source_of_truth"] == (
        "original_confirmed_by_reviewers"
    )
