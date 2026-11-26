# Phase 2: conservative triage of new region IDs

The 35 original documents are distinct. A region ID is scoped by
`idacordao`; compare original regions with each project's evaluation,
not across unrelated decisions.

Run after normalizing literal escape sequences:

```powershell
python -m legal_nlp.phase2_new_region_triage `
  --original "data/interim/phase_2/normalized/original_normalized.json" `
  --evaluations "data/interim/phase_2/normalized/evaluations_normalized.json" `
  --output "data/interim/phase_2/new_region_triage"
```

Outputs are private local files:
- `triage_summary.json` aggregates explicit-new comments and replacement
  candidate evidence separately by project.
- `new_regions_triage.jsonl` provides region-level details with candidate
  original IDs. No comments or document text are written.
- `new_regions_exact_crossreview.jsonl` lists uniquely matching new
  region label+offset signatures across the two review projects.
- `ambiguous_crossreview_signatures.jsonl` flags repeated signatures
  that cannot safely be paired.

A new region with an explicit "nova anotação" comment remains reviewer
evidence of an intended addition even when its span overlaps an old
region. Overlap alone does not mean a corrected old region. Lack of
this comment in project 11 is not evidence of no new annotation.

The tool is diagnostic only: it never rewrites offsets, removes labels,
declares agreement based on an absent checkbox, or selects a gold
annotation. Keep all outputs under ignored local paths, not GitHub.
