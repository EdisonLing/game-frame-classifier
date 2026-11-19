# Frame to Game — Roadmap

CNN that maps a single gameplay frame → one of six games (Valorant, League of Legends, CS2, Minecraft, Overwatch 2, Marvel Rivals) or **unknown** (D24; threshold first, optional trained 7th later).

**Focus:** frame classification only. Clip / interval tagging is not a model change — it is deterministic multi-frame inference (sample frames → predict → majority vote / threshold). Defer that until after the model works.

**Working assumption:** start with personal clips you already have to build and verify the data tools; only after that pipeline is solid do we chase volume from public/streamer sources.

**Related docs:** [docs index](../INDEX.md) · [training pipeline](../training-pipeline.md) · [data layout](../data-layout.md) · [design decisions](../design-decisions.md)

---

## Progress snapshot

| Area | Status | Extent |
|---|---|---|
| Planning docs (roadmap, tool pages, design decisions) | **done** | Living docs; open decisions still blank until we decide them |
| Stage 0 — repo / env / pytest | **done** | See Stage 0 checklist below |
| Stage 1 — frame extractor | **implemented** | Single-video CLI/API + unit/system/personal tests |
| Stage 1 — batch extract | **implemented** | `gfc-batch-extract` over catalog → `frames/<Game>/<source>/<stem>/` |
| Stage 1 — frame cleaner | **implemented** | Black / blur / aHash dedupe + reject log; D11 detector planned (rule decided) |
| Stage 1 — quality encoder | **implemented** | Video CRF then extract; **ops = full + low(45)**; medium=38 docs/reference (D04) |
| Stage 1 — clip catalog | **implemented** | Scans `data/raw/<Game>/<source>/` → `clips.csv` + `clips.json`; absolute paths; ffprobe meta |
| Stage 1 — Frame Export Kit | **implemented** | Contributor clips → zip; release canary pending | [tools/frame-export-kit.md](tools/frame-export-kit.md) |
| Stage 1 — ingest pack | **implemented** | Zip → `data/frame_sources/`; make-sources still missing (D26) | [tools/ingest-pack.md](tools/ingest-pack.md) |
| Stage 1 — make-sources, derive, slot-mode clean | **specified** | Personal clips into `frame_sources`, 256×144 derive + slot index, per-slot cleaning | [training-pipeline.md](../training-pipeline.md) |
| Stages 2, 4, 5 — split, loader, baseline, CNN, evaluation | **specified** | Specs ready to build; held-out test design is an open gate (D32) | [training-pipeline.md](../training-pipeline.md) |
| Stages 3, 6, 7 | **not started** | Volume, writeups, hardening |

**Verified:** extractor + cleaner tests green; sample under `data/frames/valorant_smoke/` and cleaned output under `data/frames/valorant_smoke_cleaned/`.

**At-a-glance diagram:** [pipeline-status.md](../pipeline-status.md) (done vs missing for auto-all-raws).

### Pipeline manager?

**Not yet.** Each tool is manifest in → manifest out (`extract` → `clean` → later `split`). Chain with CLI or a thin `gfc-run` script later. Avoid heavy workflow engines until batch volume hurts.

---

## Timeline (approximate)

Durations are rough working estimates, not calendar dates.

| Phase | Approx. effort | Notes |
|---|---|---|
| Stage 1 remainder (D11 detector; optional batch clean) | ~0.5–1 day | Lobby/non-game filter after first multi-game extract |
| Stage 2 — splitter + augmentation | ~2 days | Leak-free splits before any model numbers |
| Stage 3 — scale volume | ~2 days | Can overlap once tools work |
| Stage 4 — baseline | ~1–2 days | Histogram + logistic regression + figures |
| Stage 5 — first CNN train/eval | ~2 days | Feasibility results, not final polish |
| Stage 6 — mid-project writeup | ~1–2 days | Package data + baseline + CNN results |
| Stage 7 — hardening + final writeup | ~2 weeks | Full eval, remaining data, optional clip-tag demo |

**Near-term priority:** finish Stage 1–2 on personal clips quickly → Stage 3 volume → baseline → first CNN → mid-project writeup. Do not spend the whole next stretch only on tooling.

### Does “personal clips first” still make sense?

**Yes for tooling. Not enough alone for a mid-project check-in.**

