# ADR-0001 — Lossless ingestion before model-specific preprocessing

Status: proposed

We will first create a canonical, provenance-preserving representation of all
annotation records across Phase 1 and Phase 2. NER and structural segmentation
will consume derived supervised views of the same document text.

This pipeline will not apply minimum frequency filters, majority vote,
shortest-span overlap removal, token labeling or sliding-window decisions.
These belong to later adjudication and model preparation stages.

Reason: avoid reproducing irreversible data loss and confounded evaluations
from the previous implementation. The earlier code and MLflow runs are historical
references, not the source of truth for the new dataset.
