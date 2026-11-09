# Phase 2: ID-first semantic review audit

Phase 2 contains 35 distinct original decisions. Each original region has
an ID scoped to its decision; each decision has one or two reviewer records.
Unlike Phase 1, different original annotators did not annotate the same 25
decisions.

A review links `labels`, `choices` and `textarea` by identical
`result.id`. It must NOT be compared by array position. The region's
`id` is the first alignment key, with label and offsets as observed
properties, not the identity key.

```powershell
python -m legal_nlp.phase2_semantic_audit `
  --original "data/interim/phase_2/normalized/original_normalized.json" `
  --evaluations "data/interim/phase_2/normalized/evaluations_normalized.json" `
  --output "data/interim/phase_2/semantic_audit"
```

Local outputs:
- `semantic_audit_summary.json`: choice, change and review comparison totals
- `region_decisions.jsonl`: one observed region per review with source ID,
  reviewed label/offset, checkbox outcome and comment-presence markers
- `reviewer_comparisons.jsonl`: original-region-ID aligned reviews for
  the same acórdão, only when two reviews exist
- `review_queue.jsonl`: possible inconsistencies to inspect

Important: a new region ID is not necessarily a new annotation. It may be
a recreated replacement for a prior region. A missing original ID is not
proof of deletion intent. A marked `Limite impreciso` without offset changes
under the same ID must be investigated, not treated as implicitly corrected.
Likewise, disagreement in checkbox values may coexist with identical
labels and offsets. The implementation does NOT adjudicate, discard,
automatically relink new regions or produce final supervised gold labels.

Outputs remain local and ignored. Do not commit real texts or personal names.