| Mid-project ask | Personal-clips-first tools | Still needed soon after |
|---|---|---|
| Data processing done + stats + examples | Build extract / clean / split / quality tools on your clips | Scale to **most** of the target (~2–3k frames/game) once tools work |
| Plan for never-before-seen test data | Hold out personal sessions as a personal-clip test set | Also plan unseen-streamer public test videos |
| Baseline + quantitative/qualitative results | Same cleaned frames feed the baseline | Implement colour-histogram + logistic regression and run it |
| Primary CNN + results | Same dataset | Train at least a first CNN and show curves / sample preds |

---

## High-level pipeline

**Target (D26):** raw / contributor pack → native `frame_sources` (full + crf45) → derive 256×144 → clean → split → …  
**Interim (works today):** catalog → batch extract straight to 256×144 `frames/` → clean → optional quality encoder → …

```text
raw clips ── gfc-make-sources ──┐
contributor zips ── gfc-ingest-pack ──┴─► frame_sources (native, full + crf45)
    → gfc-derive-frames          256×144 frames + clips_index + slots
    → gfc-clean-frames --slots   one verdict per slot (black / blur / near-dupe / quarantine)
    → gfc-split                  sessions → train / val / test_session / test_source, tier per slot
    → loader + augmentation      (train only: mild zoom, colour jitter; no flips)
    → gfc-train-baseline / gfc-train-cnn
    → gfc-evaluate               accuracy, F1, confusion, per tier / source / clip
```

Files passed between the steps, shared conventions and open decisions: [training-pipeline.md](../training-pipeline.md). The interim catalog → batch extract path remains for single-clip debugging only (D29).

Quality tiers: on disk **full + low (45)**; every frame used (train/val/test, baseline, CNN) is **half full, half low**, fixed per slot (D04, revised 2026-11-17); per-tier eval is a diagnostic.

---

## Stages

### Stage 0 — Repo & environment ✅ **complete** (~done)
Scaffold so tools and tests can land without rework.

- [x] Python env + dependency list (`requirements.txt` / `pyproject.toml`, editable install)
- [x] Folder layout: `src/game_frame_classifier/`, `tests/{unit,system,helpers}/`, `data/frames/` (local); `data/raw`, `data/manifests`, `notebooks/` still unused placeholders as needed
- [x] `ffmpeg` / `ffprobe` confirmed on PATH (system tests skip if missing)
- [x] `.gitignore` extended for `data/raw|frames|manifests` and media (`*.mp4`, etc.)
- [x] pytest wired — real suite, not empty smoke (`pytest` / `pytest -m "not personal"`)

**Exit met:** import package, run pytest, call ffmpeg.

**Not in Stage 0 (still open elsewhere):** locking remaining design decisions (D10–D17); creating empty `notebooks/` unless we need it.

---

### Testing convention (every tool)

Each tool page has a **Testing** section. Default rule:

| Kind | What | Where |
|---|---|---|
| **Unit** | Pure logic with no real video (schemas, hash distance, split assignment, histogram dims, vote aggregation) | `tests/unit/` — fast, CI-friendly, synthetic fixtures |
| **System / integration** | Real ffmpeg or a tiny synthetic clip end-to-end | `tests/system/` — may skip if ffmpeg missing |
| **Manual spot-check** | Visual “does this look right?” (blur reject, HUD not flipped) | Documented on the tool page; not a substitute for automated tests |

**Fixture policy:** do not commit large personal clips. Use a tiny synthetic video (e.g. generated by ffmpeg in the test, or a ≤2s checked-in fixture under `tests/fixtures/`). Personal-clip smoke runs stay local.

---

### Stage 1 — Personal-clip data tools *(in progress, ~2 days remaining)*
Prove every data step on clips you already have before caring about volume.

| Tool | Status | Extent | Detail |
|---|---|---|---|
| Clip catalog | **implemented** | Walk `data/raw/<Game>/<source>/` → `clips.csv` + `clips.json`; absolute paths; duration/width/height via ffprobe; CLI `gfc-catalog-clips` | [tools/clip-catalog.md](tools/clip-catalog.md) |
| Batch extract | **implemented (interim)** | Catalog → `data/frames/<Game>/<source>/<stem>/` at 256×144; skip-if-done; `--game` / `--limit` / `--force` / `--clean`; CLI `gfc-batch-extract`. Superseded for dataset building once `gfc-make-sources` exists (D26) | [pipeline-status.md](../pipeline-status.md) |
| Frame extractor | **implemented** | Single video → frames @ 5s, 256×144 JPEG, CSV/JSON manifest, CLI `gfc-extract-frames` / module API; unit + synthetic system + optional personal smoke (20s stream-copy trim) | [tools/frame-extractor.md](tools/frame-extractor.md) |
| Frame cleaner | **implemented** | Manifest in → kept/reject manifests; black + blur + aHash dedupe; reasons logged. **Gaps:** D11 detector not coded yet (rule decided); thresholds are v1 defaults (tunable via CLI) | [tools/frame-cleaner.md](tools/frame-cleaner.md) |
| Quality encoder | **implemented** | Video CRF then extract; ops **full + low(45)**; medium=38 optional/docs (D04) | [tools/quality-encoder.md](tools/quality-encoder.md) |
| Frame Export Kit | **implemented** | `gfc-frame-export` + `scripts/build_frame_export.py`; release checklist (sandbox run, friend canary) pending. Plug-and-play toolset for friends: clips → native-res stills (full + crf45) zip with full metadata; same `sourcing` code as my clips (D25–D27) | [tools/frame-export-kit.md](tools/frame-export-kit.md) |
| Ingest pack | **implemented** | `gfc-ingest-pack`: validate contributor zip → `data/frame_sources/` (D26); optional extra tests (zip-of-packs, Other, consent refuse) still open | [tools/ingest-pack.md](tools/ingest-pack.md) |

