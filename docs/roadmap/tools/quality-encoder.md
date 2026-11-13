# Quality encoder

**Stage:** 1 — Personal-clip data tools  
**Status:** planned  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Re-encodes frames (or short clips) at controlled lower bitrates using ffmpeg CRF settings, producing medium/low quality variants of the same content.

## Why we need it

Real clips are messy: compression, Medal/GPU overlays, re-uploads. The proposal treats quality as a first-class axis:

1. **Train augmentation** — random low-bitrate re-encode on 30–50% of training frames  
2. **Eval** — same test frames scored at full / medium / low (CRF 0 / 28 / 38)

One shared tool keeps those CRF definitions consistent.

## Inputs / outputs

| | |
|---|---|
| **In** | Clean frames (or parent clips) + target CRF / quality tier |
| **Out** | Degraded copies + metadata noting quality tier |

## Known design choices (from proposal)

- Tooling: **ffmpeg**
- Augmentation CRF range: **28–40** on **30–50%** of train frames (applied in [augmentation](augmentation.md), after split)
- Eval tiers: **CRF 0 / 28 / 38** (full / medium / low)
- Degraded copies must **never cross splits** — encode after split assignment, or tag lineage carefully

## Undecided / blank

- **Stack:** —
- **Operate on images vs re-encode via short video roundtrip:** TBD (ffmpeg CRF is video-oriented; image JPEG quality is an alternative for frame-only workflows)
- **Storage layout:** parallel folders per tier vs on-the-fly during training
- **Architecture:** —

## Implementation notes

-

## Acceptance checks

- [ ] Produce medium + low versions of a known good frame
- [ ] Visual difference is obvious; file sizes drop
- [ ] Tier label stored in metadata
- [ ] Same CRF settings reusable by augmentation + eval

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Tier → CRF mapping (0/28/38) is exact; invalid tier rejected; metadata fields include `quality_tier` / CRF |
| **System** | Encode one synthetic frame/clip at medium + low → output files exist; low tier file smaller (or higher compression metric) than full; skip if ffmpeg missing |
| **Manual** | Side-by-side open full vs CRF 38 — blocky but recognizable |

**How to run:** `pytest tests/unit/test_quality_encoder.py tests/system/test_quality_encoder.py`

## Ties to proposal

“random low-bitrate re-encoding (ffmpeg, CRF 28–40)… evaluated at full, medium, and low quality (CRF 0/28/38).”
