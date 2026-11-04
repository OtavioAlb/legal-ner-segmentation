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

## CSV encodings

The importer reads CSV files as UTF-8 (including BOM) when possible. If UTF-8
decoding fails, it attempts Windows-1252 and then ISO-8859-1. This is a
best-effort fallback, **not a definitive encoding detector**. Each input's
selected encoding is recorded in `dataset_manifest.json`.

Use `--annotations-encoding cp1252` (or `--texts-encoding cp1252`) to
override detection. All decoding is strict (no replacement characters).
If an input is incorrectly decoded but remains valid text, inspect the
source file and override its encoding rather than modifying the original.
Text is never normalized; offsets remain relative to the decoded source.
