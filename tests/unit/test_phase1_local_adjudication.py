"""Offline adjudication UI: provenance, security, review-only output."""
import hashlib
import json

import pytest

from legal_nlp.datasets import phase1_local_adjudication as mod


def test_page_escapes_untrusted_document_text_and_comments(tmp_path):
    output=tmp_path/"private_review.html"
    payload={
        "training_ready":False,"document_id":"phase_1:phase1:300",
        "text":"A</script><img src=x onerror=alert(1)>",
        "regions":[{"id":"x","label":"SEG_RELATORIO","start":0,"end":2,
                    "origins":[{"votes":[{"comment":"</script><script>alert(1)</script>"}]}]}],
        "overlap_families":[],"text_sha256":"verified",
        "verified_raw_export_sha256":{"texts":"abc","annotations":"def"}
    }
    result=mod.write_review_html(payload,output)
    assert result["training_ready"] is False
    page=output.read_text(encoding="utf-8")
    assert "</script><img" not in page
    assert "</script><script>alert" not in page
    assert "\\u003c/script\\u003e" in page
    assert 'status:"proposed_review_only_not_gold"' in page
    assert "URL.createObjectURL" in page
    assert "textContent" in page
    with pytest.raises(FileExistsError,match="already exists"):
        mod.write_review_html(payload,output)


def test_reject_gold_payload(tmp_path):
    with pytest.raises(ValueError,match="review-only"):
        mod.write_review_html({"training_ready":True},tmp_path/"page.html")


def test_review_payload_joins_document_and_all_seg_sources(tmp_path,monkeypatch):
    source_text="0123456789abcdefghij"
    source={"annotation_id":"phase1:row","source_row":5,
            "annotator_id":"annotator 3","target_selection_status":"reviewed_final",
            "review_agree_count":1,"review_disagree_count":1,
            "fields_original":{"label":"SEG_RELATORIO","start":1,"end":10},
            "fields_revised":{"label":"SEG_RELATORIO","start":1,"end":10},
            "reviewer_opinions":{
                "A":{"status":"agree","comment_raw":"ok"},
                "B":{"status":"disagree","comment_raw":"ajustar final"}}}
    monkeypatch.setattr(mod,"audit_phase1_lineage",
                        lambda *args:{"verified_raw_export_sha256":{"texts":"x","annotations":"y"}})
    monkeypatch.setattr(mod,"_verified_source_votes",
                        lambda *args:{"phase1:row":{"opinions":{"A":{"status":"agree"},
                                                                  "B":{"status":"disagree"}}}})
    monkeypatch.setattr(mod,"read_jsonl",lambda *args:[source])
    monkeypatch.setattr(mod,"_validate_and_load",lambda *args:(
        [{"phase":"phase_1","document_id":"phase_1:phase1:300","text":source_text}],
        [{"phase":"phase_1","document_id":"phase_1:phase1:300","task":"SEG",
          "region_id":"ls_one","label":"SEG_RELATORIO","source_label":"SEG_RELATORIO",
          "start":1,"end":10,"provenance":[{"annotation_id":"phase1:row"}]}],
        None,None,None
    ))
    result=mod.build_review_payload(tmp_path,tmp_path,tmp_path,tmp_path,tmp_path,
                                    tmp_path,tmp_path,tmp_path,tmp_path,
                                    "phase_1:phase1:300")
    assert result["text_sha256"]==hashlib.sha256(source_text.encode()).hexdigest()
    assert len(result["regions"])==1
    assert result["regions"][0]["origins"][0]["annotator_id"]=="annotator 3"
    assert result["regions"][0]["origins"][0]["votes"][1]["comment"]=="ajustar final"
    assert result["overlap_families"]==[]
    assert result["training_ready"] is False


def test_unknown_document_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(mod,"audit_phase1_lineage",
                        lambda *args:{"verified_raw_export_sha256":{}})
    monkeypatch.setattr(mod,"_verified_source_votes",lambda *args:{})
    monkeypatch.setattr(mod,"_validate_and_load",lambda *args:([],[],None,None,None))
    with pytest.raises(ValueError,match="document ID not found"):
        mod.build_review_payload(tmp_path,tmp_path,tmp_path,tmp_path,tmp_path,
                                 tmp_path,tmp_path,tmp_path,tmp_path,"phase_1:phase1:300")
