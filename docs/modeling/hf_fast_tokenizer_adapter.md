# Hugging Face fast-tokenizer adapter — synthetic validation

**Status:** design-only. No training, adjudication, model weights, private
judicial text, or promotion of a diagnostic snapshot to gold.

## Scope

This branch extends the existing BILOU and window-planning contracts in
`src/legal_nlp/modeling/token_alignment.py` without changing that module.

- `tokenize_document` uses a fast Hugging Face tokenizer on the *whole*
  original text, with no normalization by our pipeline, truncation, or
  special tokens; collects source-text character offsets.
- `project_bilou` operates globally, before chunking. Unsupported
  annotations (overlap, nesting, nonaligned endpoints) fail explicitly.
- `encode_windows` introduces model-specific special tokens and builds
  masks. Each source subtoken is assigned to **one** training-loss window.
  Repeated context positions are masked from loss.
- `stitch_window_tags` joins predicted BILOU tags by deterministic
  token ownership. It is an initial reference decoder, not a substitute
  for structured decoding or logit aggregation.
- `decode_bilou` reconstructs canonical `[start,end)` intervals.
  Invalid transitions fail explicitly instead of being repaired silently.
- Empty/special/unrepresentable tokenizer intervals are rejected. This
  conservative policy must be studied using the actual five tokenizers.
  It must not be bypassed by boundary snapping or dropping spans.

**Known limitation:** Reassembling independently predicted window labels
can yield invalid global BILOU sequences, even when every window has a
unique loss owner. We explicitly fail on invalid transitions. A future
modeling PR will evaluate constrained decoding and logit aggregation.
This branch is infrastructure only.

## Run synthetic tests (no Transformers installation needed)

```powershell
git fetch origin
git switch feat/hf-fast-tokenizer-adapter
git pull --ff-only
python -m pytest tests/unit/test_hf_tokenizer_adapter.py -v
python -m pytest -q
```

## Run real fast-tokenizer smoke test (synthetic text only)

```powershell
python -m pip install -e ".[dev,tokenization]"
python -m legal_nlp.modeling.tokenizer_smoke --allow-download
```

The smoke test loads the tokenizer configuration only for the five
checkpoints listed in `configs/model_experiments.v1.json`. It does not
download model weights or access corpus files. It prints per-checkpoint
status, token counts and window counts without source text.

If files are cached locally, omit `--allow-download`; by default
`local_files_only=True`. The smoke command exits nonzero on any
failure. Check checkpoint trust/dependency/runtime requirements separately
before proceeding to model training. No training is authorized.

## Research and evaluation caveats

The five-tokenizer smoke test uses one short synthetic sentence. Passing
it is **not proof** that all 60 judgments, all 67 labels, extremely long
segments, whitespace, apostrophes, accents, emoji, and different types of
nested regions are tokenizable without mismatches. A later, read-only local
diagnostic should collect only counts of unrepresentable offsets, never
raw judicial excerpts or personal annotations. Such diagnostics are not
supervised training.

Comparison of five encoders initially controls window length at 512
tokens. Longer contexts are a separate experiment to avoid confounding.
