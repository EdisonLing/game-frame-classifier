# Ingest stills (`gfc-ingest-stills`)

**Stage:** 1 — Collection  
**Status:** specified  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [public dataset licences](public-licenses.md) · [ingest pack](ingest-pack.md) · [derive frames](derive-frames.md)

## What it does (high level)

Turns a folder of labelled still images (a public stills dataset, or screenshots someone sent) into `data/frame_sources/` clips that the rest of the pipeline treats like any other source. Stills that came from the same video or session stay together as one clip, so they never land on both sides of a split. For a public source, the dataset's licence must already be saved, and the tool records which files it ingested.

## Why we need it

Some datasets ship stills, not videos. Today only `scripts/prototype_public_stills.py` handles stills, with code written for two datasets. A general tool makes every stills dataset one manifest and one command, and makes the leakage risk explicit: groups that come from the dataset (real video or session ids) are trusted; groups the tool has to make up are marked as made up.

## Connections

| | |
|---|---|
| **Reads** | A folder of images and a manifest CSV; `config/public_sources.json` and `docs/licenses/<source>/` for public sources |
| **Writes** | `data/frame_sources/<Game>/<source>/<clip_key>/` (or `_other/<other_name>/<source>/<clip_key>/`): `full/*.jpg` and `clip.json`; `data/frame_sources/_stills/<source>/ingest_<UTC>.json` (run record); for public sources, the ingested file list in `docs/licenses/<source>/provenance.json` |
| **Then** | `gfc-derive-frames`, `gfc-clean-frames --slots ...`, `gfc-split`, `gfc-licenses` |

## Usage

```text
gfc-ingest-stills <images folder> --manifest <manifest.csv> --source public_gamed
gfc-ingest-stills <images folder> --manifest <manifest.csv> --source friend_alex --group-size 10
gfc-ingest-stills ... --dry-run            # check and report; write nothing
gfc-ingest-stills ... --limit-groups 5     # at most N clips per game (for a trial)
python -m game_frame_classifier.ingest_stills ...
```

| Flag | Meaning |
|---|---|
| `<images folder>` | Root that the manifest's `file` paths are relative to |
| `--manifest` | CSV, columns below |
| `--source` | Source name, normalised with `normalize_handle`; must not start with `contributor_` (packs) |
| `--group-size` | Stills per made-up group when the manifest has no `group` (default 10) |
| `--limit-groups` | Clips per game at most (default: all) |
| `--force` | Rewrite clips that already exist |
| `--dry-run` | Validate and print the plan; no writes |
| `--data-root` | Default `data` |

### Manifest

| Column | Required | Meaning |
|---|---|---|
| `file` | yes | Image path relative to the images folder (`/` or `\`) |
| `game` | yes | One of the six games or `Other` (exact names from `sourcing.labels.CLASSES`) |
| `other_name` | for `Other` | Content name, normalised with `normalize_other_name`; must be non-empty for `Other` |
| `group` | no | Video, session or match id from the dataset. Stills with the same `game` and `group` become one clip |
| `order` | no | Number (seconds or index) that orders stills within a group; default: file name order |

Blank lines and rows whose `file` starts with `#` are ignored.

Exit codes: `0` done; `1` some stills failed (unreadable image) and the rest were written; `2` usage error (bad manifest, unknown game, missing licence, refused source, missing image folder).

## Behaviour

1. **Validate.** Read the manifest; stop with exit 2 on a missing required column, an unknown `game`, `Other` without `other_name`, or a duplicate `file`. Every `file` must exist under the images folder (missing ones: exit 2 listing up to 20).
2. **Licence gate (public sources).** If `--source` starts with `public_`: the source must be in `config/public_sources.json` with `approved: true` and `docs/licenses/<source>/LICENSE.txt` must exist; otherwise exit 2 with "save the licence first: run the dataset's downloader or `fetch_license`". Non-public sources skip this step.
3. **Group.**
   - With a `group` column: one clip per (`game`, `other_name`, `group`); `group_origin = "dataset"`.
   - Without it (or rows with an empty `group`): per (`game`, `other_name`), stills sorted by `file`, cut into consecutive groups of `--group-size`; `group_origin = "made_up"`, group ids `auto0000`, `auto0001`, …
   - Within a clip, stills ordered by `order` (numeric) then `file`.
   - `--limit-groups N` keeps the first N clips per game in group-id order.
4. **Clip key.** `"c" + sha256("stills:<source>:<game>:<other_name>:<group>")[:12]`. Stable across reruns.
5. **Skip or rewrite.** A clip folder that exists with a `clip.json` is skipped unless `--force` (then removed and rewritten).
6. **Write each clip** to `frame_sources/<Game>/<source>/<clip_key>/` (Other: `_other/<other_name>/<source>/<clip_key>/`):
   - Each still to `full/<frame_name(clip_key, "full", i)>` for i = 0, 1, … in clip order. JPEG files are copied byte for byte; any other format Pillow reads is converted to RGB JPEG quality 95. An unreadable image is skipped and counted as failed; a clip with no readable stills is not written.
   - `clip.json` from `blank_clip_row()` with: `clip_key`, `clip_sha256` (sha256 over the stored JPEG bytes in order), `quick_id` (its first 16 hex), `status = "ok"`, `status_detail = "stills"`, `original_filename = "<group>.stills"`, `original_relpath` = the group id, `file_bytes` (sum of the source images), `recorded_start_utc` (step 7), `recorded_start_source = "synthetic"`, `duration_s = 5.0 × stills`, `width` / `height` of the first still, `expected_slots` = `slots` = stills, `label_hint` = game; plus extra keys `game`, `other_name`, `stills_group`, `group_origin`.
7. **Synthetic times.** Stills have no recording time. Clips of one source get `2000-01-01T00:00:00Z + k hours`, k = the clip's index in (game, other_name, group id) order, so every clip is its own session (the splitter's gap is 30 minutes) and the order is stable.
8. **Run record** `frame_sources/_stills/<source>/ingest_<UTC>.json`: manifest path and sha256, images folder, group-size, counts (clips written, skipped, stills written, failed) per game, made-up group share.
9. **Provenance (public).** For a public source, append one entry for the manifest with `record_download(source, manifest_path)`, so `provenance.json` lists what was ingested.
10. **Summary** printed: clips and stills per game, `made_up` groups and a warning line when any exist ("made-up groups: stills from one video may sit in different clips; near-duplicates are removed by the cleaner, but leakage is possible").

