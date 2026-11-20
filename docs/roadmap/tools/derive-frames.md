# Derive frames (`gfc-derive-frames`)

**Stage:** 1 — Personal-clip data tools  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md)

## What it does (high level)

Walks `data/frame_sources/`, makes the 256×144 model-size copy of every native still (D27), and writes the two index tables every later step reads: one row per clip and one row per slot.

## Why we need it

Frame sources are native resolution and spread over per-clip folders with per-pack manifests. Training needs one image size and one table. This is the single place where native stills become model input, so personal and contributor frames get exactly the same scaler.

## Connections

| | |
|---|---|
| **Reads** | `data/frame_sources/<Game>/<source>/<clip_key>/` and `_other/<name>/<source>/<clip_key>/`, `_index/by_sha256.json`, `_packs/<pack_id>/pack_manifest.json`, `config/recipe.json` |
| **Writes** | `data/frames/<Game>/<source>/<clip_key>/` or `data/frames/_other/<name>/<source>/<clip_key>/`, `data/manifests/clips_index.csv/json`, `data/manifests/slots.csv/json` |
| **Previous step** | [`gfc-make-sources`](make-sources.md), [`gfc-ingest-pack`](ingest-pack.md) |
| **Next step** | [`gfc-clean-frames --slots`](frame-cleaner.md) |

## Usage

```text
gfc-derive-frames
gfc-derive-frames --game Valorant
gfc-derive-frames --game Other
gfc-derive-frames --force
gfc-derive-frames --index-only
python -m game_frame_classifier.derive_frames
```

| Flag | Meaning |
|---|---|
| `--data-root` | Data root (default `data`) |
| `--recipe` | Recipe file (default `config/recipe.json`); supplies `compact_size`, pad tolerance, scaler and JPEG quality |
| `--game`, `--source` | Derive only this game / source; the tables are still rebuilt for every clip |
| `--force` | Derive again even when the output folder is complete |
| `--index-only` | Skip image work; rebuild the two tables from what is on disk |

Exit codes: `0` success, `1` at least one clip failed, `2` usage or missing input.

## Behaviour

1. **Find clips.** Every `frame_sources/<Game>/<source>/<clip_key>/clip.json` for the six games, plus `_other/<name>/<source>/<clip_key>/clip.json`. Other internal folders (`_packs`, `_personal`, `_index`, `_stats`, `_tmp`) are skipped.
2. **Tiers.** Tier folders present in the clip folder. A clip must have `full` and at most one `crf<N>` tier matching the recipe. A clip with only `full` is a quick-mode clip (D04): it is kept, with `low_tier` empty. Anything else is reported and left out of the tables.
3. **Slots.** Parse `bucket` from `<clip_key>_<tier>_b<bucket>.jpg`. A slot exists when every tier of the clip has that bucket (for a quick-mode clip, every `full` file is a slot). Unpaired files are counted and ignored.
4. **Derive.** For each tier folder, `sourcing.derive` pad-then-scale (`pad` to 16:9 when the aspect is off by more than the tolerance, `scale=256:144:flags=bicubic`, JPEG `q2`) into `data/frames/<Game>/<source>/<clip_key>/<tier>/` with the **same file names**. A clip is skipped when its output folders already hold one image per slot per tier. A clip is derived again when any source still is newer than its derived copy (re-extracted clips).
5. **Already model-size sources.** When a clip's stills are already `compact_size` (a compact contributor pack; decided from the first `full` still, since `clip.json` reports the original video's size), files are copied byte for byte and `derive_id` is `compact_passthrough`.
6. **Check.** Every derived image is read back with `sourcing.hashing.jpeg_size` and must be exactly 256×144.
7. **Tables.** Rewritten in full on every run from the files on disk, sorted by game, source, `clip_key`, bucket.

`sourcing.derive.derive_dir` runs one ffmpeg call per folder only when the files are named `%06d.jpg` and share one size; otherwise it falls back to one call per file, which is much slower. It also deletes its destination folder before writing. This tool keeps the pack file names, so it stages each tier folder as a numbered sequence (hard links, or copies when links are not possible, in a temp folder under `data/frames/_tmp/`), derives into a second temp folder, renames the outputs back to the pack names, and only then moves them into place. A failed clip leaves its earlier output untouched.

