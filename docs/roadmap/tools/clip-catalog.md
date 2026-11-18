# Clip catalog

**Stage:** 1 — Personal-clip data tools  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Builds a table of every source video/clip: filesystem path, game label, channel/session id, and light metadata (duration, resolution, etc.). This is the inventory everything else reads from.

## Why we need it

Without a catalog, labels live in folder names or memory and break as soon as you add friends’ clips or public VODs. The interim write-up also needs reproducible “where did this frame come from?” answers (video id, channel, timestamp).

## Inputs / outputs

| | |
|---|---|
| **In** | `data/raw/` tree per [data-layout.md](../../data-layout.md) |
| **Out** | `clips.csv` + `clips.json` (one row per clip) → usually under `data/manifests/` |

## Known design choices

- Layout: `data/raw/<Game>/<source>/` — see [data-layout.md](../../data-layout.md)
- **Label UX (locked for v1):** game = top folder; source = next folder; filenames kept as-is
- Store enough ids to support **video/source-level splits** later (not frame-level)
- Personal clips: treat `<source>` (and later session, after normalize) as the split unit
- **Stack:** Python + pathlib; ffprobe for duration/width/height
- **Manifests:** CSV + JSON (same pattern as frame manifests; D20)
- **Paths:** absolute (supports external drives)
- **Empty raw:** empty catalog (not an error)
- **clip_id:** `Game/source/filename` (stable across re-runs)
- **Extensions:** `.mp4`, `.mkv`, `.webm`, `.mov`, `.avi`
- Unknown game folder → error; loose files not under `<Game>/<source>/` → ignored

### Schema (v1)

| Column | Meaning |
|---|---|
| `clip_id` | `Game/source/filename` |
| `path` | Absolute path to the video |
| `game` | Game folder name |
| `source` | Source/channel folder name |
| `filename` | Original filename |
| `duration_s` | Duration from ffprobe |
| `width` | Video width |
| `height` | Video height |

## Usage

```bash
gfc-catalog-clips                  # defaults: data/raw → data/manifests
gfc-catalog-clips data/raw -o data/manifests
python -m game_frame_classifier.clip_catalog data/raw -o data/manifests
```

## Acceptance checks

- [x] Point at a personal-clip folder → get a complete manifest
- [x] Every row has a valid game label and a resolvable path
- [x] Session/video id is stable enough for the splitter (`clip_id`)

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Valid game labels accepted; unknown label rejected; `clip_id` stable; empty folder → empty manifest; loose/non-video ignored |
| **System** | Temp dir with ffmpeg synthetic clip under `Valorant/edison/` → row count/fields match; re-run same ids; unreadable file → clear error |
| **Manual** | Once: point at a real personal-clip folder; spot-check a few rows |

**How to run:** `pytest tests/unit/test_clip_catalog.py tests/system/test_clip_catalog.py`

## Ties to proposal

Data Processing: “per-frame metadata (video ID, channel, timestamp, quality tier) is stored” — catalog is the clip-level parent of that metadata.