**Stage 1 exit (almost):** catalog + batch extract + clean + quality + Frame Export Kit + ingest work. Remaining: **D11 lobby detector** (after first multi-game volume); **[`gfc-make-sources`](tools/make-sources.md) + [`gfc-derive-frames`](tools/derive-frames.md) + cleaner slot mode** to finish the D26 path (specified, not built). Frame Export Kit release canary is optional volume help, not a Stage 1 blocker.

---

### Stage 2 — Dataset assembly *(~2 days)*
Turn cleaned frames into train/val/test without leakage.

| Tool | One-liner | Why it matters | Detail |
|---|---|---|---|
| Dataset splitter | Split by **session**, not frame (70/15/15 + held-out sources); ledger keeps assignments stable as footage arrives; assigns the tier of every slot | Frame-random splits leak near-duplicates (TwitchCategory failure mode) | [tools/dataset-splitter.md](tools/dataset-splitter.md) |
| Dataset loader and augmentation | One reader for both models; train-only mild zoom + colour jitter, no flips | Baseline and CNN see identical frames; augmentation never touches val/test | [tools/dataset-loader.md](tools/dataset-loader.md) |

**Exit:** reproducible split manifests; held-out sets defined (gate D32) and frozen; per-game counts generated.

---

### Stage 3 — Scale volume *(~2 days, after tools work)*
Same tools, more sources. Mid-project check-in wants **most** of the data in place.

| Tool | One-liner | Why it matters | Detail |
|---|---|---|---|
| Source acquisition | Collect / download permitted public gameplay + fallback datasets | Personal clips alone likely won’t hit 2–3k frames/game with enough channel diversity | [tools/source-acquisition.md](tools/source-acquisition.md) |

Constraints from the proposal (keep when collecting):

- 15+ channels per game where possible
- Cap any one channel (incl. pro/esports or personal) at ~1/15 of that game’s frames
- Prefer terms-permitted sources; fallbacks: Gamed (Valorant/CS2), Gameplay Images / MineRL (Minecraft)
- Frames stay local; never redistribute

**Exit:** class-balanced dataset approaching target size; per-channel stats; plan written for final never-seen test data.

---

### Stage 4 — Baseline model *(~1–2 days)*
Non-deep sanity check before (and beside) the CNN.

| Tool | One-liner | Why it matters | Detail |
|---|---|---|---|
| Colour-histogram baseline | RGB histogram → multinomial logistic regression | Required mid-project comparison; shows palette-only performance vs spatial CNN | [tools/baseline.md](tools/baseline.md) |

**Exit:** quantitative metrics + a few qualitative examples (e.g. Minecraft easy, OW2 vs Marvel Rivals hard).

---

### Stage 5 — Primary CNN *(~2 days for first results)*
From-scratch CNN on 256×144 RGB frames (proposal architecture as starting point).

| Tool | One-liner | Why it matters | Detail |
|---|---|---|---|
| CNN train / eval loop | Train, validate, checkpoint, basic metrics | Core model | [tools/cnn-trainer.md](tools/cnn-trainer.md) |

**Exit for mid-project check-in:** architecture diagram, param count rough idea, ≥1 quantitative + ≥1 qualitative result, short note on challenges.

**Later (final hardening):** unknown-class confidence threshold; flatten vs GAP experiment; quality-tier eval; unseen-streamer + personal-clip breakdowns.

---

### Stage 6 — Mid-project writeup *(~1–2 days)*
Package what exists; keep text short and figure-heavy.

