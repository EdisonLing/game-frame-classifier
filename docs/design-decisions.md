# Design decisions

Living log of choices for Frame to Game. Fill in **Decision** / **Rationale** / **Date** when we decide — leave blank until then.

**Statuses:** `open` · `leaning` · `provisional` · `gate` · `decided` · `deferred` · `rejected`

- `provisional`: a working default chosen so building can continue. Cheap to change (a config value or a rerun); the alternative is written down and gets revisited after first results.
- `gate`: expensive to undo. Must be decided explicitly, together, before the step it blocks. The blocked step is named in the entry.

**Sources of prompts:** proposal notes · reviewer feedback · roadmap work · experiments

---

## How to use

1. When something comes up (TA suggestion, implementation fork, report rewrite), add or update a row/section here.
2. Do **not** auto-adopt TA suggestions — park them as `open` / `leaning` until we pick.
3. Link out to the tool page or roadmap stage that implements the decision once locked.

---

## Already strong (default keep)

Called out positively in TA feedback. Treat as decided unless we explicitly reopen.

| ID | Decision | Status | Notes |
|---|---|---|---|
| D01 | Split by **video/session**, not by frame | decided | Leakage fix vs prior work |
| D02 | Test on **unseen streamers** + **held-out personal sessions** | decided | |
| D03 | **Augment only after** splitting | decided | |
| D04 | Ops stills **full + low (CRF 45)**; medium=38 docs only; **every frame used (train, val, test, baseline, CNN) is one tier: half full, half low**, fixed per slot by bucket parity with a per-clip offset (not both tiers per slot); **per-tier eval is a diagnostic on top**. **Quick mode** (opt-in per contributor, kit only): a clip with no low tier uses `full` for every slot; its slots are counted and reported, so the drift above half full stays visible | decided (revised 2026-11-17) | Small 256×144 Δ → no 2× dataset; dual folders kept for sampling + per-tier diagnostics. Was: random full *or* low per train example |
| D05 | Colour-histogram + logistic regression baseline | decided | Exposes what spatial layout adds |
| D06 | Keep menus/overlays in the data (do not strip as “bad”) | decided | Differs from Trivedi et al. |
| D07 | Course primary goal = **frame classification**; clip tagging = inference glue | decided | See roadmap |

---

## Open decisions (from TA + gaps)

### D10 — Progress/final figure redo

| | |
|---|---|
| **Status** | open |
| **Prompt** | TA Illustration −0.5: small labels; CNN drawn right→left |
| **Options** | (A) Redraw for progress report only (B) Also update proposal archive figure (C) Defer polish to final report |
| **Decision** | |
| **Rationale** | |
| **Date** | |
| **Links** | Architecture figure lives in local proposal materials (not in git) |

**Suggested fix (TA, not adopted):** enlarge labels under Deduplicate / Auto Filter; simplify data-pipeline half; CNN left→right.

---

### D11 — “Non-game content” filter rule

| | |
|---|---|
| **Status** | decided |
| **Prompt** | TA Data Processing −0.5: no definition of “dominated by non-game content” |
| **Options** | (A) Hand rules (black/blur + manual quarantine) (B) Simple lobby/menu detector + threshold, validated on a hand-labelled sample (C) Drop only black/blur for v1; defer non-game heuristic (D) Other: ___ |
| **Decision** | **(B)** Simple lobby / non-game detector with a score threshold, checked on a small hand-labelled sample (TA recommendation). Until that ships: keep black / blur / near-dupe auto-filters; quarantine obvious lobby/desktop frames by hand when reviewing rejects. |
| **Rationale** | Closes the undefined-filter gap without stripping in-game menus/HUD (D06). Detector is for lobby / desktop / facecam-heavy / browser — not “frame has a menu.” Hand-labelled sample keeps the rule honest before we trust a threshold. |
| **Date** | 2026-11-15 |
| **Links** | [tools/frame-cleaner.md](roadmap/tools/frame-cleaner.md) |

**Note:** Proposal keeps menus/HUD as valid gameplay frames (D06). “Non-game” should mean desktop/browser/facecam-heavy/etc., not “has a menu.”

**When:** Progress report can describe the rule + current black/blur/dedupe; implement the detector after first multi-game extract (not blocking batch extract).

---

### D12 — Confirmed sources for LoL, Overwatch 2, Marvel Rivals

| | |
|---|---|
| **Status** | open |
| **Prompt** | TA Data Processing −0.5: three games have no public fallback / named source |
| **Options** | Name ≥1 concrete, terms-OK source per game (channel, VOD set, tournament archive, friends’ clips, …) |
| **Decision** | LoL: ___ · OW2: ___ · Marvel Rivals: ___ |
| **Rationale** | |
| **Date** | |
| **Links** | [tools/source-acquisition.md](roadmap/tools/source-acquisition.md) |

**TA collection tip (operational, not architecture):** prioritize **personal clips** for these three while sourcing.

---

### D13 — Personal holdout discipline

