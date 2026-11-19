# Pipeline timing

Measured wall-clock rates so we can estimate batch jobs before running them.

**How to refresh extract:** `python scripts/bench_extract.py` (uses `data/raw/`; writes `data/bench_extract/`).

Contributor-pack size/time by resolution (full + CRF 45, native stills): [handoff-sizes.md](handoff-sizes.md).

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

So extract time is dominated by **source decode** (4K AV1 ≫ 1080p H.264), not by writing 256×144 JPEGs. Contributor 1080p clips will be much faster; plan with the **103** rate only for 4K AV1 (or re-bench).

### Pre-flight estimate from catalog

After `gfc-catalog-clips`:

```text
video_minutes = sum(duration_s) / 60
extract_wall_min ≈ video_minutes × 103 / 60     # if sources match 4K AV1 profile
```

Or re-run the bench on a representative clip when codec/resolution changes.

---

## Quality tiers (video CRF → extract)

Method (D22 / D04): re-encode video at **CRF 45** (ops **low**), then extract 256×144 @ 1/5s; **full** = extract from the original. **Medium CRF 38** is docs/reference only, not required for ops timing.

Synthetic **1080p** color bars (lower bound; real gameplay is slower to encode), historical full+med+low bench:

| Source | Wall-s / video-min (full+med+low) | Notes |
|---|---:|---|
| 1080p30 synth | ~7 | `scripts/bench_quality_1080.py` |
| 1080p60 synth | ~12 | more frames to encode |

For **ops = full + CRF 45** only, expect roughly **~2/3** of those three-tier synth numbers (one re-encode instead of two), plus extract. Prefer [handoff-sizes.md](handoff-sizes.md) for real contributor-pack wall time (~75% in the CRF 45 encode).

4K AV1 personal clips: quality path tracks near **extract rate** plus re-encode cost (much slower than 1080p contributors).

## `gfc-make-sources` (measured 2026-11-19)

Same extractor as above (seek per sample, GPU encode for the low tier). Rates come from the
run reports (`frame_sources/_personal/<run>/clips.csv`) with
`python scripts/summarize_make_sources_timing.py`; 340 clips, 313 min of footage, about 1.1 h of wall time in total.

| Codec | Size | Method | Clips | Wall s / clip | Wall s / footage-min |
|---|---|---|---:|---:|---:|
| av1 | 3840x2160 | seek | 35 | 75.6 | 28.8 |
| av1 | 1920x1080 | seek | 8 | 53.2 | 17.7 |
| h264 | 1920x1080 | seek | 33 | 5.1 | 7.3 |
| h264 | 1280x720 | seek | 185 | 2.3 | 5.6 |
| h264 | 1280x720 | pass | 47 | 0.7 | 8.5 |
| h264 | 640x360 | seek | 31 | 10.6 | 3.5 |

Planning: `wall_s ~ rate x footage_minutes`, with the row for the source's codec and size.
Downloaded 720p H.264 videos cost about 6 s per footage-minute; 4K AV1 replays about 29.
Rerun the script after each batch to refresh the table.

---

## Not measured yet (fill in later)

| Stage | Planned metric | Notes |
|---|---|---|
| Catalog (`gfc-catalog-clips`) | wall-s / clip (ffprobe) | Usually seconds for dozens of files |
| Clean | wall-s / frame or / 1k frames | Pillow; should be ≪ extract for 4K AV1 sources |
| Batch extract end-to-end | sum of above | `--clean` adds catalog rebuild + deletes |
| `gfc-make-sources` | wall-s / footage-min | Measured, see the section above |

---

## Related

- [pipeline-status.md](pipeline-status.md)
- [handoff-sizes.md](handoff-sizes.md)
- `scripts/bench_extract.py`
- `scripts/bench_quality_1080.py`
