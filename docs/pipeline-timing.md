# Pipeline timing

Measured wall-clock rates so we can estimate batch jobs before running them.

**How to refresh:** `python scripts/bench_extract.py` (uses `data/raw/`; writes `data/bench_extract/`).

---

## Frame extract (current defaults)

Settings: **1 frame / 5 s**, resize **256×144** JPEG, ffmpeg decode + scale.

### Firm rate — personal 4K AV1 replays (this machine)

Measured 2026-11-15 on five ~3 min Valorant replays (`3840×2160`, **av1**, ~650 MB each).

| Run | Video processed | Wall time | Wall-s / video-min |
|---|---:|---:|---:|
| 1 min slice | 1.0 min | 103.7 s | **103.7** |
| 3 min slice | 3.0 min | 313.0 s | **104.3** |
| Full clip | 3.0 min | 310.0 s | **103.3** |

**Use this number for planning on the same kind of source:**

```text
wall_seconds ≈ 103 × video_minutes
wall_minutes ≈ 1.72 × video_minutes          # ~1.7× realtime
wall_hours   ≈ 103 × video_minutes / 3600
```

At 5 s interval: **~12 frames / video-minute** → about **8.6 wall-s / output frame**.

Rate was stable across 1 min / 3 min / full (±1%), so linear scaling is trustworthy for this codec/resolution.

### Current library estimate (same day)

| | |
|---|---|
| Clips | 5 |
| Total duration | **15.0 video-minutes** |
| Batch extract (all, from scratch) | **≈ 26 wall-minutes** (`15 × 103 / 60`) |

### Contrast — easy source (same extract settings)

Synthetic **1920×1080 H.264** color bars, 60 s: **0.39 wall-s / video-min**.

So extract time is dominated by **source decode** (4K AV1 ≫ 1080p H.264), not by writing 256×144 JPEGs. Friend clips or 1080p downloads will be much faster; plan with the **103** rate only for 4K AV1 (or re-bench).

### Pre-flight estimate from catalog

After `gfc-catalog-clips`:

```text
video_minutes = sum(duration_s) / 60
extract_wall_min ≈ video_minutes × 103 / 60     # if sources match 4K AV1 profile
```

Or re-run the bench on a representative clip when codec/resolution changes.

---

## Quality tiers (video CRF → extract)

Method (D22): re-encode video at CRF 28/38, then extract 256×144 @ 1/5s (full = extract from original).

Synthetic **1080p** color bars (lower bound; real gameplay is slower to encode):

| Source | Wall-s / video-min (full+med+low) | Notes |
|---|---:|---|
| 1080p30 synth | ~7 | `scripts/bench_quality_1080.py` |
| 1080p60 synth | ~12 | more frames to encode |

Frame zip size (real HUD gameplay, not synth): ~**0.15 MB/video-min** per tier → ~**0.45 MB/video-min** for three tiers.

4K AV1 personal clips: quality path will track near **extract rate × ~3** plus re-encode cost (much slower than 1080p friends).

## Not measured yet (fill in later)

| Stage | Planned metric | Notes |
|---|---|---|
| Catalog (`gfc-catalog-clips`) | wall-s / clip (ffprobe) | Usually seconds for dozens of files |
| Clean | wall-s / frame or / 1k frames | Pillow; should be ≪ extract for 4K AV1 sources |
| Batch extract end-to-end | sum of above | `--clean` adds catalog rebuild + deletes |

---

## Related

- [pipeline-status.md](pipeline-status.md)
- `scripts/bench_extract.py`