| | |
|---|---|
| **Status** | provisional |
| **Prompt** | TA: keep personal-clip held-out set untouched during development |
| **Options** | (A) Strict freeze once split is written (B) Allow rare peek for debugging only, never for tuning (C) Soft holdout until dataset is larger |
| **Decision** | **(A) for now.** Training and tuning read `train` and `val` only. `test_session` and `test_source` open through `gfc-evaluate` alone, only after the split is frozen, with a stated reason, and every access is appended to `data/runs/holdout_access.jsonl`. Development and progress-report numbers come from `val`. |
| **Rationale** | Strict is the direction that can be relaxed later; a look at the test set cannot be taken back. Whether the progress report shows one logged `test_session` result is settled with D32. |
| **Date** | 2026-11-17 |
| **Links** | [tools/dataset-splitter.md](roadmap/tools/dataset-splitter.md) |

---

### D14 — Progress-report data tables

| | |
|---|---|
| **Status** | decided |
| **Prompt** | TA: report frames, videos, and channels **per game** |
| **Options** | (A) Table in progress report only (B) Also auto-generate from catalog as a script output |
| **Decision** | **(B).** `gfc-split` writes `counts.csv` (slots, clips, sessions, sources per game and split) and `sources.csv` (per-source share); `gfc-evaluate --data-report` draws the class-count figure and example frames. |
| **Rationale** | The numbers change every time footage arrives; a generated table cannot go stale. |
| **Date** | 2026-11-17 |
| **Links** | [tools/dataset-splitter.md](roadmap/tools/dataset-splitter.md), [tools/evaluation.md](roadmap/tools/evaluation.md) |

---

### D15 — Two-stream HUD architecture

| | |
|---|---|
| **Status** | provisional — **two-stream not adopted** |
| **Prompt** | TA: consider full-frame stream + small CNN on fixed HUD crops (minimap, ability bar, corners), fuse before classifier |
| **Options** | (A) Stick to single-stream 4-block CNN for progress report; revisit after first results (B) Implement two-stream as primary before progress report (C) Single-stream primary + two-stream as ablation for final (D) Reject two-stream |
| **Decision** | **(A) for now.** Single stream for the first results. (C) or (D) is chosen once the look-alike confusion of the single-stream model is known. |
| **Rationale** | Nothing in the single-stream pipeline has to change to add a second stream later: HUD crops would be cut from the native stills in `frame_sources`, which are kept for exactly this (D25). |
| **Date** | 2026-11-17 |
| **Links** | [tools/cnn-trainer.md](roadmap/tools/cnn-trainer.md) |

**Why it’s optional:** tests the “HUD position matters” claim and may help OW2 vs Marvel Rivals, but adds crop design, fusion, and tuning cost before we even have a working single-stream baseline+CNN.

---

### D16 — Exact layer sizes + parameter count

| | |
|---|---|
| **Status** | provisional |
| **Prompt** | TA: give exact channel/FC sizes; flattening 16×9×256 ≈ 37k features into first FC |
| **Options** | FC 128 (5,108,390 params) · **FC 256 (9,827,878)** · FC 512 (19,266,854) · two FC layers · GAP head (390,438) |
| **Decision** | Conv channels: **32-64-128-256** (3×3, no bias, BN, ReLU, 2×2 max pool) · Flatten 256×9×16 = 36,864 · FC: **36,864→256**, dropout 0.5, **256→6** · Params: **9,827,878** (conv stack 388,896; first FC 9,437,440). Layer table in the tool page. |
| **Rationale** | Matches the proposal (four blocks, 32–256 channels, one FC with dropout). 256 keeps the first FC under 10 M weights for a training set of roughly 10,000 frames; sizes are config values, so this is tuned on val after the first curves. |
| **Date** | 2026-11-17 |
| **Links** | [tools/cnn-trainer.md](roadmap/tools/cnn-trainer.md) |

Related open fork from proposal: **flatten vs global average pooling** — decide with D16 or separately as D16b.

#### D16b — Flatten vs GAP

| | |
|---|---|
| **Status** | decided |
| **Options** | (A) Flatten first (matches “where HUD is” claim) (B) GAP first (C) Ablate both for final |
| **Decision** | **(A) then (C).** Flatten is the primary head; `model.head=gap` is a config switch so the comparison promised in the proposal is one extra run. |
| **Rationale** | As the proposal states: flatten preserves where HUD features appear. |
| **Date** | 2026-11-17 |

---

### D17 — Analysis focus if easy games saturate

| | |
|---|---|
| **Status** | deferred (until we see metrics) |
| **Prompt** | TA: if distinct games hit near-ceiling early, focus analysis on look-alike pair + low-quality frames |
| **Decision** | |
| **Rationale** | |
| **Date** | |

---

## Implementation forks (fill as we build tools)

### D19 — Raw clip folder layout