## Also in this task

- **`public_sources._clip_dirs`** also looks under `frame_sources/_other/<name>/<source_id>/`, so a public Other dataset counts as active and is counted in `THIRD_PARTY_DATA.md`.
- **`scripts/prototype_public_stills.py`** keeps its downloads but writes clips through `ingest_stills.write_still_clip` (same clip keys as before are not required).

## Never

- Never ingest a public source whose licence is not saved or which is not approved.
- Never write outside `data/frame_sources/` (and `docs/licenses/<source>/provenance.json` for public sources).
- Never use a `contributor_` source (packs go through `gfc-ingest-pack`).
- Never put stills of different `group` values in one clip.

## Testing

| Kind | Cases |
|---|---|
| **Unit: manifest** | Required columns; unknown game; `Other` without name; duplicate file; missing image; `#` and blank rows |
| **Unit: groups** | Dataset groups; made-up groups of N with ids; `order` then file ordering; `--limit-groups` |
| **Unit: licence gate** | Public source unapproved, unknown, or without `LICENSE.txt` refused (exit 2); non-public source not checked |
| **Unit: write** | JPEG copied byte-identical; PNG converted; unreadable image counted as failed; empty clip not written; `clip.json` fields; stable clip keys; skip existing, `--force` rewrites; Other path |
| **Unit: times** | Clip k gets base + k hours; stable order |
| **Unit: licences** | `_clip_dirs` finds `_other/<name>/<source_id>/` clips |
| **System** | Fake images (JPEG and PNG) + manifest → ingest → `gfc-derive-frames` → `gfc-clean-frames --slots` → `gfc-split` puts every clip whole in one split; for a `public_` source with a saved licence and an approved test config, `licenses.json` lists it |

## Acceptance checks

- [ ] A stills folder with a manifest becomes frame_sources clips that derive, clean and split like video clips
- [ ] Dataset groups stay whole; made-up groups are marked and warned about
- [ ] Public stills are refused without an approved source and a saved licence
- [ ] CLI entry `gfc-ingest-stills` in `pyproject.toml`

## Build instructions

Written for an agent that builds exactly this and decides nothing; ask the user if anything is unclear. No network in tests; Pillow is already a dependency.

1. **`src/game_frame_classifier/ingest_stills.py`** (new):
   - `@dataclass StillRow(file: str, game: str, other_name: str, group: str, order: float | None)`; `@dataclass StillClip(game, other_name, group, group_origin, rows: list[StillRow])`.
   - `class IngestStillsError(Exception)` with `exit_code` (as `PublicSourcesError`).
   - `read_manifest(path, images_root) -> list[StillRow]` (Behaviour 1).
   - `check_licence(source, *, repo_root) -> None` (Behaviour 2; uses `public_sources.load_sources` and `license_dir`).
   - `group_rows(rows, group_size, limit_groups) -> list[StillClip]` (Behaviour 3).
   - `clip_key_for(source, clip) -> str` (Behaviour 4).
   - `write_still_clip(fs_root, source, clip, images_root, *, clip_index, force) -> tuple[str, int, int]` returning (`"written"` / `"skipped"` / `"empty"`, stills written, stills failed) (Behaviours 5–7).
   - `run(images_root, manifest, source, *, data_root, repo_root, group_size, limit_groups, force, dry_run) -> dict` (Behaviours 8–10).
   - `main(argv)`: argparse as in Usage; `sys.stdout.reconfigure(errors="replace")`; `normalize_handle` on `--source`, refuse empty or `contributor_` (exit 2).
2. **`__main__`**: `python -m game_frame_classifier.ingest_stills` calls `main` (module-level `if __name__ == "__main__": raise SystemExit(main())`).
3. **`public_sources.py`**: extend `_clip_dirs` to `_other/<name>/<source_id>/<clip>` (skip names starting with `_`); its game key for counts is `Other`.
4. **`scripts/prototype_public_stills.py`**: replace its `write_clip` with building `StillClip` objects (Gamed: group = `video_id`, origin `dataset`; Gameplay Images: made-up groups of `--images-per-clip`) and calling `write_still_clip`.
5. **`pyproject.toml`**: `gfc-ingest-stills = "game_frame_classifier.ingest_stills:main"`. **`docs/data-layout.md`**: `_stills/<source>/` run records and the `synthetic` recording-time source. **`docs/research/public-dataset-use-plan.md`**: in its ingest steps, name `gfc-ingest-stills` for stills.
6. **Tests** as in the Testing table: `tests/unit/test_ingest_stills.py`, a case in `tests/unit/test_public_sources.py`, `tests/system/test_ingest_stills.py`.
