# Make sources (`gfc-make-sources`)

**Stage:** 1 — Personal-clip data tools  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md)  
**Pairs with:** [ingest-pack.md](ingest-pack.md) (same output layout for contributor zips)

## What it does (high level)

Turns the videos under `data/raw/<Game>/<source>/` and `data/raw/_other/<name>/<source>/` into native-resolution stills under `data/frame_sources/`, using the same `sourcing` code and recipe as the Frame Export Kit. After this step a personal clip and a contributor clip look identical to everything downstream (D26).

## Why we need it

The splitter, loader and both models read slots with paired `full` and `crf45` images. Only the `sourcing` extraction produces those. Without this tool, personal clips can only go through the interim 256×144 batch extract, which has no slot ids, no paired tiers and a different sampler.

## Connections

| | |
|---|---|
| **Reads** | `data/raw/<Game>/<source>/**` and `data/raw/_other/<name>/<source>/**` videos; `config/recipe.json` |
| **Writes** | `data/frame_sources/<Game>/<source>/<clip_key>/` or `data/frame_sources/_other/<name>/<source>/<clip_key>/`, `clip.json`, `_personal/<run_id>/`, `_index/by_sha256.json` |
| **Next step** | [`gfc-derive-frames`](derive-frames.md) |
| **Shares code with** | Frame Export Kit (`sourcing.probe`, `sourcing.extract.extract_clip`, `sourcing.timeinfo`, `sourcing.hashing`) |

## Usage

```text
gfc-make-sources
gfc-make-sources --game Valorant --source myclips
gfc-make-sources --game Other
gfc-make-sources --limit 1 --dry-run
gfc-make-sources --rebuild c1a2b3c4d5e6f
gfc-make-sources --cpu                          # libx264 for this run
gfc-make-sources --budget-hours 2               # at most 2 h per game and source, in total
python -m game_frame_classifier.make_sources
```

| Flag | Meaning |
|---|---|
| `--data-root` | Data root (default `data`) |
| `--recipe` | Recipe file (default `config/recipe.json`) |
| `--game`, `--source` | Only this game folder / source folder |
| `--limit N` | Stop after N new clips |
| `--budget-hours H` | At most H hours of footage per game and source, counting clips already extracted (see Behaviour 3). Default: no budget |
| `--rebuild <clip_key>` | Delete that clip's folder and index entry, then extract it again (repeatable) |
| `--dry-run` | Probe and hash only; print what would be extracted; write nothing |
| `--cpu` | Decode on the CPU and encode the degraded tier with libx264 even if the GPU works (D28) |

Exit codes: `0` success (including nothing new), `1` at least one clip failed, `2` usage or missing input.

## Behaviour

1. **Scan.** Walk `data/raw/<Game>/<source>/` recursively for the six games and `data/raw/_other/<name>/<source>/` for Other. `<name>` must already equal `normalize_other_name(name)`. `--game Other` selects only the latter. Files are videos when their extension is in `video_extensions`.
2. **Source name.** `<source>` is the folder name, lower-cased through `normalize_handle`. It must not start with `contributor_` (reserved for ingested packs); such a folder is refused.
3. **Probe and select.** `sourcing.probe.probe_file`; skip clips shorter than `min_duration_s` or that fail to probe. Two files with the same content in one run: the second is `skipped` / `duplicate`. With `--budget-hours H`, the new clips of each game and source are picked with the kit's `spread_days_v1` (spread across recording days) up to H hours minus footage already extracted. For Other, the budget is separate per `(other_name, source)`.
4. **Identity.** `clip_sha256` over the file, `clip_key = "c" + sha[:12]`. If the SHA is already in `_index/by_sha256.json` (from an earlier run or from a contributor pack), the clip is skipped and listed as `skipped_existing`.
5. **Extract.** `extract_clip(tools, src, info, recipe, clip_key, stage, frames_root, rel_root)` with `frames_root = frame_sources/_tmp/<run_id>/frames` and `frame_mode` forced to `native`. Tiers come from the recipe (`full` + `crf45`). The degraded tier is encoded on the GPU (`h264_d3d12va`, QP 51) after a startup self-test, with the same picture checks, stall timeout, per-tier libx264 fallback and 3-in-a-row cut-off as the Frame Export Kit, and the same separate per-codec GPU decode check (D28). Each frame row records `encoder` and `encoder_rc`; `clip.json` records `low_encoder` and `gpu_fallback` (local paths scrubbed).
6. **Place.** Move `<clip_key>/` to `frame_sources/<Game>/<source>/<clip_key>/`, or `_other/<name>/<source>/<clip_key>/` for Other.
7. **`clip.json`.** One row with `sourcing.manifests.CLIP_COLUMNS`, filled the same way as the Frame Export Kit's `clip_row`. An Other clip additionally records `game = "Other"` and `other_name`.
8. **Index.** Add `clip_sha256 → {clip_key, pack_id: "personal:<run_id>", game, source, rel_dir}` to `_index/by_sha256.json`, written atomically.
9. **Run record.** `frame_sources/_personal/<run_id>/` holds `run_manifest.json`, `clips.csv/json` (every scanned file, including skipped and failed) and `frames.csv/json` (`FRAME_COLUMNS`, `rel_path` relative to `frame_sources/`).

