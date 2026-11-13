# Frame extractor

**Stage:** 1 — Personal-clip data tools  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Uses ffmpeg to pull still frames from a video at a fixed time interval, resizes them to the model input size, writes image files, and records per-frame metadata (source video, timestamp, path, game label).

## Why we need it

The model is a **single-frame** classifier. Clips are the raw material; this tool is the bridge from video → labelled images. Same tool is reused when we later add public VODs (Stage 3).

## Inputs / outputs

| | |
|---|---|
| **In** | Video path + game label (+ optional video id / max duration) |
| **Out** | Frame images + `frames_manifest.csv` / `frames_manifest.json` |

## Known design choices (locked for v1)

- **Stack:** Python + `subprocess` to ffmpeg/ffprobe (no ffmpeg-python binding)
- Extract with **ffmpeg** `fps=1/{interval}`, default interval **5 s**
- **Resize during extract:** `scale=256:144`
- **Image format:** JPEG (`-q:v 2`) for disk scalability
- Timestamps: `0, 5, 10, …` while `t < duration` (see `planned_timestamps`)
- Game label passed explicitly for now (catalog can feed this later)
- Optional `max_duration_s` for smoke / partial runs

## CLI

```bash
# from repo root (package installed editable)
gfc-extract-frames path\to\clip.mp4 -o data/frames/my_clip --game Valorant

# or
python -m game_frame_classifier.frame_extractor path\to\clip.mp4 -o data/frames/my_clip --game Valorant
```

Useful flags: `--video-id`, `--interval`, `--width`, `--height`, `--ext`, `--max-duration`, `--debug`.

### `--debug`

Writes under `output_dir/debug/`:

- `extract_debug.json` — duration, planned timestamps, ffmpeg command, count notes
- `extract_debug_frames.csv` — per-frame planned ts, raw name → final name
- `raw/` — copies of ffmpeg `frame_XXXXX.jpg` **before** rename (audit trail)

## Module API

`game_frame_classifier.frame_extractor.extract_frames(...)` → `list[FrameRecord]`

## Acceptance checks

- [x] Synthetic 15 s video → 3 frames at 0/5/10, size 256×144
- [x] Manifest CSV/JSON written
- [x] Personal Valorant drop smoke (trimmed) passes
- [ ] Full personal clips batch once catalog exists

## Testing

**Method (scalable + reliable):**

1. **Unit** — pure timestamp/filename math; no ffmpeg; always runs in CI  
2. **System / synthetic** — tests generate a tiny CFR color MP4 in `tmp_path` via ffmpeg lavfi (`make_color_video`). No binaries committed. Assert count, timestamps, size, manifests.  
3. **Personal smoke** — `@pytest.mark.personal`: if `GFC_TEST_VIDEO` or repo-root Valorant MP4 exists, **stream-copy trim** to ~20 s then extract. Skips cleanly when absent. Never requires committing personal media.

| Kind | Cases |
|---|---|
| **Unit** | `planned_timestamps`; `frame_filename` sorting/determinism; bad interval rejected |
| **System** | 15 s synth → 3 frames; `max_duration` caps; missing file raises; dims 256×144 |
| **Personal** | Trimmed Valorant smoke → ≥3 frames, correct label/dims/manifest |

**How to run:**

```bash
pytest                       # all (personal auto-skips if no clip)
pytest -m "not personal"     # CI-safe subset
pytest -m personal           # local smoke with dropped clip / GFC_TEST_VIDEO
```

## Ties to proposal

Data Processing: “Frames will be extracted with ffmpeg at a fixed interval (one frame every 5 s)… Frames are resized to 256×144.”
