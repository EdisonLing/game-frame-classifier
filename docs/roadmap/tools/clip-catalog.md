# Clip catalog

**Stage:** 1 — Personal-clip data tools  
**Status:** planned  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Builds a table of every source video/clip: filesystem path, game label, channel/session id, and light metadata (duration, resolution, etc.). This is the inventory everything else reads from.

## Why we need it

Without a catalog, labels live in folder names or memory and break as soon as you add friends’ clips or public VODs. The progress report also needs reproducible “where did this frame come from?” answers (video id, channel, timestamp).

## Inputs / outputs

| | |
|---|---|
| **In** | Folder(s) of personal clips; a simple way to assign game labels (folder convention or CSV) |
| **Out** | Manifest (CSV/JSON/Parquet — TBD) with one row per clip |

## Known design choices

- Six game labels matching the proposal: Valorant, LoL, CS2, Minecraft, Overwatch 2, Marvel Rivals
- Store enough ids to support **video/session-level splits** later (not frame-level)
- Personal clips: treat a recording session as the split unit

## Undecided / blank

- **Stack:** *(likely Python + pathlib; manifest format TBD)*
- **Architecture:** —
- **Label UX:** folder-per-game vs sidecar CSV vs interactive CLI
- **Schema fields beyond path/game/session:** exact column list TBD

## Implementation notes

-

## Acceptance checks

- [ ] Point at a personal-clip folder → get a complete manifest
- [ ] Every row has a valid game label and a resolvable path
- [ ] Session/video id is stable enough for the splitter

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Valid game labels accepted; unknown label rejected; missing file → clear error; session id stable for same path; empty folder → empty manifest (or explicit error — pick one and lock it) |
| **System** | Temp dir with fake files named by folder-per-game (or CSV) → manifest row count/fields match; re-run is idempotent (same ids) |
| **Manual** | Once: point at a real personal-clip folder; spot-check a few rows |

**How to run (once implemented):** `pytest tests/unit/test_clip_catalog.py tests/system/test_clip_catalog.py`

## Ties to proposal

Data Processing: “per-frame metadata (video ID, channel, timestamp, quality tier) is stored” — catalog is the clip-level parent of that metadata.
