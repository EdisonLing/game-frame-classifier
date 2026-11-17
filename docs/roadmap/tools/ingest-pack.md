# Ingest pack (`gfc-ingest-pack`)

**Stage:** 1 — Personal-clip data tools  
**Status:** planned (spec v1 locked; not built)  
**Back to:** [ROADMAP.md](../ROADMAP.md)  
**Pairs with:** [frame-export-kit.md](frame-export-kit.md) §11 (zip contract this tool consumes)

## What it does (high level)

Takes a contributor pack zip (or a zip of pack zips) from the Frame Export Kit, validates it safely, and places its native-res stills into `data/frame_sources/` so friend frames and my own sources share one layout (D26).

## Why we need it

Friends send frames, not masters. Without a single ingest path, packs become a one-off dump and drift from personal extracts. Ingest is the gate: zip bomb / path checks first, then content checks, then content-addressed placement with dedupe by clip SHA-256.

## Out of scope (v1)

- `gfc-make-sources` (personal clips → same `frame_sources` layout)
- Derive to 256×144 train frames (`data/frames/…`) — separate step using `sourcing.derive` (D27)
- Cleaning, lobby filter, HUD crops
- Network download of packs (you pass a local zip path)
- Rewriting or “fixing” a friend’s recipe (differences are recorded only)

## Goals

| | |
|---|---|
| G1 | Never write anything until zip safety checks pass. |
| G2 | Place only packs that pass content checks (schemas, hashes, complete slots). |
| G3 | Dedupe by full `clip_sha256` across all existing frame sources. |
| G4 | Keep pack manifests verbatim under `_packs/<pack_id>/` for audit and re-derive. |
| G5 | Append local size stats (zip vs source bytes, resolution) for D25 tracking. |
| G6 | Stdlib + existing `sourcing` only; no new third-party deps. |

## Usage

```text
gfc-ingest-pack <zip>
gfc-ingest-pack <zip> --data-root data --recipe config/recipe.json
gfc-ingest-pack <zip> --dry-run
gfc-ingest-pack <zip> --force
python -m game_frame_classifier.ingest_pack <zip>
```

| Flag | Meaning |
|---|---|
| `<zip>` | Path to a contributor pack, or a zip whose entries are only pack zips (one nesting level; already supported by `sourcing.packzip.validate_pack_zip`) |
| `--data-root` | Project data root (default: `data`). Frame sources go under `<data-root>/frame_sources/` |
| `--recipe` | Expected recipe JSON (default: `config/recipe.json`). Compared to the pack’s embedded recipe; mismatches are warnings, not failures |
| `--dry-run` | Validate + content-check only; print the plan; write nothing |
| `--force` | Allow re-ingest when `_packs/<pack_id>/` already exists (replace that pack’s stored manifests and re-copy its frames). Still skips clips whose `clip_sha256` is owned by a *different* pack |

Exit codes: `0` success (including “nothing new to place”), `1` validation/content failure, `2` usage / missing inputs.

## Layout after ingest

```text
data/frame_sources/
  <Game>/                          # e.g. Valorant
    contributor_<handle>/
      <clip_key>/                  # c + first 12 hex of clip_sha256
        full/
          <clip_key>_full_b000000.jpg
          ...
        crf45/
          ...
        clip.json                  # one clip row from the pack (status=ok)
  _other/
    <other_name>/                  # only when pack game label is Other
      contributor_<handle>/
        <clip_key>/...
  _packs/
    <pack_id>/                     # UUID from pack_manifest.json
      pack_manifest.json           # verbatim
      clips.json                   # verbatim
      frames.json                  # verbatim
      clips.csv                    # verbatim
      frames.csv                   # verbatim
      run_log.txt                  # verbatim
      probe/                       # verbatim probe JSON files present in the pack
      ingest.json                  # written by this tool (see below)
  _index/
    by_sha256.json                 # map clip_sha256 → placement record
  _stats/
    handoff_sizes.jsonl            # one JSON object per ingested pack (local; gitignored)
```