| | |
|---|---|
| **Status** | decided |
| **Options** | Flat dumps · game-first · source-first · person__session |
| **Decision** | **Collect now:** `data/raw/<Game>/<source>/` with original filenames (drag-and-drop, no rename). **Later:** normalize script copies into a tooling layout from filepath |
| **Rationale** | Most concerns are per-game; friends often only have one title; easier to fill League/OW2/Rivals first |
| **Date** | 2026-11-14 (revised: game-first) |
| **Links** | [data-layout.md](data-layout.md) |

### D20 — Manifest format

| | |
|---|---|
| **Status** | decided |
| **Options** | CSV · JSONL · Parquet · other |
| **Decision** | **CSV + JSON** side by side (`clips.csv` / `clips.json`, and the same for frame manifests) |
| **Rationale** | Matches extract/clean/quality already shipping; CSV for sheets, JSON for code |
| **Date** | 2026-11-14 |

### D21 — Frame image format on disk

| | |
|---|---|
| **Status** | decided |
| **Options** | PNG · JPEG · other |
| **Decision** | JPEG (`-q:v 2`) for extractor v1 |
| **Rationale** | Enough quality for HUD/palette cues; much smaller than PNG at dataset scale |
| **Date** | 2026-11-12 |

### D22 — Quality degradation method

| | |
|---|---|
| **Status** | decided |
| **Options** | (A) Still-frame CRF round-trip after 256×144 extract (B) **Video CRF re-encode, then extract/downscale** (C) JPEG qscale proxy |
| **Decision** | **(B)** Re-encode the **source video** at H.264 CRF, then sample @ 1/5s and scale to 256×144. **Since 2026-11-17 the re-encode covers a 1 s window before each sample** (`low_window_s`), starting with a fresh keyframe, instead of the whole video, with a 2 s keyframe interval on both encoders (`low_gop_s`): the artifacts still form on a video timeline, the sample is an ordinary predicted frame about 1 s into a group of pictures as in a stream, and only about a fifth of the frames are encoded. The full tier is taken by one accurate seek per sample, which gives the same frames as one pass over the whole video. Both depend on the source having frequent keyframes, so the method is chosen per clip from its keyframe interval (first 30 s of packets): up to 10 s, seeks and windows; longer, whole-video passes with a keyframe forced 1 s before each sample, which keeps the same structure. **Operational tiers:** **full** (original) + **low=CRF 45**. **Medium=CRF 38** is kept for docs / visual reference, not as a required train/eval/friend folder. **Encoder policy:** see **D28** (friends = libx264; personal may toggle AMF for speed). |
| **Rationale** | Low-bitrate artifacts must form on the timeline before downscale. At model size, even a harsh encode is only a few % mean abs vs full (README Δ), so a three-way eval ladder costs more than it teaches; one hard degraded setting is enough. |
| **Date** | 2026-11-16 (ops = full+low; method 2026-11-15; windows 2026-11-17) |
| **Links** | [tools/quality-encoder.md](roadmap/tools/quality-encoder.md), D28 |

### D28 — Degraded-tier encoder

| | |
|---|---|
| **Status** | decided (revised 2026-11-17: GPU first everywhere, libx264 fallback) |
| **Prompt** | Frame Export Kit wall time is ~75% libx264; GPU encoders are faster and leave the CPU free, but are not true CRF and differ by vendor |
| **Options** | (A) libx264 everywhere (B) **GPU everywhere, friends and personal, with libx264 fallback** (C) friends libx264, personal optional GPU toggle (D) friends libx264, personal GPU only |
| **Decision** | **(B).** Both the Frame Export Kit and `gfc-make-sources` encode the degraded tier with **`h264_d3d12va`** (Direct3D 12, one vendor-neutral API for NVIDIA, AMD and Intel on Windows 11) at **constant QP 51**, and fall back to **libx264 CRF 45** when the GPU can't be used. Recipe `encoder` = `auto` (try the GPU) or `x264`; `gpu_qp` maps each CRF tier to its QP (`{"45": 51}`); `--cpu` forces libx264 for one run. The tier id stays `crf45` whichever encoder made it. The `full` tier is never re-encoded. GPU decode (`d3d11va`) is separate from the encoder: it is allowed per codec only after its first frames match CPU decode bit for bit, so the full-tier stills are identical whichever way a PC decodes, and a GPU encoder failure never turns it off. Every degraded frame records `encoder` and `encoder_rc` (`h264_d3d12va`/`qp51` or `libx264`/`crf45`), every clip `low_encoder` and `gpu_fallback`, every run an `encoder` block, so results can be split by encoder. AMF (AMD's own encoder) is not built: on AMD cards the D3D12 path already uses the same hardware, so a second GPU path would only add a vendor-specific variant. |
| **Rationale** | Speed and a usable PC while extracting, for contributors and for me. Vendor artifacts in the low tier are accepted: at the 256×144 model input most of an encoder's character is removed by the downscale (CRF 45 vs full is only 3.5 % mean difference at 256×144, D22), and real streams are encoded by exactly these vendor hardware encoders, so the mix is closer to deployment than one software encoder. QP 51 is the H.264 maximum and the closest match to x264 CRF 45 (RX 9070 XT, 1440p60: 1.18 vs 1.34 Mbps; 32.7 vs 31.1 dB PSNR at 256×144, so slightly milder). The previous decision (C, 2026-11-16) kept contributors on libx264 so that encoder family could not stand in for the contributor; that risk is now measured instead of avoided: evaluation reports accuracy by encoder (`by_encoder`), and a large gap between encoders is the signal to revisit. |
| **Fallback** | Startup self-test (30-frame test encode: frame count and picture, PSNR at least 18 dB against the source); failing it means libx264 for the whole run, with a printed warning and the reason. Per tier: an ffmpeg error, missing frames, timestamps that don't line up with the full tier, or a first, middle or last still below 18 dB PSNR against the full-tier still redo that tier with libx264, with a warning. Any ffmpeg call with no progress for 300 s is killed (a hung driver becomes an ordinary fallback). A GPU decode failure redoes that step with CPU decode. After 3 clips in a row fall back, the rest of the run uses libx264. The H.264 level is pinned to 5.2 above 4K60 macroblock rates, since drivers refuse to open the encoder otherwise (4K120, 3440×1440 at 144 fps). |
| **Tested** | RX 9070 XT, Windows 11, driver 26.10.1: identical slot counts and timestamps to libx264 on 1080p60, 1080p120, 1440p60, 1440p144 and 4K120 AV1 VFR footage, plus HDR, VFR and odd-size synthetic clips; 5120×1440 falls back correctly. NVIDIA, Intel and Windows 10 untested: a canary on one such contributor PC comes before wide release. |
| **Date** | 2026-11-16 (revised 2026-11-17) |
| **Links** | [tools/frame-export-kit.md](roadmap/tools/frame-export-kit.md), [tools/make-sources.md](roadmap/tools/make-sources.md), [tools/quality-encoder.md](roadmap/tools/quality-encoder.md), [tools/evaluation.md](roadmap/tools/evaluation.md), D22 / D25 / D26 |

