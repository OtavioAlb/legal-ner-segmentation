# Phase 2 — read-only annotation audit

After merging both Label Studio evaluation projects and resolving reviewer
assignments locally, run:

```powershell
python -m legal_nlp.phase2_audit `
  --original "data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json" `
  --evaluations "data/interim/phase_2/merged_evaluations_resolved.json" `
  --labels "configs/labels.json" `
  --output "data/interim/phase_2/audit"
```

Outputs (private/local; ignored by Git):
- `audit_summary.json`: counts, coverage, label types and exact-span comparison statistics.
- `review_queue.jsonl`: technical exceptions and candidate issues without document excerpts.
- `span_comparisons.jsonl` and `span_comparisons.csv`: counts of identical, removed and added exact spans for NER and SEG separately.

Important limitations: these are diagnostics, not interannotator reliability
coefficients or adjudicated gold labels. The source files and offsets are never
changed; overlap/nesting across NER and SEG is permitted. A span is eligible for
comparison only when its offsets, canonical label and text match pass validation.
Thus comparisons can undercount changes involving technically invalid spans.
The tool does not infer that either reviewer or the annotator was correct.
User identity is verified against the local assignment mapping, not platform
account ownership. No source texts, personal identities or real decision IDs
are committed to this public repository.

Interpret `issue_counts` and the two comparison scopes separately before
deciding any sanitation or supervised-view policy.