`contributor_<handle>` uses the normalised handle from the pack (`contributor.handle`), prefixed with `contributor_`. Handle rules match the export kit (`[a-z0-9_]{1,24}`).

## Zip safety (before any write)

Reuse `game_frame_classifier.sourcing.packzip.validate_pack_zip` unchanged. That already enforces:

- Relative ASCII paths, no `..`, no drive letters, no symlinks, no encryption
- Allowed extensions `.jpg .json .csv .txt` (and `.zip` only for a top-level zip-of-packs)
- Per-entry size ≤ 64 MiB; total uncompressed ≤ min(64 GiB, declared × 1.05 + 16 MiB)
- Entry count = `file_count` + 1
- `STORED` or `DEFLATED` with ratio limits
- One nesting level for zip-of-packs
- Root folder `gfc_pack_<8 hex>`; schema `gfc.pack/1`

Scratch for nested inners: `<data-root>/frame_sources/_tmp/scratch/` (created as needed, emptied after).

## Content checks (after zip safety, before placement)

For each pack manifest returned by the validator, open the zip again (or the extracted staging copy) and check:

1. **Required files present:** `pack_manifest.json`, `clips.json`, `frames.json`, `clips.csv`, `frames.csv`, `run_log.txt`.
2. **Contributor:** `contributor.handle` non-empty and normalises to itself; `contributor.contributor_id` is a non-empty string; `consent.data_use` is true (refuse otherwise).
3. **Game:** `game.label` is one of the recipe games or `Other`. If `Other`, `game.other_name` must be a non-empty normalised other-name.
4. **Recipe:** pack `recipe` is a dict with `recipe_id`. Diff against `--recipe` (field-by-field on the resolved recipe keys the export kit embeds). Record adds/changes in `ingest.json` as `recipe_diff`; do not fail.
5. **Clips:** every `clips.json` row with `status == "ok"` has `clip_key`, `clip_sha256` (64 hex), `expected_slots` / `slots` ints with `slots >= 1`, and `slots == expected_slots` unless `unpaired_dropped` explains attrition — for v1 require `slots == expected_slots` and `unpaired_dropped == 0` (export kit already aims for this; refuse odd packs).
6. **Frames:** every `frames.json` row for those ok clips:
   - `rel_path` is under `frames/<clip_key>/<tier>/` and exists in the zip
   - file bytes length == `bytes`
   - SHA-256 of bytes == `sha256`
   - JPEG SOF size == `(width, height)` via `sourcing.hashing.jpeg_size` on a temp extract of that entry
7. **Slots complete:** for each ok clip, for each tier in `manifest.output.tiers`, the set of `bucket` values matches across tiers (same buckets), and count of frames for that clip equals `slots * len(tiers)`.
8. **Probe files (optional but checked if present):** `probe/<clip_key>.json` must be valid JSON when listed in the zip.
9. **Handle / id collisions (warn, don’t refuse):**
   - Same `handle`, different `contributor_id` than an earlier pack in `_packs/` → warning
   - Same `contributor_id`, different `handle` → warning

Any hard failure raises a clear error naming the pack id and the first problem; nothing from that pack is placed. A zip-of-packs processes each inner pack independently: failures in one do not roll back a previously successful pack in the same invocation, but the process exit code is `1` if any pack failed.

## Placement

For each ok clip not skipped by dedupe:

1. Destination directory:
   - Normal game: `<data-root>/frame_sources/<Game>/contributor_<handle>/<clip_key>/`
   - Other: `<data-root>/frame_sources/_other/<other_name>/contributor_<handle>/<clip_key>/`
2. Copy each frame file from the zip into `<clip_key>/<tier>/<filename>` (filenames stay as in the pack).
3. Write `clip.json` (the single clips.json row) into `<clip_key>/`.
4. **Dedupe:** if `clip_sha256` is already in `_index/by_sha256.json`, skip the clip and list it under `ingest.json` → `skipped_existing`. Do not overwrite another pack’s frames.
5. **Same pack re-ingest (`--force`):** if this `pack_id` already owns the sha in the index, replace files for that clip_key.

After clips:

