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

## Audit JSON compatibility (v1.1.0)

The `audit_summary.json` field `unknown_label_counts` is a **list of
records** rather than a map keyed by source label:

```json
"unknown_label_counts": [
  {"label": "SIM", "count": 1},
  {"label": "sim", "count": 1}
]
```

This preserves source case exactly and is compatible with Windows PowerShell
`ConvertFrom-Json`, which otherwise reports duplicate keys for `SIM`
and `sim`. `audit_schema_version` tracks this output-contract change;
the input `schema_version` and taxonomy are unchanged.

After pulling, re-run **only** `python -m legal_nlp.audit` if
`annotations.jsonl` was produced with the current importer's field schema.
In Windows PowerShell:

```powershell
$report = Get-Content data/interim/phase_1/audit/audit_summary.json -Raw |
    ConvertFrom-Json
$report | Select-Object supervised_annotation_count, supervised_excluded_count
$report.unknown_label_counts | Format-Table
```

## Confirmed-original recovery / conflict exclusion (Phase 1)

**Updated rule:** `concorda_* = SIM` explicitly confirms the original
`label`, `start`, and `end_exclusive` when the evaluator has not entered
a correction. Consequently, **empty reviewed columns do not by themselves
mean the annotation was rejected**.

Selection hierarchy per source annotation:

1. All four reviewed fields populated: use evaluator-corrected values
   (`target_selection_status=reviewed_final`), including records previously
   marked `NÃO`. Technical validation still applies.
2. All four reviewed fields empty, at least one explicit `SIM`, and **no**
   explicit `NÃO`: use the original fields
   (`target_selection_status=original_confirmed_by_reviewers`), provided
   original target fields exist and validation succeeds.
3. All four reviewed fields empty with both `SIM` and `NÃO`:
   `conflicting_votes_without_correction`; exclude from supervision.
4. All four reviewed fields empty with `NÃO` and no `SIM`:
   `disagreement_without_correction`; exclude.
5. All four reviewed fields empty with no recorded evaluations:
   `no_evaluation_no_correction`; exclude.
6. Incomplete reviewed values (neither all present nor all empty):
   `incomplete_reviewed_fields`; exclude conservatively; do not
   create a hybrid original/revised annotation.

The selected values always undergo document, label, offset and text-integrity
validation. For accepted originals, `field_selection_source` records
`original_confirmed`, and the supervised view records
`source_of_truth=original_confirmed_by_reviewers`.

The diagnostic audit records `target_selection_status_counts` and
`NO_VALIDATED_TARGET_SELECTION` for ineligible records. **No LLM adjudication
or new human review** is run. Raw rows, reviews and original values remain
unchanged. Contradictory evaluations without a complete corrected annotation
are treated as errors for the consolidated training data.

For the user's prior breakdown of 141 all-blank rows, five had only positive
recorded votes and are candidates for re-entry, subject to technical validation.
The other 136 lacked an unambiguous original confirmation under this rule.
Numbers must be recalculated after re-ingestion.

**This section supersedes earlier blanket statements** that every blank
reviewed field is excluded or that only fully populated reviewed rows can
be part of the supervised view.


## Phase 1 deterministic sanitization (separate from ingestion/audit)

Run after ingestion and audit:

    python -m legal_nlp.sanitization --dataset data/interim/phase_1 --output data/interim/phase_1/sanitized

Implementation: src/legal_nlp/sanitization.py.
Versioned rules: configs/sanitization_rules.json.

Four local-only outputs:

- sanitized_annotations.jsonl: all previously valid spans plus newly recovered
  ones; one row per source annotation; no deduplication or overlap pruning.
- sanitization_actions.jsonl: successful, atomic, per-field transformations with
  original and resulting values, original row and rule ID.
- sanitization_exclusions.jsonl: one row for every source annotation still not
  eligible, with explicit reasons and original technical issues.
- sanitization_summary.json: input/baseline/final counts, net new eligible spans,
  transformation counts, exclusion reasons and task counts.

