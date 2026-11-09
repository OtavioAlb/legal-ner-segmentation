# Phase 2: deterministic missing-choice decisions and new-region comments

Only code and synthetic tests belong in this public repository. Store exports, judicial text, per-region reports and reviewer comments in ignored data/ folders.

## Step 1. Filter and classify missing checkboxes

Run from the repo root in PowerShell, after placing the 35-original annotations JSON and both current evaluation exports under data/raw/phase_2/:

    python -m legal_nlp.phase2_auto_review --original data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json --project-11 data/raw/phase_2/project-evaluation-1-at-2026-11-09-12-19-aa62bd8c.json --project-17 data/raw/phase_2/project-evaluation-2-at-2026-11-09-12-19-cf6d5b27.json --exclude-user-id 10 --output-dir data/interim/phase_2/automatic_review_2026-11-09

Matching by data.idacordao + region result.id, if a checkbox is absent: changed label -> incorreto_automatico (priority); unchanged label but changed offset -> limite_impreciso_automatico; unchanged label and offsets -> correto_automatico.

Human choices are never overwritten. Added choices carry origin=automatic-comparison. Compare original embedded predictions against the supplied original JSON before proceeding. New or removed IDs are pending. These are structural comparisons, not evidence of semantic correctness, human agreement or gold labels.

Private outputs: evaluations_filtered_automatic.json, automatic_decisions.csv, pending_manual_review.csv, removed_reviewer_records.json, auto_review_summary.json.

## Step 2. Triage reviewer observations for new region IDs

    python -m legal_nlp.phase2_new_region_comments --evaluations data/interim/phase_2/automatic_review_2026-11-09/evaluations_filtered_automatic.json --output data/interim/phase_2/new_region_comments_2026-11-09

Comments declaring nova anotação are retained as reviewer evidence. Similar variants are tracked separately. Structural warnings cover exact duplicates with original IDs, same boundaries with other labels, duplicates within the review and same-label overlaps with IoU >= 0.8. Different labels on the same offsets can be legitimate NER/SEG overlaps.

Outputs: triage_summary.json, new_regions_triage.jsonl and missing_originals_triage.jsonl; all local/ignored. No automatic adjudication of new IDs or removed IDs.

## Validated data snapshot: 2026-11-09

35 documents; 70 initial reviews -> 60 after excluding reviewer ID 10 (Teresa); 2,369 human decisions retained; 143 automatic (142 unchanged, 1 changed label, 0 offset-only); 282 new regions lacking choices; 22 missing original IDs.

For 282 new regions, 171 exact nova anotação comments; 49 variants; 62 without a comment. Triage: 167 explicit candidates; 47 variants; 35 structural warnings; 33 not confirmed. None promoted to gold.

Local tests: python -m pytest -q. No merge into main without explicit approval.
