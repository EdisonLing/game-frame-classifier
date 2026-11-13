# Dataset splitter

**Stage:** 2 — Dataset assembly  
**Status:** planned  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Assigns each **video/session** (not each frame) to train, validation, or test, then materializes frame lists / manifests for those splits. For personal clips, splits by session and holds some sessions out as a personal-clip test set.

## Why we need it

Frame-random splits leak near-duplicates from the same video into train and test — a failure mode called out for TwitchCategory in the proposal. Correct splits are required before baseline/CNN numbers mean anything, and the progress report asks for a plan to test on never-before-seen data.

## Inputs / outputs

| | |
|---|---|
| **In** | Clean frame manifest with video/session ids |
| **Out** | train / val / test manifests (+ optional personal-holdout test) |

## Known design choices (from proposal)

- Split **by video**, not by frame ≈ **70 / 15 / 15**
- Test set should include **streamers unseen in training** (once public data exists)
- Personal clips: split by **session**, ≈ **60–70% train**, remainder held out as separate personal test set
- Augmentation only after splitting

## Undecided / blank

- **Stack:** —
- **Stratification:** how hard to balance games × channels inside each split
- **Personal holdout freeze policy** — **D13** in [design-decisions.md](../../design-decisions.md) (TA: keep untouched during development; leaning yes)
- **Seed / reproducibility file format**
- **Architecture:** —

## Implementation notes

-

## Acceptance checks

- [ ] No video/session id appears in more than one split
- [ ] Per-split class counts are sane (not empty classes)
- [ ] Personal holdout sessions fully excluded from train
- [ ] Can regenerate splits from a seed

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Fake manifest with multiple frames per session → **no session id** in more than one split; same seed → identical assignment; different seed → (usually) different; personal holdout ids absent from train/val; empty-class guard or explicit warning |
| **System** | Write temp manifests → run splitter CLI/API → reload train/val/test files and assert disjoint session sets |
| **Manual** | Print per-game counts per split before first model train |

**How to run:** `pytest tests/unit/test_dataset_splitter.py tests/system/test_dataset_splitter.py`

**Critical property:** leakage test (same `session_id` / `video_id` across splits) must always stay green.

## Ties to proposal

Data Processing — Splits paragraph; related-work contrast with random frame splits.
