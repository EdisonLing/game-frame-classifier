# Quality encoder

**Stage:** 1 — Personal-clip data tools  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Re-encodes frames at controlled quality tiers using an **ffmpeg H.264 CRF round-trip**, producing full / medium / low copies of the same content with tier metadata.

## Why we need it

1. **Train augmentation** — random CRF in **28–40** on a fraction of train frames (wired later in [augmentation](augmentation.md))  
2. **Eval** — same frames scored at **full / medium / low** (CRF **0 / 28 / 38**)

## Inputs / outputs

| | |
|---|---|
| **In** | `frames_manifest.csv` / `.json` (cleaned frames preferred) |
| **Out** | `output_dir/<tier>/` images + manifests; `quality_summary.json` |

## Known design choices (locked for v1)

- **Stack:** Python + ffmpeg `libx264` (same style as extractor)
- **Method (D22):** still → 1-frame H.264 at CRF → JPEG (not a JPEG-quality-only proxy)
- **CRF 0 (`full`):** byte-copy of the source (no re-encode)
- Eval tiers: **full=0, medium=28, low=38**
- Augmentation range constants: **28–40** (`AUGMENT_CRF_MIN/MAX`)
- Per-tier folders so degraded copies do not silently mix with originals

## CLI

```bash
gfc-encode-quality data/frames/my_clip_cleaned/frames_manifest.csv -o data/frames/my_clip_quality
gfc-encode-quality ... -o out --tiers full medium low
```

## Module API

- `crf_for_tier(tier)` / `degrade_frame_ffmpeg(src, dest, crf=…)`
- `encode_frame_record(...)` / `encode_manifest(...)`

## Acceptance checks

- [x] Tier → CRF map matches proposal
- [x] Medium/low encodes exist; low typically smaller than full copy
- [x] Manifests store `quality_tier` + `crf` + source frame id
- [x] Optional personal smoke on `valorant_smoke` when present

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Tier map; unknown tier rejected; CRF bounds |
| **System** | Synthetic frame encode; manifest multi-tier layout; bad tier fails fast |
| **Personal** | `valorant_smoke` → 4 frames × 3 tiers when extract exists |

```bash
pytest tests/unit/test_quality_encoder.py tests/system/test_quality_encoder.py
```

## Ties to proposal

“random low-bitrate re-encoding (ffmpeg, CRF 28–40)… evaluated at full, medium, and low quality (CRF 0/28/38).”
