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
reviewer opinions, `review_state` and `review_flags`. A present but empty
reviewed field **does not fall back** to the original value. These flags do not
imply rejected annotations. An adjudication protocol is required before
creating supervised targets.

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
agreement or disagreement. Any explicit disagreement remains available for provenance, but the
evaluator-corrected values are final for Phase 1; no additional human
adjudication is required. The audit excludes incomplete or technically invalid
records conservatively and preserves every original row. No original data
are deleted.