## Output tables

### `clips_index.csv` (one row per clip)

| Column | Notes |
|---|---|
| `clip_key`, `clip_sha256` | Identity |
| `game`, `other_name`, `source` | `game` is `Other` and `other_name` is the normalised `_other` folder for non-six content; `other_name` is empty for the six games |
| `source_kind` | `contributor` when `source` starts with `contributor_` or `friend_`, `public` when it starts with `public_`, `web` when it starts with `yt_` (downloaded from the public web, no licence), else `personal` |
| `origin` | `pack_id` from the index (`personal:<run_id>` for make-sources) |
| `public_examples_ok` | `true` for personal sources; for contributor sources the pack's `consent.public_examples`; `false` for web sources and when unknown |
| `recorded_start_utc`, `recorded_start_source`, `duration_s` | From `clip.json`; input to sessions |
| `native_width`, `native_height`, `padded` | Native geometry (`width`, `height` in `clip.json`); `padded` = aspect pad applied |
| `hdr`, `vfr`, `video_codec`, `encoder_tag` | From `clip.json`, for shortcut analysis |
| `low_tier` | e.g. `crf45`; empty for a quick-mode clip |
| `low_encoder` | From `clip.json`: `h264_d3d12va`, `libx264`, `mixed`, or empty for packs made before D28's revision (treated as `libx264`). Lets evaluation split results by encoder |
| `slots` | Paired slots found on disk |
| `derive_id` | `pad16x9_bicubic_256x144_q2` or `compact_passthrough` |

### `slots.csv` (one row per slot)

| Column | Example |
|---|---|
| `slot_id` | `c1a2b3c4d5e6f:b000012` |
| `clip_key` | `c1a2b3c4d5e6f` |
| `game`, `other_name`, `source` | `Valorant`, empty, `contributor_alex`; or `Other`, `Apex_Legends`, `contributor_alex` |
| `bucket`, `target_time_s` | `12`, `60.0` (`bucket × interval_s`) |
| `path_full` | `frames/Valorant/contributor_alex/c1a2b3c4d5e6f/full/c1a2b3c4d5e6f_full_b000012.jpg` |
| `path_low` | `frames/Valorant/contributor_alex/c1a2b3c4d5e6f/crf45/c1a2b3c4d5e6f_crf45_b000012.jpg`; empty for a quick-mode clip |

Paths are relative to the data root. Original file names from `clip.json` are deliberately not copied into these tables.

## Decisions

| | |
|---|---|
| Disk is the source of truth | Tables are rebuilt from `frame_sources/` and `frames/` each run; there is no merged manifest to keep in sync with ingest |
| Derive policy | D27, parameters from the recipe. Changing the model input size means changing the recipe and running with `--force` |
| Output location | `data/frames/<Game>/<source>/<clip_key>/`. Interim batch-extract folders under the same game/source use the video stem, never a `clip_key`, and can be deleted |
| Public sources | The `public_` prefix is the working convention until public collection is designed (D12) |

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Bucket parsing; slot pairing with an unpaired file; `source_kind` rules; `public_examples_ok` for personal / consenting / non-consenting / unknown contributor; table rows sorted and paths relative |
| **System** | Temp `frame_sources` with a 16:9 clip, a 4:3 clip and a 256×144 clip → all outputs 256×144, 4:3 padded, compact copied byte for byte; quick-mode (full only) kept with empty `path_low`; rerun derives nothing; `--index-only` reproduces identical tables; a clip with no `full` tier is reported and excluded |

**How to run:** `pytest tests/unit/test_derive_frames.py tests/system/test_derive_frames.py`

## Acceptance checks

- [x] Every row of `slots.csv` points at existing 256×144 files (`path_full` always; `path_low` when the clip has a low tier)
- [x] Rerun with nothing new performs no image work and rewrites identical tables
- [x] A new pack or new personal clips appear after a rerun without touching existing outputs
- [x] CLI entry `gfc-derive-frames` in `pyproject.toml`

## Ties to decisions

D21 (JPEG), D26 (frame sources), D27 (derive policy), D29 (slot index is the training input).
