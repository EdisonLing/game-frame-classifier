# Frame Export Kit (clips → frames zip)

**Stage:** 1 / volume (contributor data)  
**Status:** v1 implemented; release checklist (§13) pending  
**Back to:** [ROADMAP.md](../ROADMAP.md)  
**Decisions:** [D25](../../design-decisions.md) (pack), [D26](../../design-decisions.md) (frame sources + one extraction path), [D27](../../design-decisions.md) (derive to 256×144), D04 / D22 (tiers), D21 (JPEG)

A zip I send to friends once. They extract it, drag a folder of clips onto one file, pick the game, and get back a zip of frames to send me. No Python, no ffmpeg install, no settings to understand. Their video files never leave their PC.

The frames they send are a **source of truth** in my pipeline (the masters are gone), so the pack keeps every piece of metadata I can't recover later. This page is the full contract: friend UX, configuration, processing, output format, metadata schemas, safety, packaging, and tests.

---

## 1. Goals and non-goals

**Goals**

| # | Goal |
|---|---|
| G1 | Works out of the box on a stock Windows 10 22H2+ / 11 PC. Nothing to install. |
| G2 | One action per folder of clips: name asked once (remembered), game asked per run. |
| G3 | Output is ingest-ready and self-describing: game, source, clip identity, timestamps, tiers, probe metadata, recipe, tool and ffmpeg versions. |
| G4 | Same recipe as my own clips (D22 video CRF, then stills), produced by the **same code** (D26), so friend data and personal data are interchangeable. |
| G5 | Future-proof within reason: native-resolution stills so I can change train size, aspect policy, HUD crops (D15) or augmentation later without asking again. |
| G6 | Safe and respectful: read-only on their clips, no network, no personal machine details, explicit consent, ingest-side zip validation. |

**Non-goals (v1)**

- No cleaning, lobby filtering, or HUD crops on their PC (I do that after ingest).
- No macOS / Linux build.
- No GUI, installer, auto-update, or upload. They send the zip however they like.
- No medium tier by default (D04). No audio, no video in the output.

---

## 2. Friend user flow

1. **Get the pack.** I send `GFC-FrameExportKit-v1.zip` (about 120 MB, mostly ffmpeg). They right-click → *Extract All*. Running from inside the zip is detected and explained.
2. **Start.** Either drag a folder of clips onto `START HERE.bat`, or double-click it and drag the folder into the window when asked.
3. **First run only:** a short notice of what is collected, then three prompts, saved to `config/user.json`:
   - name / handle (becomes the source id)
   - "OK to process your clips into frames for this project?" (default yes)
   - "OK if a few of your frames appear in my report or README?" (default yes)
4. **Scan summary.** Clip count, total duration, resolutions, files skipped and why, estimated output size and time, free disk space. Over the footage budget (default 3 h per game), it picks clips spread across recording days and says to run again later for more (§5.2a).
5. **Game prompt.** Numbered list of the six games plus *Other*. Pre-selected when folder/file names agree on one game; a warning (and confirmation) when names suggest a different game than the one picked.
6. **Optional notes** (Enter skips each): colourblind mode, graphics preset, one game-specific question from the recipe (for example Minecraft shaders), free text.
7. **Confirm and run.** Per-clip progress with percentage and a measured ETA after the first clip. Closing the window or Ctrl+C stops cleanly; running again on the same folder resumes.
8. **Done.** The zip path and size are printed and Explorer opens with the zip selected. Clips already sent in an earlier run are skipped by default.

Example session (abridged):

```text
GFC Frame Export Kit v1.0.0
Drag the folder with your clips into this window, then press Enter:
> "D:\Videos\NVIDIA\VALORANT"

Found 14 videos (2 h 11 min, 2560x1440). Skipped 1: notes.txt (not a video).
Estimated output: about 1.1 GB. Free space: 212 GB. Already sent before: 0.

Which game are these clips from?  (folder name suggests: Valorant)
  1 Valorant   2 League of Legends   3 CS2   4 Minecraft
  5 Overwatch 2   6 Marvel Rivals   7 Other
[1]: 

Optional (press Enter to skip): colourblind mode? [none]: 
...
Start? [Y/n]: 
[ 1/14] VALORANT 2026.11.02 - 21.14.08.03.DVR.mp4   100%   26 slots   (ETA 38 min)
...
Done. 12 clips OK, 1 failed (see log), 1 skipped.
Send this file: output\GFC_Valorant_alex_20261120-2214.zip  (1.04 GB)
Discord's free limit is 10 MB, so use Google Drive, OneDrive or WeTransfer and send me the link.
Press Enter to close.
```

Power-user flags (also used by me for testing and for my own clips):

```text
START HERE.bat <folder> [--game Valorant] [--other-name Apex_Legends] [--compact]
               [--budget-hours N] [--yes] [--include-packed] [--no-zip] [--output <dir>] [--no-open]
```

---

## 3. What I ship (package layout)