Only the following transformations are allowed:

1. Missing source document ID: recover only if exact original excerpt matches
   the same start/end offsets in exactly **one** source document. A malformed or
   nonempty unresolved source ID never triggers candidate guessing.
2. Unknown label: apply only explicitly enumerated lexical aliases in
   configs/sanitization_rules.json, checked against canonical labels.
   ENT_JUR_DECISAO is intentionally **not** mapped.
3. Text mismatch: accept **case-only** differences, retaining original
   character boundaries and recording the original and document-derived text.
   Whitespace differences and other mismatch classes remain excluded.

All recovered spans undergo joint validation of selected review state,
document identity, canonical label, integer offsets, document bounds and
permitted text equivalence. Recovery is atomic: a partially repaired row stays
excluded, and no failed action appears among successful transformations.

Rows with conflicting evaluator votes and no final corrected annotation
(e.g., CSV lines 946 and 991), unresolved evaluation, or incomplete reviewed
fields never enter the sanitized supervision. The previously discussed line
1910 remains excluded unless its mismatch is independently proven to be only
a case difference; no offset adjustment is allowed. The rules do not rely on
an LLM, a second reviewer pass or majority voting.

This view is **not** the model-ready gold set: duplicate labels across
annotators, overlaps, document-grouped evaluation folds and token alignment
are subsequent explicit phases. No actual TJSP text or source data is
committed to the public repository.


## Post-sanitization span diagnostics (read-only)

After successful sanitization, execute:

    python -m legal_nlp.span_diagnostics --input data/interim/phase_1/sanitized/sanitized_annotations.jsonl --output data/interim/phase_1/span_diagnostics

Outputs (all local, no private judicial text in Git):

- exact_duplicate_groups.jsonl: document+task+offset+label groups with
  multiple annotation records, original row numbers and annotator IDs.
- same_span_label_conflicts.jsonl: identical document/task/start/end
  boundaries assigned distinct labels, with separate source-row evidence.
- within_task_overlap_pairs.jsonl: unique labeled spans with intersecting
  intervals, classified as nested or crossing; pairs are reported once,
  independent of duplicate annotation multiplicity.
- span_diagnostics_summary.json: per-task and overall counts.

NER and SEG are analyzed **separately**. Cross-task nesting (e.g., an
entity inside an argumentative segment) is expected and is not an error.
These are diagnostic candidate conflicts, not automatically invalid spans.
The tool neither drops duplicate annotations nor chooses labels or resolves
overlaps. Dataset preparation, annotator reconciliation and document-grouped
cross-validation require a separate explicit policy.

## Near-identical boundaries in span-based annotation (diagnostics v1.1.0)

Both NER and SEG use span-based annotations, not BIO token tagging. Overlaps,
nesting, shared boundaries and different labels are not automatically errors.

A candidate in near_boundary_candidates.jsonl must satisfy ALL of:
- Same document and task (NER vs SEG remain separate);
- Absolute start delta <= 10 characters, inclusive;
- Absolute exclusive-end delta <= 10 characters, inclusive;
- Positive text intersection (at least one shared character);
- Not an exact duplicate with the same label.

Both offset conditions are mandatory regardless of labels. The intersection
condition avoids flagging short but disjoint, nearby entities. Labels may
match or differ, and candidates are not grouped transitively.

Candidates are classified as identical_offsets_different_label,
near_boundaries_same_label, or near_boundaries_different_label, with
signed offset deltas, source rows, annotation IDs and annotator provenance.
These are diagnostic candidates, not confirmed errors or removal directives.

Command: python -m legal_nlp.span_diagnostics --boundary-tolerance 10

Existing overlap counts remain descriptive, never error counts. The summary
now includes boundary_candidate_pairs and a per-task category breakdown.
No supervised annotations, offsets or raw inputs are changed.

## Explicit evaluator labels and near-boundary different-label candidates

