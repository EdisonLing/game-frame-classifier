# CNN trainer

**Stage:** 5 — Primary model  
**Status:** planned  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Trains and evaluates the from-scratch CNN that maps a 256×144 RGB frame to a 6-way game prediction (optional later: low-confidence → “unknown”).

## Why we need it

This is the graded primary model. Progress report needs an architecture description more detailed than the proposal, rough complexity (layers / params), and at least one quantitative + qualitative result showing feasibility.

## Inputs / outputs

| | |
|---|---|
| **In** | Split manifests + augmentation pipeline |
| **Out** | Checkpoints, training curves, metrics, sample predictions |

## Known design choices (from proposal)

- Input: **256×144** RGB
- From scratch (random init), **not** pretrained backbone (for the primary story)
- Four conv blocks: 3×3 conv → BatchNorm → ReLU → 2×2 max pool; channels **32–256**
- Flatten → 1–2 FC layers + dropout → softmax over 6 games
- Loss: cross-entropy; optim: Adam; hparams tuned on val
- Planned experiment: **flatten vs global average pooling**
- Later: confidence threshold → “unknown”; majority vote is **inference glue**, not this trainer — see [clip-tagger.md](clip-tagger.md)

## Undecided / blank

- **Stack:** PyTorch (course standard) — confirm env
- **Exact channel widths / FC sizes / dropout / LR / batch size** — **D16** in [design-decisions.md](../../design-decisions.md); TA notes flatten 16×9×256 ≈ 37k features into first FC
- **Flatten vs GAP** — **D16b**
- **Two-stream HUD crops** — **D15** (TA suggestion; **open, not default**)
- **Training hardware** (Colab vs local GPU/CPU) — **D23**
- **Logging:** TensorBoard / CSV / notebook-only
- **Architecture diagram:** refine for progress report — **D10**

## Implementation notes

- Progress report bar: “someone can reproduce a model like yours that will perform similarly” — log hparams with checkpoints

## Acceptance checks (progress report)

- [ ] Train/val curves plotted
- [ ] Val accuracy / F1 reported
- [ ] Qualitative: correct vs failure examples (esp. look-alikes)
- [ ] Rough param count known
- [ ] Challenges noted

## Acceptance checks (final report extras)

- [ ] Unseen-streamer + personal-clip test breakdowns
- [ ] Quality-tier eval (full vs low CRF 45; D04)
- [ ] Confusion matrix emphasis on OW2 vs Marvel Rivals
- [ ] Optional unknown threshold

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Forward pass on random `1×3×144×256` tensor → logits shape `[1,6]`; param count matches locked D16; unknown threshold maps low-max-prob → unknown class/flag |
| **System** | Overfit test: tiny dataset (few images, 2–3 classes) for a few epochs → train accuracy → ~1.0 (proves train loop, loss, optimizer wiring); skip if no torch |
| **Manual / report** | Real curves, val metrics, failure cases — not asserted in pytest |

**How to run:** `pytest tests/unit/test_cnn_trainer.py tests/system/test_cnn_trainer.py`

## Ties to proposal

Architecture + Evaluation sections.
