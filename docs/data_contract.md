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

## Phase 1 document identifiers

CSV exports sometimes encode integer document IDs as decimal strings (for
example, `290.0` in annotations and `290` in the documents file).
The importer normalizes only unsigned integer identifiers ending in a
decimal point followed exclusively by zeros. The original ID and the
normalized ID are both retained in the output.

The normalizer **does not** discard leading zeros or coerce arbitrary IDs to
floating point. A normalized key that maps to more than one source document
is marked ambiguous rather than silently assigned to one document.

`dataset_manifest.json` now includes `document_linkage`, with counts of
matched annotations, links requiring normalization, unmatched IDs and
ambiguous IDs. Missing associations are preserved in `annotations.jsonl`
and reported as issues, including original source identifiers.

Matching a document does not imply the annotation is valid: verify offsets,
text correspondence and label taxonomy after linkage is repaired.

## Review-aware source fields (Phase 1 v0.2)

The authoritative candidate for each field is its reviewed column
(`label_new`, `start_new`, `end_exclusive_new`, `span_text_new`),
when that column exists. A present-but-blank reviewed field stays
`null` in the selected candidate, even if the original has a value.

Each annotation retains:

- `fields_original`: pre-review label, start, end, span text.
- `fields_revised`: reviewed label, start, end, span text.
- `field_selection_source`: one provenance key per field.
- `review_state`: `revised_complete`, `revised_incomplete`,
  `revised_all_empty`, or `no_complete_review_schema`.
- `review_flags`: original is populated but revised value is blank.
- `reviewer_opinions`: all available per-reviewer raw votes and comments.
- `source_fields`: complete original imported row, including extra columns.

The legacy `label_original` output field names the **selected pre-alias**
label; the actual pre-review label is `fields_original.label`.
Likewise, `start`, `end` and `span_text_source` describe the
selected candidate only.

A reviewed blank is **not** automatically a rejection: it requires
adjudication before training. Technical validation is separate from
review status.

## Local review audit

After re-running ingestion, execute:

```powershell
python -m legal_nlp.audit --dataset data/interim/phase_1 --output data/interim/phase_1/audit --labels configs/labels.json --aliases configs/label_aliases.json
```

Outputs:
- `audit_summary.json`: review states, reviewer vote categories, offset
  reasons, unknown-label frequencies/categories and document candidates.
- `review_queue.jsonl`: local pending decisions with issue reasons and
  exact-match candidate document IDs. **No edits** to source annotation IDs.
- `unknown_labels_review.jsonl`: label candidates only (no automatic mapping).

These reports stay local and are excluded from Git. Some original labels
contain free text rather than category codes; inspect locally before
sharing any report externally.

Do not interpret `annotations_without_issues` as the training set size:
records can be technically valid but unadjudicated.

## Segmentation taxonomy v1.1.0

The authoritative taxonomy now contains **67 labels (54 ENT and 13 SEG)**.
In addition to the 11 segmentation labels in the original Label Studio file,
`SEG_DECISAO_VOTO_VENCEDOR` and `SEG_DECISAO_VOTO_VENCIDO` are canonical,
based on explicit project confirmation. Both also belong to Phase 2.
They are distinct from `ENT_DECISAO_VOTO_VENCEDOR` and
`ENT_DECISAO_VOTO_VENCIDO`.

No other semantic label migration is approved by this change.

## Review protocol: evaluation coverage and correction tracking

The review design assigns reviewers to other annotators. Therefore only
**explicitly filled** `concorda_*` cells represent review observations.
Empty review cells mean **no assessment recorded**, not agreement, rejection,
or disagreement. Do not compute majority voting over all seven reviewers.

Vote interpretation:
- `SIM` (including case/whitespace variants) → `agree`
- `NÃO` / `NAO` (including case/whitespace variants) → `disagree`
- empty → `not_recorded`
- other cell contents → `other_not_interpreted` pending verification

Each `reviewer_opinions` entry contains `status`,
`agreement_raw` and `comment_raw`.

**Explicit disagreement requires examination of a correction:** the reviewer
may have corrected the label/entity/segment, changed offsets, or introduced a
separate annotation. `changed_review_fields` lists differences between
original and revised values (label, start, end, span_text).
`correction_status` distinguishes:

- `revised_fields_differ_pending_verification`: differences exist; this
  alone does not prove that the correction satisfies the reviewers.
- `no_field_change_located`: disagreement without a difference in these
  fields; inspect comments and possible new annotation rows.
- `not_triggered_by_explicit_disagreement`: no explicit disagreement;
  this does **not** prove that the record was reviewed or approved.

The audit includes all explicitly disputed annotations in
`review_queue.jsonl`, even if no technical validation error exists. It
does not automatically link new annotations to disagreement records.

All records and reviewer comments remain in ignored local datasets.

## Phase 1 final evaluator corrections (supersedes previous adjudication gate)

**Final policy confirmed by the project owner:** the values in `label_new`,
`start_new`, `end_exclusive_new` and `span_text_new` are the evaluator-corrected
source of truth. No further human adjudication will be performed for Phase 1.
An explicit disagreement does not veto a complete, technically valid corrected
annotation; unchanged revised values are also used as delivered.

Empty revised fields are never silently replaced by original values. Records
with incomplete revised fields, unknown labels, unresolved document identity,
invalid offsets or mismatching excerpts are **conservatively excluded from the
supervised view**, while all 5,295 source rows remain preserved in
`annotations.jsonl`. Exclusion is a technical selection decision, not a claim
that the evaluator rejected the original span. Only deterministic and verifiable
remediation can change technical eligibility.

After re-ingestion and audit, the local files include:
- `audit/supervised_annotations.jsonl`: complete validated corrected spans
  with canonical label, document, offsets, task and original annotation ID.
- `audit/supervised_exclusions.jsonl`: every excluded source annotation and
  its explicit reasons (no data deleted).
- `audit/review_queue.jsonl`: **diagnostic exceptions**, not a human
  adjudication queue; `resolution_status` distinguishes records usable in
  the final reviewed view from technical exceptions.
- `audit/audit_summary.json`: `supervised_annotation_count`,
  `supervised_excluded_count` and reason counts.

The supervised view is **not yet a model-ready NER/SEG dataset**: it has not
resolved cross-annotator duplicates, overlapping spans, document-grouped splits
or token-label encoding. Those transformations are separate later stages.

The older terminology `pending_manual_review` and `manual_review_queue_count`
has been superseded. No further manual adjudication is required.
