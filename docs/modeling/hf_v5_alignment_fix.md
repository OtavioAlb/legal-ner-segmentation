# HF tokenizers v5: fast-tokenizer alignment fix

The real synthetic smoke test from 2026-11-26 failed for all five encoders
on Transformers 5.24.1 (the repository's previous mocks passed).
This branch fixes the adapter *without* changing any source annotations,
encoder choices, supervision readiness, or private documents.

## Confirmed diagnoses

- BERTimbau + RoBERTaLexPT: `prepare_for_model` is not available in v5.
- NorBERTo + moBERTo: byte-level token offsets include the whitespace
  immediately before `Código` ([9,16) for a span starting at character 10).
- XLM-R: there is a nonempty offset overlap early in the synthetic text;
  the actual target `Código Civil` remains exactly aligned.
- PyTorch not installed is not an obstacle for tokenizer-only smoke tests.

## Implemented policy

1. Probe two **synthetic strings** and require a fixed contiguous-content
   prefix/suffix special-token template; explicitly reject other templates.
   Insert the verified prefix/suffix IDs around each slice of unmodified
   global token IDs. This replaces the removed `prepare_for_model`.
2. Token offsets remain raw/unchanged. Intervals with overlapping ends are
   tolerated outside supervised regions if starts remain ordered. Within
   a supervised region, an overlap of non-whitespace characters is rejected
   as ambiguous.
3. Allow the leading portion of a token to extend before an annotation
   boundary **only when that prefix consists entirely of whitespace**.
   Original annotations are not moved, snapped, truncated or dropped.
4. `decode_bilou(..., source_text=original_text)` removes the leading
   whitespace from the *prediction boundary only*, after verifying the
   document SHA-256. Production callers must provide the source text.
   **Formal limitation:** BILOU cannot distinguish a gold span including a
   leading whitespace character from a span whose start excludes it when
   the tokenizer bundles that whitespace with the first word. Accordingly,
   `project_bilou` rejects source spans whose first character is whitespace,
   rather than allowing the decoder to shift their boundaries. This is an
   explicit unsupported case, not evidence that the gold is erroneous.
   These regions must remain in the canonical data and be handled by a
   compatible span/boundary model or adjudicated policy; do not relabel as `O`.
   Synthetic regression tests exercise spaces, newlines and long windows.
5. The `tokenizer_smoke` now uses this source-verified reconstruction.
6. No training, gold promotion, corpus rewrite, merging or model-weight load.

## Validate locally

```powershell
git fetch origin
git switch fix/hf-tokenizer-v5-alignment
git pull --ff-only

python -m pytest tests/unit/test_modeling_token_alignment.py -v
python -m pytest tests/unit/test_hf_tokenizer_adapter.py -v
python -m pytest -q

python -m legal_nlp.modeling.tokenizer_smoke
```

All five tokenizers should already be in the local Hugging Face cache.
If not, use `--allow-download` for tokenizer files only.
Test outcomes must be checked before any merge.

**Limitations:** One short synthetic smoke sentence does not demonstrate
alignment on all source offsets or all legal segments. Non-whitespace
overlapping offsets in supervised regions remain unsupported in the flat
BILOU path. Some true gold endpoints may not be representable by a
particular tokenizer; future read-only corpus diagnostics must quantify
this rather than silently alter target spans.

The special-token template strategy is constrained to the five configured
single-sequence encoders; if another checkpoint changes the post-processor,
a new compatibility test is mandatory. For sections extending across
windows, this is still only a token-based baseline; structured decoding
and full-section boundary analysis will be separate experiments.
