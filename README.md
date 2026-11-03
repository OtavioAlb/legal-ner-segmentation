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