6. Write `_packs/<pack_id>/` with verbatim copies of the pack tables, manifest, run log, and any `probe/*.json`.
7. Write `_packs/<pack_id>/ingest.json` (this tool’s record).
8. Update `_index/by_sha256.json` atomically (write `.tmp` then replace).
9. Append one line to `_stats/handoff_sizes.jsonl`.

### `ingest.json` schema

```json
{
  "schema": "gfc.ingest/1",
  "ingested_utc": "2026-11-17T04:00:00Z",
  "tool": {"name": "gfc-ingest-pack", "version": "1.0.0"},
  "source_zip": "GFC_Valorant_alex_20261116-1200.zip",
  "pack_id": "…",
  "recipe_diff": [],
  "warnings": [],
  "clips_placed": 2,
  "clips_skipped_existing": 1,
  "clips_failed": 0,
  "placed_clip_keys": ["c0123…", "c4567…"],
  "skipped_clip_keys": ["c89ab…"]
}
```

`source_zip` is the basename only (no absolute path).

### Index record (`by_sha256.json`)

```json
{
  "<clip_sha256>": {
    "clip_key": "c0123456789ab",
    "pack_id": "…",
    "game": "Valorant",
    "source": "contributor_alex",
    "rel_dir": "Valorant/contributor_alex/c0123456789ab"
  }
}
```

### Stats line (`handoff_sizes.jsonl`)

```json
{
  "ingested_utc": "…",
  "pack_id": "…",
  "game": "Valorant",
  "handle": "alex",
  "frame_mode": "native",
  "width": 3840,
  "height": 2160,
  "zip_bytes": 53477376,
  "input_bytes": 679477248,
  "uncompressed_bytes": 53089202,
  "slots": 37,
  "images": 74,
  "clips_placed": 1
}
```

`width`/`height` are the modal frame size among placed frames (or 0 if none placed). `zip_bytes` is the size of the outer file when ingesting a single pack zip; for an inner pack from a zip-of-packs, use that inner zip’s uncompressed payload size as stored in the outer entry’s `file_size`.

## Console output (human)

```text
gfc-ingest-pack 1.0.0
Validating GFC_Valorant_alex_….zip …
  pack 3b8f…2a1: Valorant / contributor_alex — 2 clips ok in manifest
  recipe_diff: (none)
  placed 2, skipped existing 0
Wrote data/frame_sources/_packs/3b8f…2a1/
```

`--dry-run` prints the same plan with `dry-run: no files written`.

## Implementation sketch

```text
src/game_frame_classifier/ingest_pack.py   # CLI + orchestration (v1)
src/game_frame_classifier/sourcing/
  packzip.py                               # already validates zips
  hashing.py                               # sha256_file, jpeg_size
  manifests.py                             # column names
  labels.py                                # normalize_handle, OTHER, GAMES
```

No ffmpeg required for ingest v1 (frames are already JPEG).

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Path helpers; index load/save; recipe_diff; skip-existing; Other path; refuse `consent.data_use=false`; handle collision warnings |
| **System** | Build a minimal valid pack zip (reuse `write_pack_zip` + tiny JPEG fixtures) → ingest into tmp `data-root` → files land in the right tree with matching hashes; second ingest skips; `--dry-run` writes nothing; zip-of-two-packs places both; path-traversal zip still refused by validator before write; `--force` replaces same `pack_id` |

**How to run:** `pytest tests/unit/test_ingest_pack.py tests/system/test_ingest_pack.py`

## Acceptance checks

- [ ] Safe zip fails closed (no files under `frame_sources/` after a bad zip)
- [ ] Good pack places frames + `_packs/<id>/` + index + stats line
- [ ] Duplicate `clip_sha256` skipped
- [ ] `Other` lands under `_other/<other_name>/`
- [ ] `--dry-run` is bit-identical tree before/after
- [ ] CLI entry `gfc-ingest-pack` in `pyproject.toml`

## Ties to decisions

- **D25** — receive contributor packs; track zip vs source size  
- **D26** — `frame_sources` layout shared with future `gfc-make-sources`  
- **D24** — `Other` / unknown-class material under `_other/`
