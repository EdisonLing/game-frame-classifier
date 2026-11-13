# Clip tagger (optional demo)

**Stage:** 7 — deferred; not required for frame-classification milestones  
**Status:** deferred  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

For a longer clip or VOD: sample frames on an interval, run the **already trained** frame classifier on each, then aggregate with deterministic rules (e.g. majority vote per interval, optional unknown if confidence is low).

## Why it exists (and why it is not Stage 1–5 work)

This is an **application** of frame classification, not a different model. No architecture change, no extra training objective — just repeated inference + aggregation. Correct to focus APS360 effort on single-frame accuracy first.

## Inputs / outputs

| | |
|---|---|
| **In** | Video path + trained frame model |
| **Out** | Per-interval or whole-clip game tag (+ optional confidence / unknown) |

## Known design choices (from proposal)

- Sample frames at intervals; majority vote labels single-game intervals
- Max-prob below a val-tuned threshold → **unknown**

## Undecided / blank

- **Stack:** —
- **Interval length / vote window**
- **Architecture:** N/A (orchestration only)

## Implementation notes

- Reuse [frame extractor](frame-extractor.md) sampling logic; do not reimplement ffmpeg ad hoc

## Acceptance checks

- [ ] Same model weights as frame eval
- [ ] Output deterministic given seed/interval settings
- [ ] Unknown path works when threshold enabled

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Majority vote on a fixed list of labels → expected tag; ties broken by documented rule; all-below-threshold → unknown |
| **System** | Mock frame model returning scripted preds over a synthetic clip timeline → interval tags match; deterministic with fixed interval |
| **Manual** | Optional demo on one personal clip after model exists |

**How to run:** `pytest tests/unit/test_clip_tagger.py tests/system/test_clip_tagger.py`

## Ties to proposal

Introduction “additional application”; Architecture inference paragraph.
