# Data contract — Phase 1 (initial)

## Scope

This ingestion layer imports all individual annotations, including duplicates,
unrecognized labels, invalid offsets and annotator disagreements. It does **not**
produce adjudicated training targets.

The reference label set comes from the supplied Label Studio XML specification:
54 ENT_ and 11 SEG_ labels (65 total).

## Required input

- Document table: \`id\` and \`text\` or \`acordao\`; optional \`idacordao\`.
- Annotation table: \`id_text\`, \`label_new\`, \`start_new\`,
  \`end_exclusive_new\`; optional \`annotator\`, \`span_text_new\`.

CSV and XLSX formats are accepted. XLSX requires \`openpyxl\`.

## Outputs

- \`documents.jsonl\`: immutable source text, identifiers, SHA-256, source row.
- \`annotations.jsonl\`: one record per source annotation, with original and
  canonical labels, original character offsets, annotator and technical issues.
- \`validation_issues.jsonl\`: a separate issue row for each detected problem.
- \`dataset_manifest.json\`: counts and hashes of inputs and configurations.

Offsets are character-based, with inclusive start and exclusive end.
Text is not normalized; offset matching is exact. Mismatches are flagged, never
silently trimmed or corrected. Rows with empty labels remain in the output.

## Future decisions

- Adjudication rules, overlaps, and incomplete annotation coverage.
- Cross-phase identity resolution and label taxonomy mapping.
- Split strategy grouped by judicial process and document.
- Preparation of NER and segmentation supervised datasets.

**No real judicial text or annotations should be committed to public Git.**
