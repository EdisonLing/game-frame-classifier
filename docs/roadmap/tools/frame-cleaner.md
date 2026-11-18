# Frame cleaner

**Stage:** 1 — Personal-clip data tools  
**Status:** implemented  

**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md)

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
- **Non-game / lobby detector (D11):** **decided** — simple lobby/non-game score + threshold, validated on a hand-labelled sample (review). Not coded yet; until then black/blur/dedupe + manual quarantine of lobby/desktop frames
- Reasons always logged (`black` / `blur` / `duplicate` / `missing_file`)

## Usage

### Manifest mode (single extract)

```bash
gfc-clean-frames data/frames/valorant_smoke/frames_manifest.csv -o data/frames/valorant_smoke_cleaned
python -m game_frame_classifier.frame_cleaner MANIFEST -o OUTPUT_DIR
```

Flags: `-o/--output-dir` (required), `--no-copy`, `--debug`, `--black-mean-max`, `--black-std-max`, `--blur-variance-min`, `--phash-size`, `--phash-max-distance`, `--skip-missing`.

### `--debug` (manifest)

- Copies rejected frames to `output_dir/rejected/<reason>/` (kept on disk for visual audit)
- Duplicates named `…__dup_of_<matched_frame_id>…`
- `rejects.csv` includes `matched_frame_id`, `matched_path`, `hamming_distance`, metrics, `debug_path`

## Slot mode (training pipeline)

Step 3 of the [training pipeline](../../training-pipeline.md). The single-manifest mode above stays for debugging one extract.

```bash
gfc-clean-frames --slots data/manifests/slots.csv
gfc-clean-frames --slots data/manifests/slots.csv --debug
gfc-clean-frames --slots data/manifests/slots.csv --data-root data
python -m game_frame_classifier.frame_cleaner --slots data/manifests/slots.csv
```

Flags: `--slots` (required for this mode), `--data-root` (default: parent of the manifests directory that holds `slots.csv`), `--debug`, and the same black / blur / aHash threshold flags as manifest mode. Do not pass a positional manifest or `-o` with `--slots`.

| | |
|---|---|
| **Reads** | `data/manifests/slots.csv` and `clips_index.csv` from [`gfc-derive-frames`](derive-frames.md); optional `data/manifests/quarantine.csv` |
| **Writes** | `data/manifests/slots_clean.csv/json`, `data/manifests/clean_summary.json` |
| **Next step** | [`gfc-split`](dataset-splitter.md) |

**Rules**

1. **One verdict per slot.** Black and blur are measured on the `full` image only, with the thresholds above (they were tuned at 256×144). All tiers of the slot (one for a quick-mode clip) are kept or rejected together, so a kept slot always has both images.
2. **Near-duplicates across a whole source.** Within one `(game, source)`, slots are visited in order of the clip's `recorded_start_utc` (empty last), then `clip_key`, then `bucket`. A slot whose aHash is within the Hamming limit of an already kept slot of that source is a `duplicate` of it. This catches overlapping instant-replay clips, not only repeats inside one clip. Different sources are never compared.
3. **Quarantine list.** `quarantine.csv` has columns `slot_id, reason, note`. Listed slots are rejected with reason `manual:<reason>` (for example `manual:lobby`, `manual:desktop`). This is the hand quarantine D11 calls for until the detector exists, kept as a file so it is repeatable.
4. **Nothing is deleted or copied.** Rejected slots stay on disk and in the table; they are candidate material for the unknown class later (D24).
5. Every run recomputes the whole table. Order is deterministic, so the same inputs give the same output. When footage recorded earlier than existing clips arrives later, which twin of a duplicate pair is kept can change; split assignment is per clip, so this only changes which slots of an already assigned clip are used.

**Working default (dedupe scope).** Comparing across a whole source is the safe choice for overlapping clips, but in games with static views (League of Legends, Minecraft) an 8×8 hash at distance 6 may also catch frames that are genuinely different. Alternative: compare within a clip plus only clips whose recording times overlap or are within the session gap. Revisit when `clean_summary.json` shows a duplicate rate far above the other games. The comparison is quadratic in the slots of one source, which is well under a minute at 10,000 slots in pure Python.

**`slots_clean.csv`** = every column of `slots.csv` plus:

| Column | Notes |
|---|---|
| `keep` | `true` / `false` |
| `reject_reason` | empty, `black`, `blur`, `duplicate`, `missing_file` (the `full` image, or a non-empty `path_low`, is not on disk), `manual:<reason>`; later `non_game` (D11 detector) |
| `dup_of` | `slot_id` of the kept twin for duplicates |
| `luma_mean`, `luma_std`, `edge_var` | Measured values on the `full` image |
| `ahash` | 16 hex digits |

**`clean_summary.json`:** thresholds used, counts kept and rejected per reason overall and per game and per source.

`--debug` writes a contact folder `data/frames/_rejected/<reason>/` with copies of the rejected `full` images for a visual check.

**Slot-mode tests**

| Kind | Cases |
|---|---|
| **Unit** | Verdict from `full` applies to both tiers; duplicate across two clips of one source is caught; identical frames in two different sources are both kept; quarantine row rejects with `manual:<reason>`; visiting order is independent of row order in the input |
| **System** | Synthetic derived tree + `slots.csv` → `slots_clean.csv` with expected `keep` and reasons; rerun is byte-identical; no file under `data/frames/` is modified without `--debug` |

## Acceptance checks

- [x] Slot mode: `slots_clean.csv` written; every kept slot has both tier files; rerun identical
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
| **Unit** | Black/blur heuristics; aHash distance; full `clean_frames` drop set; copy-kept paths; slot verdict from `full`; cross-clip same-source dupe; different-source twins kept; quarantine `manual:<reason>`; visit order independent of CSV row order |
| **System** | Synthetic folder + manifest → kept/reject counts + summary JSON; synthetic derived tree + `slots.csv` → `slots_clean` with expected reasons; slot rerun byte-identical; frames untouched without `--debug` |
| **Personal** | If `data/frames/valorant_smoke` exists, clean it (auto-skip otherwise) |

```bash
pytest tests/unit/test_frame_cleaner.py tests/system/test_frame_cleaner.py
pytest -m personal   # includes valorant smoke clean when present
```

## Ties to proposal

Data Processing: labelling/cleaning paragraph; contrast with related work that filters menus out.
