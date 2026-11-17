# Augmentation pipeline

**Stage:** 2 — Dataset assembly  
**Status:** planned  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Applies training-only transforms to frames **after** splits exist: mild geometric scale, colour/brightness jitter, and (with quality tiers on disk) **random full vs low (CRF 45)** per example rather than using both (D04).

## Why we need it

Personal and public clips won’t cover every compression/lighting condition. Augmentation is how we buy robustness without collecting infinite data — and the proposal explicitly bans HUD-breaking flips.

## Inputs / outputs

| | |
|---|---|
| **In** | Train-split frames only |
| **Out** | On-the-fly tensors during training and/or cached augmented copies |

## Known design choices (from proposal)

- Mild scale: **10–20% zoom/rescale**
- Colour / brightness jitter
- **No horizontal flips** (mirrors HUDs)
- **Quality tier (D04):** each train example uses **either** full **or** low (CRF 45), chosen at random — not both. Small model-size Δ does not justify 2× samples.
- Must not let train-only randomness change val/test: eval runs fixed **full** and **low** passes

## Undecided / blank

- **Stack:** torchvision / albumentations / custom — TBD
- **Online vs offline augmentation**
- **Architecture:** —

## Implementation notes

-

## Acceptance checks

- [ ] Val/test pipelines apply **no** random train aug
- [ ] Spot-check: HUD left/right orientation preserved (no flips)
- [ ] Low-bitrate branch actually fires on ~30–50% of train samples

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Train transform pipeline includes jitter/scale; **val/test pipeline identity** (or resize-only); horizontal flip **not** in transform list; with fixed seed, low-bitrate flag True on ~30–50% of N synthetic calls (statistical or mocked RNG) |
| **System** | One batch through train dataloader → tensor shape `[B,3,144,256]` (or H×W as locked); values in expected range |
| **Manual** | Save a few augmented images; confirm HUD not mirrored |

**How to run:** `pytest tests/unit/test_augmentation.py tests/system/test_augmentation.py`

## Ties to proposal

Data Processing — Augmentation and quality robustness.
