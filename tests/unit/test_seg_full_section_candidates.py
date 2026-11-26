"""Pure, synthetic tests of whole-section candidate triage."""
import pytest

from legal_nlp.datasets.seg_full_section_candidates import _relation, triage_families


def candidate(identifier, start, end, agree=1, disagree=0):
    return {
        "logical_span_id": identifier, "start": start, "end": end,
        "distinct_reviewers_agreeing": agree,
        "distinct_reviewers_disagreeing": disagree,
        "source_annotation_count": 1,
    }


def evidence(*candidates):
    return {
        "training_ready": False, "components_total": 1,
        "verified_export_sha256": {"texts": "abc", "annotations": "def"},
        "review_queue": [{
            "document_id": "phase_1:phase1:300",
            "label": "SEG_RELATORIO", "number_of_regions": len(candidates),
            "source_annotation_count": len(candidates),
            "candidates": list(candidates),
        }],
    }


def test_identify_maximal_supported_interval_not_as_gold():
    r = triage_families(evidence(
        candidate("long", 1426, 4151, agree=3),
        candidate("short", 1426, 2312, agree=2),
        candidate("near", 1426, 4150, agree=2),
        candidate("rejected", 4152, 4567, agree=0, disagree=2),
    ))
    group = r["families"][0]
    assert group["maximal_supported_logical_ids"] == ["long"]
    assert group["pair_relations_among_positively_evaluated"]["near_equal"] == 1
    assert group["pair_relations_among_positively_evaluated"]["containment"] == 2
    assert group["requires_manual_review"] is True
    assert r["training_ready"] is False
    assert "gold" in r["mode"]
    assert len(group["candidates"]) == 4


def test_partially_overlapping_support_both_remain_candidates():
    r = triage_families(evidence(
        candidate("a", 10, 20), candidate("b", 15, 25)
    ), near_tolerance=1)
    group = r["families"][0]
    assert group["maximal_supported_logical_ids"] == ["a", "b"]
    assert group["pair_relations_among_positively_evaluated"]["partial_overlap"] == 1


def test_rejected_outer_region_cannot_dominate_positive_inner_region():
    r = triage_families(evidence(
        candidate("rejected_outer", 0, 100, agree=0, disagree=2),
        candidate("approved_inner", 20, 80, agree=2),
    ))
    assert r["families"][0]["maximal_supported_logical_ids"] == ["approved_inner"]
    assert r["families"][0]["requires_manual_review"]


def test_touching_intervals_are_disjoint():
    assert _relation(candidate("a", 0, 10), candidate("b", 10, 20), 1) == "disjoint"


def test_fail_closed_if_report_is_sampled():
    e = evidence(candidate("a", 0, 10), candidate("b", 0, 9))
    e["components_total"] = 187
    with pytest.raises(ValueError, match="All verified overlap"):
        triage_families(e)


def test_fail_closed_if_report_claims_training_ready():
    e = evidence(candidate("a", 0, 10), candidate("b", 0, 9))
    e["training_ready"] = True
    with pytest.raises(ValueError, match="non-gold"):
        triage_families(e)


def test_no_supported_geometry_is_not_promoted():
    r = triage_families(evidence(
        candidate("a", 0, 10, agree=0, disagree=2),
        candidate("b", 0, 8, agree=0, disagree=1),
    ))
    group = r["families"][0]
    assert group["maximal_supported_logical_ids"] == []
    assert group["status"] == "no_positive_evaluator_support"
