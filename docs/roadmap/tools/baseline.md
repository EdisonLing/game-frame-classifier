# Colour-histogram baseline

**Stage:** 4 — Baseline model  
**Status:** planned  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Reduces each frame to a colour histogram and trains a simple multinomial logistic regression to predict the game. Same splits as the CNN.

## Why we need it

Progress report **requires** a non-random baseline with quantitative and qualitative results. It also sets the bar the CNN must beat — especially on look-alike pairs (Overwatch 2 vs Marvel Rivals) where palette alone should struggle.

## Inputs / outputs

| | |
|---|---|
| **In** | Train/val/test frame manifests |
| **Out** | Fitted model + metrics + a few example predictions |

## Known design choices (from proposal)

- Feature: colour histogram, e.g. **16 bins per RGB channel**, concatenated
- Classifier: **multinomial logistic regression**
- Same splits as the primary model
- **Same tier assignment as the CNN (D04):** half full / half low (CRF 45) per slot, read from the split manifests
- Expectation: Minecraft-like distinct palettes easier; OW2 vs Marvel Rivals harder

## Undecided / blank

- **Stack:** scikit-learn is the obvious default — confirm when implementing
- **Histogram on raw vs resized frames**
- **Architecture:** N/A (non-deep)

## Implementation notes

-

## Acceptance checks

- [ ] Beats chance (~16.7% for 6 classes) on val
- [ ] Confusion matrix saved — look-alike pair visible
- [ ] At least one quantitative metric + one qualitative example for the progress report

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Histogram vector length = `3 * n_bins` (e.g. 48 for 16 bins); solid-color image → mass in expected bins; predict shape = n_classes probs/logits |
| **System** | Tiny synthetic dataset (e.g. 3 colors ↔ 3 fake “games”) → train logistic regression → accuracy ≫ chance on held-out same-color frames (sanity that wiring works) |
| **Manual / report** | Real val metrics + confusion matrix figure; qualitative Minecraft vs OW2/Rivals examples |

**How to run:** `pytest tests/unit/test_baseline.py tests/system/test_baseline.py`

## Ties to proposal

Baseline Model section; evaluation “CNN should clearly outperform the colour-histogram baseline.”
