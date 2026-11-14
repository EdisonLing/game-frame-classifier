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
| D04 | Eval at **three compression levels** (CRF 0/28/38) | decided | |
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
| **Status** | open |
| **Prompt** | TA Data Processing −0.5: no definition of “dominated by non-game content” |
| **Options** | (A) Hand rules (black/blur + manual quarantine) (B) Simple lobby/menu detector + threshold, validated on a hand-labelled sample (C) Drop only black/blur for v1; defer non-game heuristic (D) Other: ___ |
| **Decision** | |
| **Rationale** | |
| **Date** | |
| **Links** | [tools/frame-cleaner.md](roadmap/tools/frame-cleaner.md) |

**Note:** Proposal keeps menus/HUD as valid gameplay frames (D06). “Non-game” should mean desktop/browser/facecam-heavy/etc., not “has a menu.”

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
| **Status** | open |
| **Options** | CSV · JSONL · Parquet · other |
| **Decision** | |
| **Rationale** | |
| **Date** | |

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
| **Options** | ffmpeg video CRF roundtrip · JPEG quality proxy · both |
| **Decision** | ffmpeg H.264 CRF round-trip for stills; CRF 0 = byte-copy |
| **Rationale** | Matches proposal CRF numbers; JPEG-only qscale would diverge from eval language |
| **Date** | 2026-11-13 |
| **Links** | [tools/quality-encoder.md](roadmap/tools/quality-encoder.md) |

### D23 — Training stack / hardware

| | |
|---|---|
| **Status** | open |
| **Options** | Local PyTorch · Colab · both |
| **Decision** | |
| **Rationale** | |
| **Date** | |

---

## Decision log (newest first)

| Date | ID | Change |
|---|---|---|
| 2026-11-14 | D19 | Game-first `raw/<Game>/<source>/` (final for collection) |
| 2026-11-14 | D19 | Source-first draft tried same day; superseded |
| 2026-11-13 | D22 | Quality encoder: ffmpeg CRF round-trip; tiers full/medium/low = 0/28/38 |
| 2026-11-12 | D11 | Still open; cleaner ships black/blur/dedupe only (no lobby/non-game detector) |
| 2026-11-12 | — | Frame cleaner implemented (Pillow aHash + FIND_EDGES blur var≥400); no pipeline manager yet |
| 2026-11-12 | D21 | JPEG locked for frame extractor v1 |
| 2026-11-12 | — | Frame extractor implemented (subprocess ffmpeg, resize-on-extract); catalog still deferred |
| 2026-11-12 | — | File created; TA feedback indexed; D10–D17 opened from TA notes; D01–D07 marked keep |