```text
GFC-FrameExportKit-v1/
  START HERE.bat                 # launcher (drag a folder onto it)
  README.txt                     # one page, plain language (template in §14)
  app/                           # pure-stdlib Python source (readable)
    gfc_frame_export.py          # entry point
    game_frame_classifier/       # sourcing/ + frame_export/ packages, copied from the repo
  runtime/                       # Python 3.13.x amd64 embeddable distribution
    python.exe, python313.dll, python313.zip, vcruntime140.dll, python313._pth, ...
  bin/
    ffmpeg.exe                   # pinned static GPL build (x264 + dav1d + zimg)
    ffprobe.exe
  config/
    recipe.json                  # extraction recipe (I control; §4.1)
    user.json                    # created on first run (§4.2)
    history.json                 # created on first run: clip hashes already packed
  LICENSES/                      # FFmpeg (GPL) license + source link, Python (PSF) license
  output/                        # created on first run: zips + resumable work dirs
```

**Why embeddable Python + .bat instead of a PyInstaller exe:** `python.exe` is signed by the PSF and the app is plain text, so antivirus false positives and SmartScreen friction are far lower than an unsigned PyInstaller bootloader, and I can patch a `.py` without rebuilding. The embeddable zip already ships `vcruntime140.dll`; the app is stdlib-only, so nothing else is needed.

**Launcher (`START HERE.bat`):**

```bat
@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo This folder is incomplete. Right-click the zip, choose "Extract All", then run START HERE.bat from the extracted folder.
  pause
  exit /b 1
)
"runtime\python.exe" -B -X utf8 "app\gfc_frame_export.py" %*
echo.
pause
```

`runtime\python313._pth` lists `python313.zip`, `.` and `..\app`, which puts the app on `sys.path` and keeps the interpreter isolated from any system Python or `PYTHON*` variables. Paths with `&` or `^` and no spaces can break `.bat` argument passing; the in-window drag prompt is the fallback and handles every path.

---

## 4. Configuration

Two files, so I can ship an updated recipe without touching a friend's name or consent.

### 4.1 `config/recipe.json` (shipped by me)

```json
{
  "schema": "gfc.recipe/1",
  "recipe_id": "2026-11-16a",
  "interval_s": 5,
  "include_full": true,
  "crf_list": "45",
  "x264_preset": "veryfast",
  "jpeg_qscale": 2,
  "frame_mode": "native",
  "compact_size": [256, 144],
  "hdr_policy": "tonemap_hable_v1",
  "derive": { "aspect": "pad_16x9", "aspect_tolerance": 0.01, "scale_flags": "bicubic" },
  "video_extensions": [".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".flv", ".ts"],
  "min_duration_s": 1.0,
  "footage_budget_min": 180,
  "budget_selection": "spread_days_v1",
  "games": ["Valorant", "League_of_Legends", "CS2", "Minecraft", "Overwatch_2", "Marvel_Rivals"],
  "questions": {
    "all": [
      { "key": "colourblind_mode", "prompt": "Colourblind mode", "choices": ["none", "deuteranopia", "protanopia", "tritanopia", "unsure"], "default": "unsure" },
      { "key": "graphics_preset", "prompt": "Graphics quality", "choices": ["low", "medium", "high", "ultra", "mixed", "unsure"], "default": "unsure" }
    ],
    "Valorant":  [ { "key": "enemy_highlight", "prompt": "Enemy highlight colour", "choices": ["red", "yellow", "purple", "unsure"], "default": "unsure" } ],
    "CS2":       [ { "key": "stretched", "prompt": "Stretched / 4:3 resolution", "choices": ["yes", "no", "unsure"], "default": "unsure" } ],
    "Minecraft": [ { "key": "visual_mods", "prompt": "Shaders or texture packs", "choices": ["none", "texture_pack", "shaders", "both", "unsure"], "default": "unsure" } ]
  }
}
```

| Field | Meaning | Validation |
|---|---|---|
| `interval_s` | Seconds per sampling bucket (§5.4) | 0.5 ≤ x ≤ 60 |
| `include_full` | Extract a tier from the original video | bool |
| `crf_list` | Comma-separated H.264 CRFs; each becomes a tier `crf<N>` (re-encode the video, then extract). Accepts `"45"`, `"38,45"` or a JSON list | ints 1–51, deduplicated, sorted |
| `x264_preset` | libx264 preset for the CRF re-encode (same as repo quality encoder) | x264 preset name |
| `jpeg_qscale` | mjpeg `-q:v` for every still (D21) | 2–31 |
| `frame_mode` | `native` (default) or `compact` (256×144 via §5.7) | enum |
| `hdr_policy` | Tone-map HDR sources to SDR before every tier (§5.3) | enum |
| `derive` | Aspect + scaler used for compact mode; identical to my pipeline's derive step (D27) | — |
| `footage_budget_min` | Max minutes of footage processed per run (one run = one game); `0` = no limit. Extra clips wait for the next run (§5.2a) | int ≥ 0 |
| `budget_selection` | How clips are picked when over budget | enum |
| `questions` | Optional per-run notes; data-driven so I can change them without code | — |

At least one tier must exist (`include_full` or a non-empty `crf_list`). The tool refuses to start on an invalid recipe and says which field is wrong. Every pack embeds the resolved recipe, so if a friend edits this file, ingest still knows exactly what was produced.

