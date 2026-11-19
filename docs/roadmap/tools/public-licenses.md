# Public dataset licences (`gfc-licenses`)

**Stage:** 1 — Collection  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [public sources ledger](../../research/public-sources-ledger.md) · [dataset splitter](dataset-splitter.md)

## What it does (high level)

Every public dataset keeps a copy of its own licence, saved at download time, and the project keeps one licence and attribution document that is rebuilt from the datasets actually in use. A download that cannot save its licence stops before any media is written. Each split also records which public datasets it used, so a run's results can always be credited correctly.

## Why we need it

Public datasets come with different licences (CC BY, CC BY-NC, MIT, Apache 2.0), each with its own attribution text and limits, and the split presets turn them on and off per run. Today the ledger names the licence by SPDX id only; nothing keeps the licence text, the exact version downloaded, or which datasets a given split used.

## Files

| Path | Holds | Tracked |
|---|---|---|
| `config/public_sources.json` | One entry per public source (the ledger's source of truth) | yes |
| `docs/licenses/<source_id>/LICENSE.txt` | The licence text as downloaded | yes (public texts) |
| `docs/licenses/<source_id>/provenance.json` | Where and when it came from, hashes | yes |
| `docs/THIRD_PARTY_DATA.md` | Generated: licences and attribution for active sources | yes (generated) |
| `docs/research/public-sources-ledger.md` | Generated table from `config/public_sources.json` plus the hand-written filter notes | yes |
| `data/manifests/splits/<id>/licenses.json`, `licenses.md` | Public sources used by that split, with slot counts | no (data) |

### `config/public_sources.json` entry

```json
{
  "source_id": "public_vpt_contractor",
  "games": ["Minecraft"],
  "dataset_name": "OpenAI VPT contractor demos",
  "official_url": "https://github.com/openai/Video-Pre-Training/",
  "license_spdx": "MIT",
  "license_url": "https://raw.githubusercontent.com/openai/Video-Pre-Training/main/LICENSE",
  "commercial_ok": "review",
  "attribution_text": "OpenAI Video Pre-Training contractor demonstrations (MIT); Minecraft (c) Microsoft/Mojang.",
  "approved": false,
  "notes": ""
}
```

`approved` is set by the person only, after reading the licence; a download refuses an unapproved source. `status` is not stored; it is computed (Behaviour 3).

### `provenance.json`

`source_id, dataset_url, dataset_revision` (commit, version or file date when the host gives one, else empty)`, license_spdx, license_url, license_sha256, retrieved_utc, files` (each downloaded archive: name, bytes, sha256).

## Behaviour

1. **Licence before media.** Any downloader for a public source (`scripts/prototype_public_stills.py` now, later fetchers) calls `fetch_license(source_id)` first: it refuses a source missing from `config/public_sources.json` or with `approved = false` (exit 2), downloads `license_url` to `docs/licenses/<source_id>/LICENSE.txt`, and writes `provenance.json`. If the licence cannot be downloaded or is empty, it stops with exit 1 and writes no media. If a `LICENSE.txt` already exists with a different hash, it keeps the old file as `LICENSE.<retrieved date>.txt` and says the licence changed.
2. **Download record.** After the media download, the downloader appends each archive's name, size and sha256 to `provenance.json`.
3. **Status from disk.** A source is `active` when `data/frame_sources/<Game>/<source_id>/` holds at least one clip for any game; `downloaded` when its licence folder exists but no frames do; `planned` otherwise.
4. **`gfc-licenses`** rebuilds `docs/THIRD_PARTY_DATA.md` and the ledger table:
   - `THIRD_PARTY_DATA.md`: a header saying it is generated; one section per active source with dataset name, link, licence id and link to `docs/licenses/<id>/LICENSE.txt`, the attribution text, commercial use, date retrieved and frames on disk per game; then a short list of downloaded-but-unused sources. With no active source, it says so.
   - The ledger table between the markers `<!-- ledger:start -->` and `<!-- ledger:end -->` in `public-sources-ledger.md`, with the computed status; text outside the markers is left as is.
   - `--check`: writes nothing, exit 1 if either file is out of date (for use before committing).
5. **Per split.** `gfc-split` writes `licenses.json` and `licenses.md` into every split folder: each public source with slots in any split (slots per split and game) and its licence and attribution from `config/public_sources.json`; an empty list when the split uses none. A public source in a split but missing from `config/public_sources.json` stops the split with exit 2.
6. **Per run.** The trainers copy the split's `licenses.json` into the run folder; `run-report` lists the public sources of a run in the entry's Data section.

## Never

- Never write public media before its licence is saved.
- Never download a source with `approved = false`.
- Never delete an old licence copy.
- Never edit `THIRD_PARTY_DATA.md` or the ledger table by hand; edit `config/public_sources.json` and run `gfc-licenses`.

## Testing

| Kind | Cases |
|---|---|
| **Unit: fetch** | Unapproved and unknown sources refused; licence saved with hash; failed or empty licence stops before media; changed licence keeps the old copy |
| **Unit: status** | planned / downloaded / active from fake folders |
| **Unit: documents** | `THIRD_PARTY_DATA.md` with zero, one and two active sources; ledger table replaced only between markers; `--check` exit codes |
| **Unit: split** | `licenses.json` lists used public sources with counts; empty when none; unknown public source refused |
| **System** | Fake licence and archive served from a temp folder → prototype ingest → derive → split → `licenses.json` → `gfc-licenses` shows the source as active |

## Acceptance checks

- [x] A public download saves its licence and provenance first, and refuses unapproved sources
- [x] `docs/THIRD_PARTY_DATA.md` lists exactly the active public sources
- [x] Every split and run records the public sources it used
- [x] CLI entry `gfc-licenses` in `pyproject.toml`

## Build instructions

Written for an agent that builds exactly this and decides nothing; ask the user if anything is unclear. No network in tests.

1. **`src/game_frame_classifier/public_sources.py`** (new): `load_sources(path) -> dict[str, dict]` (validates required keys); `fetch_license(source_id, *, repo_root, opener=urllib.request.urlopen, now)` (Behaviour 1); `record_download(source_id, file_path, *, repo_root)` (Behaviour 2); `source_status(source_id, data_root, repo_root)` (Behaviour 3); `build_third_party(...) -> str`; `build_ledger_table(...) -> str`; `main(argv)` for `gfc-licenses [--check] [--data-root]` (Behaviour 4).
2. **`config/public_sources.json`**: the eight rows of today's ledger table, all `approved: false`, with `license_url` set to the licence file or licence page of each dataset.
3. **`docs/research/public-sources-ledger.md`**: wrap the table in the markers; regenerate it with `gfc-licenses`.
4. **`scripts/prototype_public_stills.py`**: call `fetch_license` before downloading and `record_download` after.
5. **`dataset_splitter.py`**: write `licenses.json` / `licenses.md` (Behaviour 5).
6. **`train.py`, `baseline.py`**: copy the split's `licenses.json` into the run folder when present.
7. **`pyproject.toml`**: `gfc-licenses = "game_frame_classifier.public_sources:main"`. **`docs/data-layout.md`**: the split files. **`.edutil/agents/skills/run-report`** is not edited by the agent; list the needed change in the final report.
8. **Tests** as in the Testing table.
