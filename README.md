# Legal NER & Segmentation

Research software for named entity recognition (NER) and structural segmentation of Portuguese judicial decisions.

## Scope

The first milestone implements **lossless ingestion** of Phase 1 (25 annotated decisions). This milestone does not train models, remove overlaps, apply majority voting, or exclude rare classes. Its canonical annotations are later shared by NER and segmentation, including Phase 2 when available.

## Local setup (Python 3.11+)

```bash
python -m venv .venv
# Activate your virtual environment, then:
python -m pip install -e '.[dev]'
pytest -q
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and install using `python -m pip install -e ".[dev]"`.

## Import Phase 1 locally

Place the private documents and source annotations under `data/raw/phase_1/` (not tracked in Git). Export them as CSV or XLSX. The expected columns are documented in [the data contract](docs/data_contract.md).

```bash
legal-nlp-ingest-phase1 \
  --texts data/raw/phase_1/dados.csv \
  --annotations data/raw/phase_1/spans_consolidados_agrupado_atual.csv \
  --output data/interim/phase_1
```

The importer outputs `documents.jsonl`, `annotations.jsonl`, `validation_issues.jsonl`, and `dataset_manifest.json`. Validate the generated report before converting annotations to supervised targets.

## Data protection

**This repository is public.** Never commit judicial decisions, raw individual annotations, derived text-containing datasets, trained model weights, or MLflow runs. The `.gitignore` excludes the associated local folders.

## Development

Feature branches and pull requests are used for review. No merge into `main` without explicit authorization.

## Phase 1 audit (local)

After importing the private data, run:

```powershell
python -m legal_nlp.audit --dataset data/interim/phase_1 --output data/interim/phase_1/audit
Get-Content data/interim/phase_1/audit/audit_summary.json
```

The audit produces `audit_summary.json` and `review_queue.jsonl`.
It counts unknown labels, invalid offsets, unresolved document references and
text mismatches. For unlinked records, it proposes document candidates **only
when both the span text and its original character offsets match exactly**.
Candidates are not assigned automatically. The review queue contains
identifiers and diagnostics; no judicial text or full excerpts are included.

The importer retains all original/review columns in the **local**
`annotations.jsonl`, with `fields_original`, `fields_revised`, individual
reviewer opinions, `review_state` and `review_flags`. When all reviewed fields are empty, the original is used **only if** at
least one reviewer explicitly said `SIM` and nobody said `NÃO`; conflicts
or absent votes are not imputed. A complete evaluator correction is always
authoritative, and incomplete corrections are not mixed with originals. No
additional human adjudication or LLM resolution is used.

After pulling the latest branch, **rerun ingestion before running the audit**:
old `annotations.jsonl` files do not contain the new review provenance fields.
The audit also writes `unknown_labels_review.jsonl` with manual taxonomy
proposals. See [the legacy analysis](docs/legacy_preprocessing_audit.md).

## Confirmed taxonomy and evaluation protocol

The canonical label schema (configs/labels.json v1.1.0) has **54 ENT + 13 SEG**
labels. The two decision-vote segmentation categories are retained across
Phase 1 and Phase 2.

Evaluation coverage varies by original annotator. A blank `concorda_*` cell
means that reviewer did **not record an evaluation**; it cannot be counted as
agreement or disagreement. Disagreements remain available for provenance, and complete
evaluator-corrected values are final for Phase 1. Conflicting reviews without
a complete correction are excluded from the supervised view. The audit excludes incomplete or technically invalid
records conservatively and preserves every original row. No original data
are deleted.


## Phase 1 deterministic sanitization

After ingesting and auditing private input files, run:

~~~powershell
python -m legal_nlp.sanitization --dataset data/interim/phase_1 --output data/interim/phase_1/sanitized
Get-Content data/interim/phase_1/sanitized/sanitization_summary.json
~~~

Outputs remain local/ignored: sanitized_annotations.jsonl,
sanitization_actions.jsonl, sanitization_exclusions.jsonl and
sanitization_summary.json. The stage uses only explicit lexical aliases,
unique exact document/excerpt/offset linkage, and case-only text equivalence.
It preserves evaluation conflicts as exclusions. No source data is changed,
no LLM is used, and there is no deduplication or overlap pruning. See
docs/data_contract.md for the complete contract.

## Span boundary diagnostics (+/-10 characters)

Both NER and SEG are trained as span-based tasks (not flat BIO).
Overlaps between different labels are allowed. To flag only nearly
coincident boundaries, run:

~~~powershell
python -m legal_nlp.span_diagnostics --input data/interim/phase_1/sanitized/sanitized_annotations.jsonl --output data/interim/phase_1/span_diagnostics --boundary-tolerance 10
~~~

The new near_boundary_candidates.jsonl report compares spans within the
same document and task regardless of label. Both start and end must differ
by at most 10 characters, and intervals must share a character. Exact
duplicates with identical labels stay in the separate duplicates report.
These are candidates for analysis, never automatically removed.

## Evaluator precedence for different-label near-boundary spans

To inspect the 76 observed pairs with different final labels, without
changing the span-based supervised view:

~~~powershell
python -m legal_nlp.reviewer_priority --annotations data/interim/phase_1/annotations.jsonl --candidates data/interim/phase_1/span_diagnostics/near_boundary_candidates.jsonl --output data/interim/phase_1/reviewer_priority
~~~

Review `review_priority_summary.json` and
`different_label_review_evidence.jsonl`. Corrections by evaluators override
the SAME annotation's original label. Two independent evaluated spans can
still legitimately have different labels; no winner is automatically selected.

## Lossless logical span grouping

After sanitization, consolidate only identical document/task/start/end/label
spans into a logical record with full reviewer and annotator provenance:

~~~powershell
python -m legal_nlp.logical_spans --sanitized data/interim/phase_1/sanitized/sanitized_annotations.jsonl --annotations data/interim/phase_1/annotations.jsonl --output data/interim/phase_1/logical_spans
~~~

Produces logical_spans.jsonl and logical_spans_summary.json locally. Different
labels and near-boundary alternatives are preserved; reviewer corrections
remain authoritative per source annotation. This is not a training split.

## Document-aligned span dataset and cross-validation folds

Build the local (not committed) dataset and deterministic five-fold
document-disjoint assignments after logical-span grouping:

~~~powershell
python -m legal_nlp.document_dataset --documents data/interim/phase_1/documents.jsonl --logical-spans data/interim/phase_1/logical_spans/logical_spans.jsonl --output data/interim/phase_1/document_dataset --folds 5 --seed 42
~~~

Outputs: document_spans.jsonl, document_folds.json,
document_dataset_summary.json. With the 25-document Phase 1 corpus,
each fold should use 20 complete training documents and 5 validation
documents. The split is deterministic but not label stratified. These
assignments are *document-disjoint*; because the dataset has no verified
process-level grouping identifier, they do NOT yet prove independence
between different judicial decisions in the same proceeding.
No separate held-out test set, BIO encoding, or model training is created.


## Planned final evaluation: 60 acórdãos

The current 25-document, five-fold split is provisional and useful only for
pipeline diagnostics. With 35 additional acórdãos, the planned protocol is
**48 development documents (25 existing + 23 new)** and **12 untouched test
documents selected from the 35 new**. Model selection uses five-fold
cross-validation on the 48 development documents, followed by training on
all 48 and one final evaluation on the frozen 12. The split must respect
judicial-process groups when they can be identified; its label distribution
and class rarity must be audited before freezing. No IDs have been assigned
or new data ingested yet. Details: [evaluation protocol](docs/evaluation_protocol_60.md).