### D23 — Training stack / hardware

| | |
|---|---|
| **Status** | decided (hardware changed 2026-11-17; the trainer's first GPU smoke run is still to be done) |
| **Options** | Local CPU · local AMD GPU (ROCm build of PyTorch) · Colab |
| **Decision** | **Stack (decided):** PyTorch + torchvision for the CNN, scikit-learn for the baseline, matplotlib for figures, as an optional `train` dependency group. **Hardware (decided):** local AMD Radeon RX 9070 XT through AMD's ROCm build of PyTorch in a separate `.venv-rocm` ([setup guide](amd-gpu-setup.md)) is primary; local CPU is the fallback. The device is auto-detected (CUDA, MPS, CPU) and ROCm builds report as CUDA, so the same command runs on the GPU, on the CPU (`--device cpu` or the plain environment) or on Colab. |
| **Rationale** | Measured 1.0 s per training batch of 64 on an 8-thread CPU: about 3 min per epoch and under 2 h for 30 epochs at 10,000 train frames. **Measured 2026-11-17 on an RX 9070 XT** (ROCm 10.1.0 build of PyTorch 2.14, Windows 11, driver 26.10.1, [setup guide](amd-gpu-setup.md)): GPU training works. The overfit test reached train accuracy 1.0 on GPU and CPU, an 11-minute continuous run (8,750 steps) had no crash, GPU reset or NaN loss, and the hipBLASLt workaround was not needed. A training step takes 0.078 s per batch of 64 (CPU baseline 1.0 s, about 13× faster), and an epoch at 10,000 train frames about 17 s with 2 loader workers (about 45 s with none, because augmentation then costs 0.21 s per batch and becomes the bottleneck) against about 3.2 min on CPU. The environment is 4.2 GB. On 2,065 real frames a full epoch was about 7× faster than on the CPU (6.4 s against 45–50 s). The GPU became primary because that speed makes sweeps and the flatten-versus-GAP comparison cheap; CPU stays as the fallback because the Windows ROCm route is recent and the CPU path needs no extra setup. Timings in [cnn-trainer.md](roadmap/tools/cnn-trainer.md#training-time). |
| **Date** | 2026-11-17 |
| **Links** | [tools/cnn-trainer.md](roadmap/tools/cnn-trainer.md) |

### D24 — Unknown / other as a seventh output

| | |
|---|---|
| **Status** | decided (product); implementation detail leaning |
| **Prompt** | Auto-tagging / VOD % breakdowns must not force every frame into one of six games |
| **Options** | (A) 6-way softmax + **unknown** when max confidence is below a threshold (B) True **7-way** trained class (`unknown`/`other`) with held-out non-target frames (C) Both: threshold now, trained other later |
| **Decision** | Product output vocabulary includes **unknown** alongside the six games (prefer the name **unknown** over “other”). **Lean (C):** ship inference unknown via confidence threshold first (already on the clip-tagger / CNN roadmap); add a trained seventh class only if threshold-alone is too weak once real autotag eval exists. |
| **Rationale** | Autotag and “% time per game” need an abstain path. Threshold unknown is cheap and matches existing hardening notes; a trained other class needs deliberate non-target data and can wait. |
| **Date** | 2026-11-16 |
| **Links** | [tools/clip-tagger.md](roadmap/tools/clip-tagger.md), [tools/cnn-trainer.md](roadmap/tools/cnn-trainer.md), root README “The trained model” |

### D25 — Frame Export Kit / contributor packs (frames zip, not masters)

| | |
|---|---|
| **Status** | decided (export kit + ingest implemented; make-sources still to build) |
| **Prompt** | Friends convert clips → frames and zip to me; plug-and-play; what to keep without masters |
| **Options** | (A) 256×144 only (B) resolution-capped stills (C) **native res, no cap** + optional compact 256 |
| **Decision** | **(C) No resolution cap.** After video CRF (D22), extract stills at the **source video resolution**. Default tiers: **full + crf45** (D04), set in a shipped `recipe.json` (`crf_list`, `include_full`, `interval_s` = 5), not hardcoded. **Footage budget** `footage_budget_min` = 180 per game per run (editable; `0` = all), clips spread across recording days; rerun sends more. Optional **compact** = 256×144 via the same derive step as my pipeline (D27). **Packaging:** Python embeddable + `.bat` launcher (drag a folder), pinned static ffmpeg (x264 + dav1d + zimg), stdlib-only app; Windows-first. Name and consent asked once (`user.json`), game per run, auto-zip per run (`ZIP_STORED`, verified). Friends do **not** clean. Manifests keep clip SHA-256, file timing, sanitised probe, actual frame timestamps, slot pairing, recipe, tool/ffmpeg/x264 versions, sizes and hashes; uncompressed size + file count for ingest-side bomb checks. **Track** handoff size vs source by resolution. **Mixed folders (v2.1):** opt-in `(mixed)` / `--game Mixed` for Medal-style `title__YYYY-MM-DD__HH-MM-SS` names only (`title__timestamp_v1`); one existing single-game pack per detected category; 3 h budget per category including a shared `Other` pack (`other_name` = `mixed_other`); unsupported or conflicting names skipped; general notes copied into every pack, no game-specific questions. |
| **Rationale** | Cap was solving a size-anxiety problem; the real need is knowing how much the sparse still pack saves at 1080 / 1440 / 4K. Native stills keep train-size, aspect, HUD-crop (D15) and docs flexibility on my side, so I never have to ask for clips again. Embeddable Python avoids the antivirus friction of an unsigned PyInstaller exe and stays patchable. Mixed mode keeps ingest unchanged (still one game per pack) while supporting contributors who store every game in one folder. |
| **Date** | 2026-11-16 (revised: drop cap; spec v1; 2026-11-17 mixed folders) |
| **Links** | [tools/frame-export-kit.md](roadmap/tools/frame-export-kit.md); [tools/quality-encoder.md](roadmap/tools/quality-encoder.md) |

### D26 — Frame sources as first-class data (one extraction path)

| | |
|---|---|
| **Status** | decided (ingest implemented; make-sources / derive still to build) |
| **Prompt** | Friend frames replace masters, so stills must be usable as sources alongside my own clips |
| **Options** | (A) Keep extracting personal clips straight to 256×144; treat contributor packs as a side format (B) **Every clip, mine or a friend's, goes through the same `sourcing` code into native-res frame sources; train frames are derived from those** |
| **Decision** | **(B).** `data/frame_sources/<Game>/<source>/<clip_key>/<tier>/` holds native-res stills for every source (`gfc-make-sources` for my clips, `gfc-ingest-pack` for friend zips). One stdlib-only package does probe, sampling and CRF for both. **Sampler `bucket_v1`:** one frame per `interval_s` bucket on the clip timeline, chosen by ffmpeg `select` on real timestamps (VFR-safe), actual `pts_time` recorded; tiers paired by bucket into **slots** (`<clip_key>:b<bucket>`). `clip_key` = `c` + first 12 hex of the clip SHA-256. Tier ids `full` / `crf<N>`. |
| **Rationale** | Two paths would drift (different samplers, scalers, ffmpeg builds) and become a hidden source-vs-label confound. Content-addressed keys dedupe across people. The old `fps=1/5` + computed timestamps assumed CFR, which game captures often are not. |
| **Date** | 2026-11-16 |
| **Links** | [tools/frame-export-kit.md](roadmap/tools/frame-export-kit.md), [data-layout.md](data-layout.md) |

### D27 — Derive policy (native stills → 256×144)

| | |
|---|---|
| **Status** | decided (not built yet) |
| **Prompt** | How native-resolution stills of any aspect become model input |
| **Options** | (A) Stretch to 256×144 (B) Centre-crop to 16:9 (C) **Pad to 16:9 when aspect is off by more than 1 %, then bicubic scale** |
| **Decision** | **(C)** via ffmpeg (`pad` then `scale=256:144:flags=bicubic`, JPEG q2) from the native JPEG, stored as `data/frames/...`; the dataloader does no resizing. Friend compact mode runs the same function. |
| **Rationale** | Crop can cut HUD corners (main cue); stretch distorts shapes. Most sources are 16:9 and untouched. Same scaler and source for every frame avoids processing confounds between my clips and contributor packs. Re-derivable if train size changes. |
| **Date** | 2026-11-16 |
| **Links** | [tools/frame-export-kit.md](roadmap/tools/frame-export-kit.md), [tools/frame-extractor.md](roadmap/tools/frame-extractor.md) |

### D29 — Training input contract

| | |
|---|---|
| **Status** | decided |
| **Prompt** | Two frame paths exist: interim batch extract (256×144, video-stem ids, absolute paths, no paired tiers) and frame sources (D26) |
| **Options** | (A) Let the splitter accept either (B) **Training reads only split manifests built from `frame_sources` through the slot index** |
| **Decision** | **(B).** `gfc-derive-frames` writes `clips_index` and `slots`; the cleaner adds verdicts; `gfc-split` writes the split manifests; the loader reads nothing else. Paths in every table are relative to the data root. The interim path stays for single-clip debugging. |
| **Rationale** | D04 needs paired tiers per slot and D01 needs clip identity and recording times; only frame sources carry them. One input format keeps the baseline and CNN on identical frames. |
| **Date** | 2026-11-17 |
| **Links** | [training-pipeline.md](training-pipeline.md), [tools/derive-frames.md](roadmap/tools/derive-frames.md) |

### D30 — Session rule

| | |
|---|---|
| **Status** | provisional (confirmed or changed with D32) |
| **Options** | (A) **Gap rule:** clips of one source and game join a session when they start within 30 min of the session's latest end (B) One session per recording day (C) One session per clip |
| **Decision** | **(A), 30 min**, `session_gap_min` in `config/split.json`. Overlapping clips always share a session; clips without a recorded start are their own session. |
| **Rationale** | Instant-replay clips overlap and cluster inside one match; the gap rule keeps a match together without merging a whole day. (C) leaks, (B) wastes sessions when a game has few recording days. |
| **Date** | 2026-11-17 |
| **Links** | [tools/dataset-splitter.md](roadmap/tools/dataset-splitter.md) |

### D31 — Split mechanics

| | |
|---|---|
| **Status** | decided |
| **Prompt** | Footage arrives over weeks; a reshuffle on every arrival would move clips between train and test |
| **Options** | (A) Shuffle sessions with a seed and cut at 70/15/15 on every run (B) Hash each session to a split (C) **Per-clip ledger with greedy fill** |
| **Decision** | **(C).** Splits `train` / `val` / `test_session` (target 70 / 15 / 15 of each game's slots) plus `test_source` for held-out sources. A new session goes to the first of `train` / `val` / `test_session` with no session yet for its game, otherwise to the split furthest below target; every clip's split is stored in `splits/<split_id>/ledger.csv` and never moves to a less held-out split. A changed policy gets a new `split_id`. |
| **Rationale** | (A) contaminates the held-out sets each time data is added. (B) is stable but badly unbalanced with few sessions per game. The ledger is stable and balanced. |
| **Date** | 2026-11-17 |
| **Links** | [tools/dataset-splitter.md](roadmap/tools/dataset-splitter.md) |

### D32 — Held-out test design (gate G1)

| | |
|---|---|
| **Status** | **gate** — blocks `gfc-split --freeze`, every `test_session` / `test_source` evaluation, and any reported test number |
| **Prompt** | Proposal: test on unseen streamers and on held-out personal sessions. Actual footage so far is personal clips and contributor packs, a few people per game |
| **Options** | (A) `test_session` only (B) `test_session` + `test_source`, holding out whole contributors where a game has at least three sources (C) `test_source` only |
| **Sub-questions** | Which sources are held out per game · confirm the session rule (D30) · whether the progress report shows a test number or `val` only (D13) |
| **Decision** | |
| **Rationale** | |
| **Date** | |
| **Links** | [tools/dataset-splitter.md](roadmap/tools/dataset-splitter.md#gates) |

**Suggested:** (B). **Until decided:** drafts only; both models are developed on `train` / `val`.

### D33 — Source cap with few sources

| | |
|---|---|
| **Status** | decided 2026-11-18 |
| **Prompt** | Proposal: 15+ channels per game, each capped at about 1/15 of the game's frames. With a few sources per game that cap would discard most of the data |
| **Options** | (A) Enforce 1/15 (needs public sources first, D12) (B) Enforce a relaxed cap (C) **No cap; report every source's share, warn above 1/15, report per-source accuracy** |
| **Decision** | **Cap train only, never delete.** `max_source_share = 1/15` (proposal) on each game's train slots; when a game has fewer than 15 sources (1/15 < 1/k), each source is capped at the median of the game's per-source train counts instead of the equal share, so a source with one video does not trim everyone to its size. Optional `train_slots_per_source` caps each person's train slots by count; the stricter cap wins. Capped slots go to `unused.csv` and come back when a cap is raised; val and test are never thinned (2026-11-18). Earlier (2026-11-17), superseding (C) no cap: optional per-source slot limits in `gfc-split` (`max_slots_per_source` for everyone, `source_slots` per person, all splits, nested by a seeded slot hash) to use a fixed amount from each person and change it without re-extracting; and `gfc-make-sources --budget-hours` to bound how much of my own footage is extracted. Both off by default. |
| **Rationale** | The cap thins `train` only, so it can be tightened at any time without touching a held-out set. Reporting the shares keeps the deviation from the proposal visible. |
| **Date** | 2026-11-17 |
| **Links** | [tools/dataset-splitter.md](roadmap/tools/dataset-splitter.md), D12 |

### D34 — Class imbalance

| | |
|---|---|
| **Status** | provisional |
| **Options** | (A) Downsample every game to the smallest class (B) **Keep all kept slots; class-weighted loss / `class_weight="balanced"`; macro-F1 beside accuracy** |
| **Decision** | **(B).** |
| **Rationale** | Games will fill at different rates while footage arrives; downsampling would tie the dataset size to the slowest game. |
| **Date** | 2026-11-17 |

### D35 — Augmentation

| | |
|---|---|
| **Status** | provisional |
| **Options** | Online vs offline copies · zoom both ways vs zoom-out only · jitter strength |
| **Decision** | Online. On half the samples: scale 0.85–1.15 with up to 2 % shift, black fill. On 80 %: brightness / contrast / saturation 0.2, hue 0.02. No flips, no rotation. Tier is not an augmentation (D04). |
| **Rationale** | Proposal ranges; online needs no extra disk and no bookkeeping. Zoom-in can crop a few HUD pixels at the edge, which is the thing to check on real samples. |
| **Date** | 2026-11-17 |
| **Links** | [tools/dataset-loader.md](roadmap/tools/dataset-loader.md) |

### D36 — Baseline details

| | |
|---|---|
| **Status** | provisional |
| **Decision** | 16 equal-width bins per RGB channel on the 256×144 frame, each channel normalised to sum 1 (48 features); `StandardScaler`; multinomial logistic regression, `C` chosen on val from 0.01 / 0.1 / 1 / 10; balanced class weights. |
| **Rationale** | The proposal's baseline, on exactly the CNN's input so the comparison isolates spatial layout. |
| **Date** | 2026-11-17 |
| **Links** | [tools/baseline.md](roadmap/tools/baseline.md) |

### D37 — CNN training settings

| | |
|---|---|
| **Status** | provisional |
| **Decision** | Adam, lr 1e-3, weight decay 1e-4, batch 64, up to 30 epochs, early stop after 6 epochs without a better val macro-F1, best-val checkpoint kept, seed 360. |
| **Rationale** | Standard starting point; the proposal fixes only cross-entropy and Adam. Tuned on val. |
| **Date** | 2026-11-17 |
| **Links** | [tools/cnn-trainer.md](roadmap/tools/cnn-trainer.md) |

### D38 — Evaluation and run layout

| | |
|---|---|
| **Status** | decided |
| **Decision** | One `gfc-evaluate` for both models through a shared `predict_proba` interface. Runs live in `data/runs/<model_type>/<run_id>/` with the resolved config, labels, split id and split hashes. Headline = accuracy and macro-F1 on the half-and-half set; always broken down by tier, source and clip; paired per-tier diagnostic on request. Example figures use only frames whose source allows public examples. |
| **Rationale** | Identical measurement for baseline and CNN; every number traceable to a data snapshot. |
| **Date** | 2026-11-17 |
| **Links** | [tools/evaluation.md](roadmap/tools/evaluation.md) |

---

## Decision log (newest first)

| Date | ID | Change |
|---|---|---|
| 2026-11-17 | D23 | Hardware decided: **local RX 9070 XT (ROCm build of PyTorch) primary, local CPU fallback**, after measured setup, stability and timing on the GPU ([amd-gpu-setup.md](amd-gpu-setup.md)) |
| 2026-11-17 | D32 | Opened as a **gate**: held-out test design must be agreed before the split is frozen or any test split is evaluated |
| 2026-11-18 | D33 | **Decided:** 1/15 share cap on train with a median fallback below 15 sources, plus optional `train_slots_per_source`; train only, nothing deleted |
| 2026-11-17 | D33 | Per-source slot limits in `gfc-split` (blanket and per source) and `gfc-make-sources --budget-hours` (cumulative, spread across days); off by default |
| 2026-11-17 | D31 | Greedy fill seeds each split first: a game's first three sessions go to `train`, `val`, `test_session`, then fill by deficit |
| 2026-11-17 | D29–D31, D38 | Decided: training reads only split manifests from frame sources; ledger-based split; shared evaluation and run layout |
| 2026-11-17 | D13, D15, D16, D23, D30, D33–D37 | Provisional working defaults recorded with their alternatives (see [training-pipeline.md](training-pipeline.md) §4.2) |
| 2026-11-17 | D14, D16b | Decided: generated data tables; flatten primary with GAP as a config switch |
| 2026-11-17 | D22 / D26 | **Extraction by seeks and windows:** full tier by one accurate seek per sample (same frames as the single select pass); low tier from a 1 s encoded window before each sample instead of the whole video (`low_window_s`, recipe `2026-11-17b`). GPU decode is used only when it is identical and faster. 3-min clips: 1080p60 38 → about 19 s, 1440p60 56 → about 26 s, 4K120 AV1 316 → about 66 s |
| 2026-11-17 | D25 | **Mixed-folder mode** (kit v2.1.0): `(mixed)` / `--game Mixed` classifies `title__timestamp_v1` names into one pack per category with a 3 h budget each (including `Other` / `mixed_other`); unsupported or conflicting names skipped; pack format and ingest unchanged |
| 2026-11-17 | D04 / D25 | **Quick mode** added to the Frame Export Kit: full quality only, about 4× faster on the CPU, asked on first run and changeable at the Start question or with `--change-mode`. Quick-mode clips use `full` for every slot; downstream reports their share |
| 2026-11-17 | D04 | Tier rule made concrete: bucket parity with a per-clip offset, so it is stable when footage is added |
| 2026-11-17 | D04 | Quality mix → **half full / half low (CRF 45) wherever frames are used**, assigned once per slot (deterministic, half and half within each clip); replaces random per-draw train sampling. Per-tier eval kept as a diagnostic (both tiers of each test slot) |
| 2026-11-16 | D25 | Tool renamed friend pack → **Frame Export Kit** (`gfc-frame-export`, package `frame_export`); its zips are contributor packs |
| 2026-11-17 | D28 | Revised to **GPU first everywhere** (kit and `gfc-make-sources`): D3D12 constant QP 51, libx264 CRF 45 fallback with warnings; encoder recorded per frame; vendor artifacts accepted and measured with `by_encoder` in evaluation |
| 2026-11-16 | D28 | Friends stay libx264; personal optional AMF speed toggle (not friend default; not AMF-only personal) |
| 2026-11-16 | D25 | Decided: spec v1 (recipe file, embeddable Python + pinned ffmpeg, manifests, ingest checks) |
| 2026-11-16 | D26 | Frame sources first-class; one `sourcing` path for my clips and contributor packs; `bucket_v1` sampler |
| 2026-11-16 | D27 | Derive: pad to 16:9 (>1 % off) + bicubic 256×144 from native JPEG |
| 2026-11-16 | D04 | Train: **random full or low** per example (not both); eval still reports both |
| 2026-11-16 | D04 / D22 | Ops tiers → **full + low (45)**; medium=38 docs/reference only (small 256×144 Δ) |
| 2026-11-16 | D04 / D22 | Tier CRF map → **0 / 38 / 45** (was 0/28/38); 256×144 MAE showed 28≈full |
| 2026-11-16 | D25 | Revised: **no res cap** (native × 3); optional 256 compact; track size savings by resolution |
| 2026-11-16 | D25 | Frame Export Kit lean (superseded same day): had been 1440p-capped × 3 + 256 compact |
| 2026-11-16 | — | Published `docs/examples/` vs local `docs/examples-library/` (gitignored full catalog) |
| 2026-11-16 | — | README Going deeper: split **across all games** vs **per-game special considerations** (Valorant table: may affect vs what I did) |
| 2026-11-16 | D24 | Product: six games + **unknown**; lean threshold first, trained 7th optional later |
| 2026-11-15 | D22 | Superseded still-CRF: video CRF → then extract/downscale (full/med/low) |
| 2026-11-15 | D11 | Decided: simple lobby/non-game detector + threshold on hand-labelled sample (TA); interim = black/blur/dedupe + manual quarantine |
| 2026-11-14 | D20 | Manifests: CSV + JSON side by side |
| 2026-11-14 | D19 | Game-first `raw/<Game>/<source>/` (final for collection) |
| 2026-11-14 | D19 | Source-first draft tried same day; superseded |
| 2026-11-13 | D22 | Quality encoder: ffmpeg CRF round-trip; tiers full/medium/low = 0/28/38 |
| 2026-11-12 | D11 | Still open; cleaner ships black/blur/dedupe only (no lobby/non-game detector) |
| 2026-11-12 | — | Frame cleaner implemented (Pillow aHash + FIND_EDGES blur var≥400); no pipeline manager yet |
| 2026-11-12 | D21 | JPEG locked for frame extractor v1 |
| 2026-11-12 | — | Frame extractor implemented (subprocess ffmpeg, resize-on-extract); catalog still deferred |
| 2026-11-12 | — | File created; TA feedback indexed; D10–D17 opened from TA notes; D01–D07 marked keep |
