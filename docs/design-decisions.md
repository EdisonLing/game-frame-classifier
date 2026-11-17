# Design decisions

Living log of choices for Frame to Game. Fill in **Decision** / **Rationale** / **Date** when we decide — leave blank until then.

**Statuses:** `open` · `leaning` · `decided` · `deferred` · `rejected`

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
| D04 | Ops stills **full + low (CRF 45)**; medium=38 docs only; **train = random full *or* low per example** (not both); **eval reports full and low** | decided | Small 256×144 Δ → no 2× dataset; dual folders kept for eval + sampling |
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

**When:** Progress report can describe the rule + current black/blur/dedupe; implement the detector after first multi-game extract (not blocking the batch runner).

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
| **Status** | leaning (toward TA advice) |
| **Prompt** | TA: keep personal-clip held-out set untouched during development |
| **Options** | (A) Strict freeze once split is written (B) Allow rare peek for debugging only, never for tuning (C) Soft holdout until dataset is larger |
| **Decision** | |
| **Rationale** | |
| **Date** | |
| **Links** | [tools/dataset-splitter.md](roadmap/tools/dataset-splitter.md) |

---

### D14 — Progress-report data tables

| | |
|---|---|
| **Status** | leaning (do this) |
| **Prompt** | TA: report frames, videos, and channels **per game** |
| **Options** | (A) Table in progress report only (B) Also auto-generate from catalog as a script output |
| **Decision** | |
| **Rationale** | |
| **Date** | |
| **Links** | [tools/clip-catalog.md](roadmap/tools/clip-catalog.md), Stage 6 in [ROADMAP](roadmap/ROADMAP.md) |

---

### D15 — Two-stream HUD architecture

| | |
|---|---|
| **Status** | open — **do not adopt by default** |
| **Prompt** | TA: consider full-frame stream + small CNN on fixed HUD crops (minimap, ability bar, corners), fuse before classifier |
| **Options** | (A) Stick to single-stream 4-block CNN for progress report; revisit after first results (B) Implement two-stream as primary before progress report (C) Single-stream primary + two-stream as ablation for final (D) Reject two-stream |
| **Decision** | |
| **Rationale** | |
| **Date** | |
| **Links** | [tools/cnn-trainer.md](roadmap/tools/cnn-trainer.md) |

**Why it’s optional:** tests the “HUD position matters” claim and may help OW2 vs Marvel Rivals, but adds crop design, fusion, and tuning cost before we even have a working single-stream baseline+CNN.

---

### D16 — Exact layer sizes + parameter count

| | |
|---|---|
| **Status** | open |
| **Prompt** | TA: give exact channel/FC sizes; flattening 16×9×256 ≈ 37k features into first FC |
| **Options** | Lock numbers when first trainable CNN is defined; report param count in progress report |
| **Decision** | Conv channels: ___ · FC: ___ · Params: ___ |
| **Rationale** | |
| **Date** | |
| **Links** | [tools/cnn-trainer.md](roadmap/tools/cnn-trainer.md) |

Related open fork from proposal: **flatten vs global average pooling** — decide with D16 or separately as D16b.

#### D16b — Flatten vs GAP

| | |
|---|---|
| **Status** | open |
| **Options** | (A) Flatten first (matches “where HUD is” claim) (B) GAP first (C) Ablate both for final |
| **Decision** | |
| **Rationale** | |
| **Date** | |

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
| **Decision** | **(B)** Re-encode the **source video** at H.264 CRF, then sample @ 1/5s and scale to 256×144. **Operational tiers:** **full** (original) + **low=CRF 45**. **Medium=CRF 38** is kept for docs / visual reference, not as a required train/eval/friend folder. **Encoder policy:** see **D28** (friends = libx264; personal may toggle AMF for speed). |
| **Rationale** | Low-bitrate artifacts must form on the timeline before downscale. At model size, even a harsh encode is only a few % mean abs vs full (README Δ), so a three-way eval ladder costs more than it teaches; one hard degraded setting is enough. |
| **Date** | 2026-11-16 (ops = full+low; method 2026-11-15) |
| **Links** | [tools/quality-encoder.md](roadmap/tools/quality-encoder.md), D28 |