- Brief project description (input = frame, output = game / unknown)
- Data processing section: sources, cleaning steps, class counts, example frames, plan for new test data
- Baseline results
- Primary model results
- Feasibility argument for finishing the remaining stages

---

### Stage 7 — Hardening + final writeup *(~2 weeks)*
- Finish remaining data / channel diversity if still short
- Tune CNN; run full evaluation suite (per-game F1, confusion, quality tiers)
- Optional: unknown threshold; majority-vote clip tagging as a **demo**, not a model change — [tools/clip-tagger.md](tools/clip-tagger.md)
- Final writeup

---

## Tool index

| # | Tool | Stage | Status | Extent |
|---|---|---|---|---|
| 1 | [Clip catalog](tools/clip-catalog.md) | 1 | **implemented** | Scan raw → clips.csv/json |
| 1b | Batch extract | 1 | **implemented** | `gfc-batch-extract` over catalog |
| 2 | [Frame extractor](tools/frame-extractor.md) | 1 | **implemented** | Single-video extract + tests |
| 3 | [Frame cleaner](tools/frame-cleaner.md) | 1 | **implemented** | Black/blur/dedupe + reject log; D11 planned |
| 4 | [Quality encoder](tools/quality-encoder.md) | 1 | **implemented** | Ops full+low(45); medium docs-only (D04) |
| 4b | [Make sources](tools/make-sources.md) | 1 | **implemented** | Personal clips → `frame_sources` |
| 4c | [Derive frames](tools/derive-frames.md) | 1 | **implemented** | 256×144 + `clips_index` / `slots` |
| 4d | [Clip sorter](tools/clip-sorter.md) | 1 | **implemented** | Contact sheets in a local page; label, disable or trash; copies into `data/raw/` |
| 4e | [Clip link downloader](tools/clip-link-downloader.md) | 1 | **implemented** (Medal only) | Medal clip links → files with game and time in the name; other sites refused (YouTube etc. later) |
| 4e.1 | [Clip link auto sources](tools/clip-link-auto-source.md) | 1 | **implemented** | One source per Medal uploader (`friend_<username>` by default, remembered; block in the uploader file); sorter takes sources from folders |
| 4f | [Label review](tools/label-review.md) | 2 | specified | Flag frames a model disagrees with; quarantine, confirm or relabel; out-of-fold for train |
| 4g | [Public dataset licences](tools/public-licenses.md) | 1 | specified | Save each public dataset's licence before its media; generated attribution document for active sources; per-split licence list |
| 5 | [Dataset splitter](tools/dataset-splitter.md) | 2 | **implemented** | Sessions, ledger splits, tiers, data tables, train cap, source groups |
| 6 | [Dataset loader and augmentation](tools/dataset-loader.md) | 2 | **implemented** | Shared reader + train transforms |
| 7 | [Source acquisition](tools/source-acquisition.md) | 3 | planned | — |
| 8 | [Colour-histogram baseline](tools/baseline.md) | 4 | **implemented** | 48-bin histogram + logistic regression |
| 9 | [CNN trainer](tools/cnn-trainer.md) | 5 | **implemented** | Four-block CNN, 9.83 M parameters |
| 9b | [Evaluation](tools/evaluation.md) | 4–5 | **implemented** | Shared metrics, figures, comparison, open-set metrics |
| 9c | [Other class (6-way / 7-way)](tools/other-class.md) | 2–5 | **implemented** | Other as a seventh class, compared with a threshold-only model (D24) |
| 10 | [Clip tagger (optional demo)](tools/clip-tagger.md) | 7 | deferred | — |

---

## Suggested near-term order

1. ~~Stage 0 setup~~ ✅  
2. ~~Frame extractor (single-video + tests)~~ ✅  
3. ~~Frame cleaner~~ ✅ — D11 detector still to implement (rule decided)  
4. ~~Quality encoder~~ ✅  
5. ~~Clip catalog~~ ✅  
6. ~~Batch extract~~ ✅  
7. `gfc-make-sources` → `gfc-derive-frames` → cleaner slot mode (build order in [training-pipeline.md](../training-pipeline.md) §6)  
8. Splitter, loader, evaluation  
9. Baseline end-to-end  
10. First CNN train run; settle the held-out test design (D32) and freeze the split  
11. Mid-project figures + writeup *(~1–2 days)*  
12. D11 lobby detector after first multi-game extract (when label noise shows up)  


---

## Docs layout

See also [`../INDEX.md`](../INDEX.md).

```text
docs/
  INDEX.md
  design-decisions.md
  roadmap/
    ROADMAP.md
    tools/
```
