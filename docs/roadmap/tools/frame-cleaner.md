# Frame cleaner

**Stage:** 1 — Personal-clip data tools  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Filters extracted frames: drop mostly-black / heavily blurred frames, and remove near-duplicates via average-hash (roadmap “pHash”). Writes a kept manifest, reject log (with reasons), and summary counts.

## Why we need it

Loading screens, black frames, and near-identical samples waste capacity and can leak across splits. Cleaning early makes Stage 2–5 metrics meaningful.

## Inputs / outputs

| | |
|---|---|
| **In** | `frames_manifest.csv` / `.json` from the extractor |
| **Out** | Kept manifest + `rejects.csv`/`rejects.json` + `clean_summary.json`; optional `kept/` image copies |

## Known design choices (locked for v1)

- **Stack:** Python + Pillow only (no numpy/OpenCV required)
- Drop **black**: low luma mean **and** low std (`mean≤8`, `std≤4`)
- Drop **blur**: FIND_EDGES variance `< 400` (synthetic blur ~150; Valorant HUD frames ~2k+)
- **Near-dupes:** 8×8 aHash, Hamming distance `≤ 6` → duplicate (first frame wins)
- **Menus/HUDs kept** (D06) — no menu stripper
- **Non-game / lobby detector (D11):** **decided** — simple lobby/non-game score + threshold, validated on a hand-labelled sample (TA). Not coded yet; until then black/blur/dedupe + manual quarantine of lobby/desktop frames
- Reasons always logged (`black` / `blur` / `duplicate` / `missing_file`)

## CLI

```bash
gfc-clean-frames data/frames/valorant_smoke/frames_manifest.csv -o data/frames/valorant_smoke_cleaned
```

Flags: `--no-copy`, `--debug`, `--black-mean-max`, `--black-std-max`, `--blur-variance-min`, `--phash-size`, `--phash-max-distance`, `--skip-missing`.

### `--debug`

- Copies rejected frames to `output_dir/rejected/<reason>/` (kept on disk for visual audit)
- Duplicates named `…__dup_of_<matched_frame_id>…`
- `rejects.csv` includes `matched_frame_id`, `matched_path`, `hamming_distance`, metrics, `debug_path`

## Acceptance checks

- [x] Black synthetic → reject reason `black`
- [x] Blurry synthetic → `blur`
- [x] Near-duplicate pair → one kept, one `duplicate`
- [x] Manifest + reject log + summary written
- [x] Personal Valorant smoke: runs without mass-deleting gameplay frames
- [x] D11 rule defined (detector planned; interim manual quarantine)
- [ ] D11 detector implemented + validated on hand-labelled sample

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Black/blur heuristics; aHash distance; full `clean_frames` drop set; copy-kept paths |
| **System** | Synthetic folder + manifest → kept/reject counts + summary JSON |
| **Personal** | If `data/frames/valorant_smoke` exists, clean it (auto-skip otherwise) |

```bash
pytest tests/unit/test_frame_cleaner.py tests/system/test_frame_cleaner.py
pytest -m personal   # includes valorant smoke clean when present
```

## Ties to proposal

Data Processing: labelling/cleaning paragraph; contrast with related work that filters menus out.