### D28 — Degraded-tier encoder (friends vs personal)

| | |
|---|---|
| **Status** | decided (not built yet) |
| **Prompt** | Frame Export Kit wall time is ~75% libx264; GPU (AMF/NVENC) is faster but not true CRF and differs by vendor |
| **Options** | (A) libx264 everywhere (B) GPU everywhere including friends (C) **Friends libx264; personal optional AMF toggle** (D) Friends libx264; personal AMF-only (replace x264) |
| **Decision** | **(C).** Frame Export Kit and the named **low / crf45** eval recipe stay **software libx264**. Personal `gfc-make-sources` / quality path may expose an **AMF toggle** for speed on my AMD machine. Manifest must record encoder + settings. Official comparable eval uses the x264 low tier; AMF output is a local speed path / optional extra stress, not a silent substitute for “CRF 45.” NVENC later is the same idea if needed — not the friend default. |
| **Rationale** | Mixing friend GPU vendors into the default low tier would confound source with artifact family. Keeping friends on pinned x264 preserves pack interchangeability. Personal AMF is fine when I accept non-identical mush and label it; replacing personal x264 entirely would make my data systematically different from friends (D rejected). |
| **Date** | 2026-11-16 |
| **Links** | [tools/frame-export-kit.md](roadmap/tools/frame-export-kit.md), [tools/quality-encoder.md](roadmap/tools/quality-encoder.md), D22 / D25 / D26 |

### D23 — Training stack / hardware

| | |
|---|---|
| **Status** | open |
| **Options** | Local PyTorch · Colab · both |
| **Decision** | |
| **Rationale** | |
| **Date** | |

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

### D25 — Friend handoff pack (frames zip, not masters)

| | |
|---|---|
| **Status** | decided (export kit + ingest implemented; make-sources still to build) |
| **Prompt** | Friends convert clips → frames and zip to me; plug-and-play; what to keep without masters |
| **Options** | (A) 256×144 only (B) resolution-capped stills (C) **native res, no cap** + optional compact 256 |
| **Decision** | **(C) No resolution cap.** After video CRF (D22), extract stills at the **source video resolution**. Default tiers: **full + crf45** (D04), set in a shipped `recipe.json` (`crf_list`, `include_full`, `interval_s` = 5), not hardcoded. **Footage budget** `footage_budget_min` = 180 per game per run (editable; `0` = all), clips spread across recording days; rerun sends more. Optional **compact** = 256×144 via the same derive step as my pipeline (D27). **Packaging:** Python embeddable + `.bat` launcher (drag a folder), pinned static ffmpeg (x264 + dav1d + zimg), stdlib-only app; Windows-first. Name and consent asked once (`user.json`), game per run, auto-zip per run (`ZIP_STORED`, verified). Friends do **not** clean. Manifests keep clip SHA-256, file timing, sanitised probe, actual frame timestamps, slot pairing, recipe, tool/ffmpeg/x264 versions, sizes and hashes; uncompressed size + file count for ingest-side bomb checks. **Track** handoff size vs source by resolution. |
| **Rationale** | Cap was solving a size-anxiety problem; the real need is knowing how much the sparse still pack saves at 1080 / 1440 / 4K. Native stills keep train-size, aspect, HUD-crop (D15) and docs flexibility on my side, so I never have to ask for clips again. Embeddable Python avoids the antivirus friction of an unsigned PyInstaller exe and stays patchable. |
| **Date** | 2026-11-16 (revised: drop cap; spec v1) |
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

---

## Decision log (newest first)

| Date | ID | Change |
|---|---|---|
| 2026-11-16 | D25 | Tool renamed friend pack → **Frame Export Kit** (`gfc-frame-export`, package `frame_export`); its zips are contributor packs |
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