**Defaults and why:** interval 5 s (proposal sampling), tiers `full` + `crf45` (D04: medium 38 is docs-only), native frames (D25), budget 3 h per game per run (about 2,160 usable frames; one person's share of a game rarely needs more, and big libraries stay at roughly 1–2.5 h of processing on a typical PC and a ~1.5 GB zip at 1440p). Halving `interval_s` to 2.5 would be a strict superset of the 5 s samples (even buckets pick the same frames), at 2× size; not the default.

### 4.2 `config/user.json` (created on first run)

```json
{
  "schema": "gfc.user/1",
  "contributor_id": "3b8f6f0e-6c1e-4a52-9d0e-1a7b2f8c4d21",
  "handle": "alex",
  "consent_data_use": true,
  "consent_public_examples": false,
  "consent_utc": "2026-11-20T03:10:02Z",
  "last_game": "Valorant",
  "frame_mode_override": null
}
```

- `handle` is normalised to `[a-z0-9_]{1,24}` (lowercase, spaces and dashes to `_`, other characters dropped); the prompt repeats until non-empty. It becomes the source id `contributor_<handle>` at ingest.
- `contributor_id` is a random UUID created once; it ties packs to one person even if the handle changes, and lets me delete someone's data on request.
- **Precedence:** command-line flag > `user.json` override > `recipe.json`.

### 4.3 `config/history.json`

`{ "<quick_id>": { "clip_sha256": "...", "pack_id": "...", "game": "Valorant", "packed_utc": "..." } }`, appended after each successful zip. Clips already present are skipped unless `--include-packed`. If a clip was packed before under a different game, the tool warns and asks. Clips left out by the footage budget are not added, so the next run picks from them.

---

## 5. Processing

### 5.1 Discovery

- Walk the chosen folder **recursively**; never follow symlinks or junctions; skip the pack's own folder if it sits inside.
- Candidate = extension in `video_extensions` (case-insensitive). Other files are listed as skipped (`not_video`).
- A folder containing `session.mpd` is a Steam Game Recording (fragmented `.m4s`, not a playable file). Skip it as `steam_recording` and tell the friend to export the clip to MP4 in Steam first.
- Paths longer than 259 characters are skipped as `path_too_long` with the advice to move the folder closer to the drive root.
- **Quick id** for every candidate: `sha256(file size ‖ first 1 MiB ‖ last 1 MiB)[:16]`. Cheap even for hundreds of GB (full hashing would read every byte). Quick ids in `history.json` are skipped as `already_packed`; equal quick ids in one run mark duplicates.
- **Full SHA-256** (1 MiB streaming) only for clips selected for processing (§5.2a), right before extraction. Identical files in one run are processed once; extra paths are recorded as `aliases`.

### 5.2 Probe

`ffprobe -v error -print_format json -show_format -show_streams -show_chapters <file>`

- **Stream choice:** video streams with `disposition.attached_pic != 1`; largest `width × height`; lowest index on ties. All ffmpeg calls use `-map 0:<index>`.
- **Failures:** no output / no video stream → `unreadable` / `no_video`. Duration < `min_duration_s` → `too_short`.
- **Nominal fps:** `avg_frame_rate` if within 10–240, else `r_frame_rate` if within 10–240, else 60. `vfr = (avg_frame_rate != r_frame_rate)`.
- **HDR:** `color_transfer ∈ {smpte2084, arib-std-b67}`.
- **Odd dimensions:** if width or height is odd, every tier gets `crop=trunc(iw/2)*2:trunc(ih/2)*2` (x264 4:2:0 needs even sizes; applying it to all tiers keeps them pixel-aligned). Recorded as `even_cropped`.
- The probe JSON is saved per clip after removing `format.filename` (absolute path). Tags are kept.
- Every candidate is probed (about 50 ms each) because the budget needs durations; a progress counter shows during the scan.

### 5.2a Footage budget (`spread_days_v1`)

Friends with large libraries would otherwise face many hours of processing and a huge upload for far more frames than one person's share of a game. Each run processes at most `footage_budget_min` of footage (default 180), spread across as many recording days as possible.

1. **Eligible** = probed OK, not `already_packed`, not a duplicate. If their total duration ≤ budget (or budget is `0`), take all.
2. **Recording start** per clip = `recorded_start_utc` (§5.2b). **Day** = local calendar date of that start.
3. Order days oldest first. Within a day, order clips by quick id (deterministic, effectively random).
4. **Round-robin:** repeatedly pass over the days, offering each day's next clip. Take it if the running total + its duration ≤ budget; otherwise skip it for this run and keep going (shorter clips may still fit). Stop when no remaining clip fits.
5. If nothing fits because every clip is longer than the budget, take the single shortest clip.
6. Unselected clips are listed in `clips.csv` as `skipped` / `over_budget` with quick id, probe fields and all timing fields (no SHA-256) and are not written to `history.json`. Running the tool again on the same folder repeats the spread over what is left.

When over budget, the scan summary says so and allows a one-off override (not saved):

```text
Found 412 videos (61 h 20 min). This run will process 3 h 0 min: 38 clips across 27 days.
Estimated time: about 2 h. Estimated output: about 1.5 GB.
Run it again later on the same folder to send more.
Press Enter to continue, or type the hours to process this time (0 = all): 
```

`--budget-hours N` sets the same override from the command line. Whole clips only: a clip is never cut to fit.

### 5.2b Recording time

Dates let me cross-reference clips later with game patches and seasons, sessions (D01 splits), and settings eras. File times are fragile (downloads reset them; copies reset the created time), so every clip that probes OK gets all the evidence plus one best estimate. Converting local times on the friend's PC uses its own timezone and daylight-saving rules for that date, which ingest could not reconstruct later.

| Field | Source |
|---|---|
| `file_mtime_utc`, `file_mtime_local` | File modified time (local = ISO 8601 with that date's UTC offset) |
| `file_created_utc` | File created time (often the copy time; evidence only) |
| `container_creation_utc` | `format.tags.creation_time`, when the recorder writes it |
| `filename_datetime_local` | First timestamp parsed from the filename or parent folders (patterns below), local time with offset |
| `recorded_start_utc` | Best estimate: container creation time, else filename time, else modified time − duration |
| `recorded_start_source` | `container`, `filename` or `mtime` |

Filename patterns (first match wins, digits validated as a real date between 2010 and today + 1 day):

| Pattern | Typical source |
|---|---|
| `YYYY.MM.DD - HH.MM.SS` | NVIDIA App / ShadowPlay |
| `YYYY-MM-DD HH-MM-SS` / `YYYY-MM-DD_HH-MM-SS` | OBS, Windows Game Bar |
| `YYYY.MM.DD-HH.MM` | Valorant replays |
| `YYYYMMDD_HHMMSS` / `YYYYMMDD-HHMMSS` | Steam, Medal, ShareX, phones |
| `YYYY-MM-DD` (date only) | Folder names; time left empty |

Container times flagged as obviously wrong (before 2010, or `1970`/`1904` epochs) are ignored. The pack manifest also records the PC's timezone (§6.2). Game patch or season is not looked up on the friend's PC; I derive it from `recorded_start_utc` after ingest.

### 5.3 Pre-filter (same for every tier)

`PRE` = optional HDR tone-map, then optional even-crop:

```text
zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p
```

HDR clips are tone-mapped **before** both the full extract and the CRF encode, because the streams this models are SDR. Recorded as `hdr` / `tonemapped`; ingest can exclude them if they look off.

### 5.4 Sampler (`bucket_v1`)

Buckets of `interval_s` seconds on the clip's own timeline; one frame per bucket: **the first decoded frame whose timestamp falls in that bucket**. ffmpeg's filter `t` is already start-relative (container start offsets removed), so bucket 0 starts at the first frame.

```text
OFF  = 0.5 / nominal_fps          # puts bucket edges half a frame away from CFR frame times
EXPR = gte(t,0)*(isnan(prev_selected_t)+gt(floor((t+OFF)/I),floor((prev_selected_t+OFF)/I)))
```

Extract command (one per tier source):

```text
ffmpeg -hide_banner -nostdin -loglevel info -y -i <src> -map 0:<v> -an -sn -dn
       -vf "[PRE,]select='EXPR',showinfo"
       -fps_mode passthrough -c:v mjpeg -q:v <jpeg_qscale> -start_number 0
       -progress pipe:1 <stage>/<tier>/%06d.jpg
```

- `showinfo` prints the **actual** `pts_time` of each selected frame (stderr); the n-th line maps to file `%06d` n. Line count must equal file count, else the clip fails.
- `bucket = floor((pts_time + OFF) / I)` computed in Python from the parsed time.
- If zero frames are selected on a clip with duration > 0, retry once with `-fflags +genpts`; still zero → `no_timestamps`.
- Works for VFR captures and gaps (verified on a synthetic VFR clip with dropped frames, a 1.7 s gap and a 2.7 s start offset).

This replaces the repo's current `fps=1/5` + computed timestamps (which assume CFR). Both sides use the same sampler (D26).

### 5.5 Tiers

| Tier id | Source | Commands |
|---|---|---|
| `full` | Original file | §5.4 on `<file>` with `PRE` |
| `crf<N>` | Original re-encoded at CRF N | Encode, then §5.4 on the temp file with no `PRE` (already applied) |

CRF encode (D22; same parameters as the repo quality encoder):

```text
ffmpeg -hide_banner -nostdin -loglevel error -y -i <file> -map 0:<v> -an -sn -dn [-vf PRE]
       -c:v libx264 -preset <x264_preset> -crf <N> -pix_fmt yuv420p
       -fps_mode passthrough -progress pipe:1 <stage>/tmp_crf<N>.mp4
```

- Software libx264 on purpose for **contributor packs** (D28): not NVENC / AMF / QuickSync. Hardware encoders differ by vendor and generation and have no true CRF, so a GPU `crf45` tier would carry a per-friend encoder signature (a source confound). x264 with a pinned build gives the same artifacts on every PC. The cost is time (§8). **Personal** `gfc-make-sources` may later offer an **AMF toggle** for speed on my machine; that path is local-only and must be recorded in the manifest — it is not the friend default.
- `-fps_mode passthrough` keeps frames 1:1, so the same sampler picks the same frames in every tier. The temp is `.mp4` (exact timestamps; `.mkv` rounds to 1 ms). Deleted after extraction.
- The x264 build string (`x264 - core NNN rNNNN ...`) is read from the first 64 KiB of the temp file and recorded.

### 5.6 Alignment check

Tiers are paired per **slot** (one sampled moment of one clip):

1. If counts match and every `|pts_full − pts_crf| ≤ 0.5 / nominal_fps`, pair by order.
2. Otherwise pair by bucket number; buckets missing from any tier are dropped and counted in `unpaired_dropped`.

Only complete slots (every tier present) are kept. `max_align_err_s` is recorded per clip.

### 5.7 Compact mode

Extract natively first (§5.4–5.6), then run the **derive** step (D27) on each staged image and delete the natives:

1. If `|w/h − 16/9| > aspect_tolerance × 16/9`: pad to 16:9 with black, centred.
2. `scale=256:144:flags=bicubic`, JPEG `-q:v <jpeg_qscale>`.

Batched per tier folder as one image-sequence ffmpeg call, falling back to one ffmpeg call per image on error. My pipeline runs the exact same function on native frames, so compact packs and native packs end up identical at train size. Compact packs are flagged `frame_mode: compact` and cannot feed higher-resolution work (other train sizes, D15 high-res HUD crops).

### 5.8 Per-clip finish

- Rename staged files to `<clip_key>_<tier>_b<bucket:06d>.jpg` under `frames/<clip_key>/<tier>/`.
- For each image: bytes, SHA-256, and width/height read from the JPEG SOF header.
- Write `done.json` in the clip's work dir (resume marker).

`clip_key = "c" + clip_sha256[:12]`: content-addressed, ASCII, short (keeps paths well under Windows limits), and identical across friends for the same file.

### 5.9 Clip status

| Status | Meaning |
|---|---|
| `ok` | All tiers extracted and aligned; ≥ 1 complete slot |
| `failed` | ffmpeg / probe error mid-clip; staged files removed; error text kept |
| `skipped` | `not_video`, `steam_recording`, `path_too_long`, `unreadable`, `no_video`, `too_short`, `already_packed`, `duplicate_in_run`, `over_budget` |

A failed clip never stops the run.

---

## 6. Output pack

### 6.1 Zip

- Name: `GFC_<Game>_<handle>_<YYYYMMDD-HHMM>.zip` (friend's local time; UTC is in the manifest). `Other` uses `GFC_Other-<other_name>_...`.
- Single root folder: `gfc_pack_<pack_id[:8]>/`.
- **Every entry `ZIP_STORED`** (JPEGs don't compress; stored entries make bomb-style ratios impossible), Zip64 enabled, ASCII names only.
- Written as `.zip.part`, re-opened and verified (entry count, sizes, CRC via `testzip()`), then renamed. The work dir is deleted only after verification.

```text
gfc_pack_6f1c0e5e/
  pack_manifest.json
  clips.csv            clips.json
  frames.csv           frames.json
  probe/<clip_key>.json
  frames/<clip_key>/full/<clip_key>_full_b000000.jpg
  frames/<clip_key>/crf45/<clip_key>_crf45_b000000.jpg
  run_log.txt
```

CSV + JSON side by side (D20). All paths inside manifests are relative to the pack root with forward slashes.

### 6.2 `pack_manifest.json`

```json
{
  "schema": "gfc.pack/1",
  "pack_id": "6f1c0e5e-2b7d-4c55-8a1e-0d9b3c7a5f10",
  "created_utc": "2026-11-20T03:44:12Z",
  "tool": { "name": "gfc-frame-export", "version": "1.0.0", "source_commit": "abc1234" },
  "recipe": { "...": "resolved recipe.json with crf_list as a list, plus sampler: bucket_v1" },
  "ffmpeg": { "ffmpeg_version": "n8.1.x-...", "ffprobe_version": "n8.1.x-...", "build": "bundled", "x264_core": "x264 - core 165 r3222 ..." },
  "host": { "os": "Windows-10.0.26100", "cpu_count": 16, "python": "3.13.x", "tz_name": "Eastern Standard Time", "utc_offset_min": -300 },
  "contributor": { "handle": "alex", "contributor_id": "3b8f...", "consent": { "data_use": true, "public_examples": false, "acknowledged_utc": "2026-11-20T03:10:02Z" } },
  "game": { "label": "Valorant", "other_name": null },
  "notes": { "colourblind_mode": "none", "graphics_preset": "high", "game_specific": { "enemy_highlight": "red" }, "free_text": "" },
  "input": { "files_seen": 15, "videos_found": 14, "clips_ok": 12, "clips_failed": 1, "clips_skipped": 1, "input_bytes": 21474836480, "input_duration_s": 7860.4,
             "footage_budget_min": 180, "eligible_duration_s": 7860.4, "selected_duration_s": 7860.4, "over_budget_clips": 0 },
  "output": { "tiers": ["full", "crf45"], "frame_mode": "native", "slots": 1560, "images": 3120, "file_count": 3134, "uncompressed_bytes": 1116684288 },
  "timing": { "wall_s": 2412.7 }
}
```

`output.uncompressed_bytes` and `file_count` describe every file in the pack except `pack_manifest.json` itself; ingest checks them before extracting. No hostname, username or absolute path appears anywhere. `ffmpeg.build` is `bundled` in a contributor pack (`env` or `path` when run from a repo checkout).

### 6.3 `clips.csv` / `clips.json` (one row per input file)

| Column | Notes |
|---|---|
| `clip_key`, `clip_sha256`, `quick_id` | Identity; dedupe across friends and runs (`clip_key` / `clip_sha256` empty for `over_budget`) |
| `status`, `status_detail` | §5.9 |
| `original_filename`, `original_relpath`, `aliases` | Relative to the chosen folder; `aliases` = other paths with the same hash |
| `file_bytes` | Source size (size-savings tracking) |
| `file_mtime_utc`, `file_mtime_local`, `file_created_utc`, `container_creation_utc`, `filename_datetime_local`, `recorded_start_utc`, `recorded_start_source` | Recording time evidence + best estimate (§5.2b), for sessions (D01), game patch / season, settings eras; lost forever once files move, so captured here |
| `duration_s`, `start_time_s` | Container duration and start offset |
| `container`, `video_codec`, `profile`, `pix_fmt`, `bit_depth`, `bitrate_bps`, `encoder_tag` | Source quality and recorder evidence |
| `width`, `height`, `sar`, `rotation` | Native geometry (aspect policy is decided later) |
| `avg_fps`, `r_fps`, `nominal_fps`, `vfr` | |
| `color_range`, `color_space`, `color_transfer`, `color_primaries`, `hdr`, `tonemapped`, `even_cropped` | |
| `audio_streams` | Count only |
| `label_hint`, `label_hint_conflict` | Game guessed from names (§9); conflict = differs from chosen game |
| `expected_slots`, `slots`, `unpaired_dropped`, `max_align_err_s` | Sampling QA |
| `x264_core`, `wall_s` | |

### 6.4 `frames.csv` / `frames.json` (one row per image)

| Column | Example |
|---|---|
| `image_id` | `c1a2b3c4d5e6f:b000012:crf45` |
| `slot_id` | `c1a2b3c4d5e6f:b000012` (tier-agnostic; the unit for D04 half-full / half-low tier assignment) |
| `clip_key` | `c1a2b3c4d5e6f` |
| `tier`, `crf` | `crf45`, `45` (`full` → `0`) |
| `bucket`, `target_time_s`, `pts_time_s` | `12`, `60.0`, `60.016667` |
| `rel_path` | `frames/c1a2b3c4d5e6f/crf45/c1a2b3c4d5e6f_crf45_b000012.jpg` |
| `width`, `height`, `bytes`, `sha256` | |

### 6.5 `run_log.txt`

Timestamped steps, ffmpeg commands and stderr tails for failures, with the chosen folder replaced by `<input>` and the user profile path by `%USERPROFILE%`.

---

## 7. Keep vs lose

**Kept** (sufficient to use the frames as sources of truth): §6.2–6.4 above, specifically game label, stable source and contributor ids, consent, content hash, original names, recording time (all evidence + best estimate + timezone), full probe, native-resolution stills for every tier, actual timestamps, slot pairing, recipe and tool/ffmpeg/x264 versions, sizes and hashes for every image.

**Accepted losses**

| Lost | Why acceptable | If ever needed |
|---|---|---|
| Video timeline, audio, motion | Single-frame classifier (D07); clip tagging uses sampled frames | Out of scope |
| Frames between samples | 1 per 5 s is the design; denser = near-duplicates | Raise `interval_s` before sending |
| Other CRFs / bitrates / pre-encode downscales | Need the video | Run those studies on my personal masters |
| Cleaning decisions | Done after ingest so they stay revisable (D11) | — |
| Exact pre-tone-map HDR pixels | Model targets SDR streams | Exclude `hdr` clips |

---

## 8. Size and time

Measured on 15 min of real gameplay; full numbers, timing and method in [handoff-sizes.md](../../handoff-sizes.md). Every pack also records its own input and output bytes.

| Source | Per slot (full + crf45) | MiB / footage min | % of an NVIDIA "High" 60 fps recording | Time per footage min (fast 8-core) |
|---|---:|---:|---:|---:|
| Compact 256×144 | 25 KiB | 0.3 | 0.25 % (vs 1080p) | same as native |
| 1080p | 466 KiB | 5.5 | 4.7 % | 12 s |
| 1440p | 716 KiB | 8.4 | 4.1 % | 22 s |
| 2160p | 1,295 KiB | 15.2 | 4.2 % | 51 s |

Zip ≈ unzipped (stored JPEGs).

**Disk check:** before starting and before each clip, require free space ≥ 2.2 × the estimated output of what remains (staged frames and the zip coexist briefly), using `0.15 bytes/pixel/image` (`15 KB` per image in compact mode). Not enough → stop with a clear message; completed clips stay resumable.

**Time:** about 75 % is the x264 re-encode at native resolution. Measured 12 / 22 / 51 min per footage hour at 1080p / 1440p / 4K (60 fps H.264) on a fast 8-core; expect about 2× on a typical 6-core, more on older laptops, 2× for 120 fps sources. The tool shows a measured ETA after the first clip, runs ffmpeg at below-normal priority, and states that the PC stays usable but fans may spin up.

---

## 9. Robustness and edge cases

| Case | Handling |
|---|---|
| VFR captures (NVIDIA, OBS, Game Bar) | Timestamp-based sampler; actual `pts_time` recorded |
| Non-zero start time | Filter time is start-relative; `start_time_s` recorded |
| HDR (PQ / HLG) | Tone-mapped before every tier; flagged |
| 10-bit SDR HEVC / AV1 | Decoded and converted to 8-bit; AV1 via dav1d |
| Odd dimensions | Even-crop on every tier; flagged |
| Ultrawide, 4:3 stretched, any aspect | Stored as-is (native); aspect policy applied later (D27) |
| Attached cover art / extra streams | Stream choice in §5.2 |
| Corrupt or crash-truncated files | Probe failure → skipped; mid-decode error → failed; run continues |
| Same file twice, or already sent | Quick id + SHA-256 dedupe in run; `history.json` across runs |
| Hundreds of GB of clips | Quick id instead of full hashing at scan; footage budget spread across days; rerun for more |
| Mixed games in one folder | Label hints warn; README says one game per folder |
| Steam Game Recording folders | Detected and skipped with export instructions |
| Unicode / long paths | Argument lists only (no shell); ASCII output names; path-length skip |
| Running inside the zip | Launcher detects missing runtime and explains |
| Low disk space | Pre-checks; graceful stop; resumable |
| Interrupted run | Per-clip `done.json`; same folder + game + recipe resumes |
| Watermarks / overlays (Medal, FPS counters) | Kept (gameplay pixels); `encoder_tag` + notes allow shortcut analysis later |

**Label hints** (case-insensitive, on folder and file names): `valorant` → Valorant; `league of legends`, `league_of_legends`, `leagueoflegends`, whole-word `lol` → League_of_Legends; `counter-strike`, `counter strike`, `cs2`, `csgo` → CS2; `minecraft` → Minecraft; `overwatch` → Overwatch_2; `marvel rivals`, `marvel_rivals`, `marvelrivals` → Marvel_Rivals. Steam clip folders `clip_<appid>_…`: 730 → CS2, 2357570 → Overwatch_2, 2767030 → Marvel_Rivals. The table lives in code next to the game list.

---

## 10. Privacy, consent, trust

- **Read-only on clips.** The tool never writes next to, renames, or deletes source files. All output goes under the pack's `output/`.
- **No network access** anywhere in the code (tested by a static check that no networking module is imported). The bundled Python has its socket and SSL modules removed, and every ffmpeg/ffprobe input is limited to the `file` protocol.
- **Writes only inside the tool folder.** Everything goes under the pack's `config/` and `output/`; every write path is resolved (junctions and symlinks followed) and refused if it lands outside the tool folder. No temp folder, registry or shortcuts. The one exception is `--output <dir>`, which the friend has to type themselves: the finished zip (written as a `.part` file, then renamed) goes into that folder, which must already exist. Nothing else goes there and existing files are never overwritten. The end-to-end tests check that the clips folder is unchanged, that nothing appears outside the tool folder, and that `--output` adds only the zip.
- **Runs only what it ships.** In a pack, only `bin\ffmpeg.exe`, `bin\ffprobe.exe` and `%SystemRoot%\explorer.exe` (to show the zip) are started, with argument lists and no shell. The Python code is stdlib-only (static test), and both bundled downloads are pinned by SHA-256 at build time.
- **No machine details:** no hostname, username, absolute paths or hardware serials. OS version, CPU count and timezone only.
- **Consent recorded per pack:** data use (required) and public examples (optional, default no). Without public-example consent, that friend's frames never appear in published docs or report figures.
- **What the notice says:** frames (no audio, no video) are sampled every 5 s; filenames, recording dates and video metadata are included; data stays on my machine for this project's training and evaluation; nothing is redistributed; ask and I delete it.
- Packs are stored only under gitignored `data/`. Handles never appear in tracked files.

---

## 11. Receiving side (ingest contract)

`gfc-ingest-pack <zip>` on my machine. Full tool spec: [ingest-pack.md](ingest-pack.md). Summary of the contract the pack must satisfy:

**Zip safety (before writing anything):**

- Entries: relative paths only, no `..`, no drive letters or leading slashes, no symlink attributes, ASCII names, allowed extensions `.jpg .json .csv .txt` (plus `.zip` at the top level only, see below).
- Sizes: each entry ≤ 64 MiB; total uncompressed ≤ min(64 GiB, `manifest.output.uncompressed_bytes` × 1.05 + 16 MiB); entry count = `file_count` + 1.
- Compression: `STORED` expected. `DEFLATED` is accepted (a friend may re-zip) with per-entry ratio limits: ≤ 2 for `.jpg`, ≤ 20 for text.
- **Zip of packs:** if the archive contains only `.zip` entries (friend bundled several packs), each inner zip is validated the same way; one nesting level maximum.

**Content checks:** schema versions known; every `frames.csv` row exists with matching bytes and SHA-256; slots complete for every tier; recipe compared with the expected recipe (differences recorded, not fatal); `contributor_id` vs handle collisions reported.

**Placement:** `data/frame_sources/<Game>/contributor_<handle>/<clip_key>/<tier>/`, manifests copied verbatim to `data/frame_sources/_packs/<pack_id>/`. Clips whose `clip_sha256` already exists anywhere (any contributor or my own clips) are skipped and logged. `Other` packs go to `data/frame_sources/_other/<other_name>/...` (unknown-class material, D24).

**Size tracking (D25):** `zip_bytes` vs `input_bytes` per pack and per resolution appended to a local stats table.

---

## 12. Implementation architecture

**Shared code, one path (D26).** Extraction logic lives in a stdlib-only package in the repo and is copied into the pack at build time:

```text
src/game_frame_classifier/sourcing/      # stdlib only (enforced by a test)
  recipe.py      load / validate / resolve recipe; tier ids
  ffbin.py       locate ffmpeg/ffprobe (bundled > GFC_FFMPEG_DIR > PATH); capture versions
  probe.py       ffprobe JSON, stream choice, sanitising, fps, HDR, even-crop
  sampler.py     bucket expression, showinfo parsing, bucket math, alignment
  extract.py     encode_crf(), extract_tier(), extract_clip() → ClipResult
  derive.py      pad-to-16:9 + scale (compact mode here, train frames in the pipeline)
  hashing.py     streaming SHA-256, JPEG dimension reader
  labels.py      game list, hint table, Steam app ids
  manifests.py   pack / clip / frame schemas, CSV + JSON writers and readers
  packzip.py     stored-zip writer + verifier; ingest-side validator
  timeinfo.py    recording time from container, filename and mtime; host timezone
  budget.py      spread_days_v1 footage budget
src/game_frame_classifier/frame_export/
  cli.py         prompts, game choice, scan summary, confirm, finish
  scan.py        discovery, quick ids, probing, budget selection
  run.py         per-clip processing, resume, manifests, zip, history
  settings.py    user.json and history.json
  paths.py       tool-folder paths; refuses writes outside the tool folder
packaging/frame_export/
  START HERE.bat, README.txt.tmpl, python313._pth, pins.json
scripts/build_frame_export.py
```

**Pinned dependencies** (exact versions and SHA-256 in `packaging/frame_export/pins.json`; the build script refuses mismatches):

- Python **3.13.17** amd64 embeddable zip from python.org. 3.12 no longer ships Windows binaries. The build removes modules the tool never needs (`_socket`, `select`, `_ssl`, `_asyncio`, `_overlapped`, `_ctypes`, `_sqlite3`, `_multiprocessing`, `pythonw.exe` and their DLLs), so the bundled interpreter cannot open network sockets.
- FFmpeg **`n8.1.3` win64-gpl** static from FFmpeg-Builds (formerly BtbN), dated autobuild `autobuild-2026-11-16-15-29` (not `latest`). Includes libx264, libdav1d (fast AV1 decode) and libzimg (tone-map). Ship `ffmpeg.exe`, `ffprobe.exe`, the build's license and a source link. Dated builds get pruned upstream, so the build script keeps the verified download in `build/frame_export_cache/`.
- My local pipeline uses the same pinned build via `GFC_FFMPEG_DIR`, so personal and friend CRF artifacts come from the same x264.

**Build (`scripts/build_frame_export.py`):** download pins → verify hashes → stage runtime (patch `._pth`), bin, app (copy `sourcing/` + `frame_export/`, stamp version and git commit), config (`recipe.json` copied from the repo's `config/recipe.json`, the same file `gfc-make-sources` uses), README (render template with collector name and contact passed on the command line, never committed), licenses → smoke test (the bundled Python cannot import `socket`; a synthetic 21 s clip gives 5 slots with the bundled ffmpeg) → `dist/GFC-FrameExportKit-v<version>.zip` (gitignored).

**Versioning:** tool semver in `frame_export/__init__.py`; `recipe_id` changes whenever any output-affecting field changes; schema ids (`gfc.pack/1` etc.) change only on breaking format changes.

---

## 13. Testing and release

**Unit:** recipe validation and precedence; filename timestamp patterns (each pattern, invalid dates, future dates, folder-only dates); recorded-start fallback order and bogus container epochs; DST offsets on both sides of a change; budget selection (under budget takes all, round-robin across days, skip-and-continue when a clip doesn't fit, single-longer-than-budget case, determinism, rerun picks only unsent clips); handle normalisation; label hints; bucket math (boundaries, OFF, negative times); showinfo parsing; alignment pairing; JPEG SOF reader; manifest round-trip; zip validator (traversal, absolute paths, symlinks, ratio, oversize, nested zip, count mismatch); stdlib-only and no-network import checks.

**System (synthetic clips generated in tests):** CFR 30/60; VFR with gaps and start offset; odd dimensions; 3440×1440 and 1280×960; HDR-tagged 10-bit HEVC; AV1; MKV with attached picture; clip shorter than one interval; zero-byte and truncated files; Unicode filename; duplicate file; Steam `session.mpd` folder; compact mode equals pipeline derive byte-for-byte on the same native image; resume after a killed run; full round trip pack → ingest → derive.

**Colour check:** mean RGB of a JPEG still vs a PNG still of the same frame within 1.5 levels (catches limited/full range mistakes).

**Release checklist:**

1. All tests green with the pinned ffmpeg.
2. Run the pack on my own clips; ingest; compare against `gfc-make-sources` output for the same clips (identical slots and hashes).
3. Clean-machine test in **Windows Sandbox** (no Python, no ffmpeg): extract, drag folder, full run, Ctrl+C + resume, low-disk refusal.
4. Canary: one friend runs it; check the pack and fix friction.
5. Send to everyone.

---

## 14. Appendix: friend `README.txt` (template)

```text
GFC Frame Export Kit — for {collector_name}'s school ML project

1. Right-click the zip → Extract All. Open the extracted folder.
2. Drag ONE game's clip folder onto START HERE.bat.
3. First time only: type a name, answer two yes/no questions.
4. Pick the game, press Enter through the optional questions, confirm Start.
5. Wait. Fans may spin up; you can close the window and rerun the same folder later.
6. Send the zip from the output folder via Drive / OneDrive / WeTransfer
   (not Discord — the free limit is too small).

Repeat step 2–6 for each game. Clips are only read. Nothing is uploaded.
If Windows blocks it: More info → Run anyway. Steam clips: export to MP4 first.
Problems? Send {collector_contact} output\...\run_log.txt.
```

## Related

- [quality-encoder.md](quality-encoder.md) (D22 primitive)
- [frame-extractor.md](frame-extractor.md)
- [data-layout.md](../../data-layout.md)