Use src/legal_nlp/reviewer_priority.py to inspect different-label
near-boundary candidate pairs against the original ingestion provenance.
The evaluator's final corrected label always supersedes that same source
annotation's original label. A `reviewed_final` value is not itself proof
of a CHANGED label; compare fields_original.label with fields_revised.label.

Run:

    python -m legal_nlp.reviewer_priority --annotations data/interim/phase_1/annotations.jsonl --candidates data/interim/phase_1/span_diagnostics/near_boundary_candidates.jsonl --output data/interim/phase_1/reviewer_priority

Outputs:
- different_label_review_evidence.jsonl: one row per different-label
  candidate pair, with original and evaluator-revised label, source row,
  reviewer status and correction evidence for each source annotation.
- review_priority_summary.json: counts by task, boundary category, and
  whether one, both, or neither side has an explicit label change.

If a candidate spans two INDEPENDENT final annotations, even a change
on only one side does not automatically invalidate the other annotation.
Different labels and nearly identical offsets can be valid multilabel spans.
Both stay in sanitized supervision. The tool records the provenance and
priority evidence but DOES NOT discard spans, infer reviewer intent,
vote between annotators, or apply BIO conversion.

Do not interpret the 76 different-label candidate pairs as 76 errors.

## Phase 1 logical-span grouping (lossless)

After reviewer-priority diagnosis, grouping for eventual span-based training
uses EXACT equality on (document_id, task, start, end, label). Different
labels on identical offsets remain separate. Same-label boundaries within
+/-10 remain separate; they are NOT automatically snapped or merged.

Run:

    python -m legal_nlp.logical_spans --sanitized data/interim/phase_1/sanitized/sanitized_annotations.jsonl --annotations data/interim/phase_1/annotations.jsonl --output data/interim/phase_1/logical_spans

Output logical_spans.jsonl includes a deterministic ID for each logical
span, its document/task/label/offsets, all source annotation IDs and rows,
annotator IDs, selection status, original/revised labels, reviewer counts,
and sanitization provenance. It does not modify source CSVs, ingest files,
or the sanitized annotation view.

logical_spans_summary.json includes the number of unique labeled spans,
input annotations, exact duplicates grouped, and per-task counts.
All final evaluator-reviewed fields remain authoritative per source record.
This is a non-destructive LOGICAL VIEW, not adjudication or a model-ready
train/validation split. BIO conversion and overlap pruning are prohibited.

## Document-aligned span dataset and 5-fold cross-validation (Phase 1)

The read-only preparation step consumes documents.jsonl and
logical_spans/logical_spans.jsonl. Run:

    python -m legal_nlp.document_dataset --documents data/interim/phase_1/documents.jsonl --logical-spans data/interim/phase_1/logical_spans/logical_spans.jsonl --output data/interim/phase_1/document_dataset --folds 5 --seed 42

Local output files:
- document_spans.jsonl: full original document text and both NER/SEG
  logical-span arrays, with original character offsets and provenance;
- document_folds.json: for each fold, disjoint train/validation document IDs;
- document_dataset_summary.json: input counts, fold sizes, and label coverage.

With 25 documents and 5 folds, validation comprises 5 complete documents
per fold and training comprises 20; every document validates exactly once.
Assignment is deterministic and order-independent with a seed and
SHA-256 sorting. This is NOT label stratification; inspect per-fold
label coverage before choosing an evaluation protocol.

Preflight checks fail closed on duplicate document IDs, duplicate text hashes,
repeated nonempty decision IDs (idacordao), invalid text hashes, unknown
document references, invalid span offsets, duplicate logical-span keys or
IDs, and missing/inconsistent source provenance.

IMPORTANT: document_id and idacordao identify documents/decisions, NOT
necessarily the underlying judicial proceeding. Multiple distinct acórdãos
from the same case could leak procedural content between folds. Process-level
grouping remains unresolved unless an authoritative process identifier
is supplied. Therefore these folds are document-disjoint, NOT claimed
process-disjoint. No independent test set has been reserved yet.

No source text is committed to Git. No BIO conversion, label arbitration,
forced flattening, model training or data deletion occurs in this step.