One failed clip does not stop the run. Its staging folder is removed and it is reported with the first line of the error.

### `run_manifest.json`

```json
{
  "schema": "gfc.personal_run/1",
  "run_id": "20261118-101500",
  "created_utc": "2026-11-18T15:15:00Z",
  "tool": { "name": "gfc-make-sources", "version": "2.0.0", "source_commit": "abc1234" },
  "recipe": { "...": "resolved recipe, as in a pack manifest" },
  "ffmpeg": { "ffmpeg_version": "...", "ffprobe_version": "...", "build": "env", "x264_core": "..." },
  "encoder": { "requested": "gpu", "gpu_encoder": "h264_d3d12va", "gpu_available": true, "gpu_adapter": "...", "gpu_unavailable_reason": "", "gpu_stopped_reason": "", "clips_gpu": 10, "clips_cpu": 0, "clips_mixed": 0, "clips_gpu_fallback": 0 },
  "input": { "videos_found": 12, "clips_ok": 10, "clips_failed": 0, "clips_skipped_existing": 2, "input_bytes": 0, "input_duration_s": 0.0 },
  "output": { "tiers": ["full", "crf45"], "frame_mode": "native", "slots": 0, "images": 0 },
  "timing": { "wall_s": 0.0 }
}
```

No absolute path, hostname or username appears in any file this tool writes.

## Decisions

| | |
|---|---|
| Same recipe as contributors | Sampler, CRF and JPEG settings come from `config/recipe.json`; nothing personal-only is configurable here, so sources stay comparable |
| Encoder | GPU first (`h264_d3d12va`, QP 51), libx264 CRF 45 fallback, exactly as the Frame Export Kit (D28). The `encoder` block has the same keys as a pack manifest's, so personal and contributor runs read the same way |
| ffmpeg build | `sourcing.ffbin.find_tools()`; set `GFC_FFMPEG_DIR` to the pinned build used by the Frame Export Kit so personal and contributor frames match. The build and versions are recorded |
| HDR, odd sizes, VFR | Handled inside `extract_clip` exactly as for contributor packs |

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Source-name rules (`contributor_` refused); skip when SHA already indexed; `clip.json` has every `CLIP_COLUMNS` key; no absolute paths in any written JSON; `--rebuild` refuses an invalid `rel_dir`; run ids never reuse a run record |
| **System** | Two synthetic clips under a temp `raw/Valorant/tester/` → folders, file names, `clip.json`, index and run record as specified; second run extracts nothing; `--rebuild` replaces one clip; `--dry-run` leaves the tree unchanged |
| **Parity** | Same synthetic clip through `gfc-frame-export` + `gfc-ingest-pack` and through `gfc-make-sources`, both with `--cpu`, gives identical image SHA-256 lists (libx264 is deterministic; GPU output is not compared across tools) |
| **Encoder** | A `--cpu` run records `libx264` / `crf45` on every degraded frame, `low_encoder` on the clip and `requested: cpu` in the run record |

**How to run:** `pytest tests/unit/test_make_sources.py tests/system/test_make_sources.py`

## Acceptance checks

- [x] Layout under `frame_sources/<Game>/<source>/<clip_key>/` is identical to an ingested pack's
- [x] Rerun is a no-op; a clip already delivered in a contributor pack is skipped
- [x] Parity test green
- [x] CLI entry `gfc-make-sources` in `pyproject.toml`

## Ties to decisions

D22 (video CRF), D26 (one extraction path), D28 (encoder policy).
