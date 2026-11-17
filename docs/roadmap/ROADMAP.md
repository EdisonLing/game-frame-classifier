# Frame to Game — Roadmap

CNN that maps a single gameplay frame → one of six games (Valorant, League of Legends, CS2, Minecraft, Overwatch 2, Marvel Rivals) or **unknown** (D24; threshold first, optional trained 7th later).

**Focus:** frame classification only. Clip / interval tagging is not a model change — it is deterministic multi-frame inference (sample frames → predict → majority vote / threshold). Defer that until after the model works.

**Working assumption:** start with personal clips you already have to build and verify the data tools; only after that pipeline is solid do we chase volume from public/streamer sources.

**Related docs:** [docs index](../INDEX.md) · [data layout](../data-layout.md) · [design decisions](../design-decisions.md)

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
| Stages 2–7 | **not started** | Split / volume / baseline / CNN still ahead — see note below |

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

```text
raw clips / videos
    → catalog (paths, game label, source meta)
    → extract frames (ffmpeg, ~1 / 5s)
    → clean + dedupe (black/blur/junk + pHash)
    → resize 256×144 + store metadata
    → split by video/session (not by frame)
    → [train] augment (jitter, mild scale, random low-bitrate)
    → baseline / CNN
    → evaluate (accuracy, F1, confusion, quality tiers)
```

Quality tiers: on disk **full + low (45)**; train samples one at random; eval reports both (D04).

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
| Batch extract | **implemented** | Catalog → `data/frames/<Game>/<source>/<stem>/`; skip-if-done; `--game` / `--limit` / `--force`; summary JSON; CLI `gfc-batch-extract` | — |
| Frame extractor | **implemented** | Single video → frames @ 5s, 256×144 JPEG, CSV/JSON manifest, CLI `gfc-extract-frames` / module API; unit + synthetic system + optional personal smoke (20s stream-copy trim) | [tools/frame-extractor.md](tools/frame-extractor.md) |
| Frame cleaner | **implemented** | Manifest in → kept/reject manifests; black + blur + aHash dedupe; reasons logged. **Gaps:** D11 detector not coded yet (rule decided); thresholds are v1 defaults (tunable via CLI) | [tools/frame-cleaner.md](tools/frame-cleaner.md) |
| Quality encoder | **implemented** | Video CRF then extract; ops **full + low(45)**; medium=38 optional/docs (D04) | [tools/quality-encoder.md](tools/quality-encoder.md) |
| Friend pack | **spec locked** | Plug-and-play toolset for friends: clips → native-res stills (full + crf45) zip with full metadata; same `sourcing` code as my clips (D25–D27) | [tools/friend-pack.md](tools/friend-pack.md) |

**Stage 1 exit (almost):** catalog + batch extract + clean + quality tiers work. Remaining Stage 1 polish: **D11 lobby detector** (after first multi-game volume). Friend pack is optional volume help, not a Stage 1 blocker.

---

### Stage 2 — Dataset assembly *(~2 days)*
Turn cleaned frames into train/val/test without leakage.

| Tool | One-liner | Why it matters | Detail |
|---|---|---|---|
| Dataset splitter | Split by **video/session**, not frame (~70/15/15; personal holdout) | Frame-random splits leak near-duplicates (TwitchCategory failure mode) | [tools/dataset-splitter.md](tools/dataset-splitter.md) |
| Augmentation pipeline | Mild scale + colour/brightness jitter + random low-bitrate on a fraction of train frames | Improves robustness; must run **after** split | [tools/augmentation.md](tools/augmentation.md) |

**Exit:** reproducible manifests for train/val/test; personal sessions held out; class counts plotted.

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
| 5 | [Dataset splitter](tools/dataset-splitter.md) | 2 | planned | — |
| 6 | [Augmentation pipeline](tools/augmentation.md) | 2 | planned | — |
| 7 | [Source acquisition](tools/source-acquisition.md) | 3 | planned | — |
| 8 | [Colour-histogram baseline](tools/baseline.md) | 4 | planned | — |
| 9 | [CNN trainer](tools/cnn-trainer.md) | 5 | planned | — |
| 10 | [Clip tagger (optional demo)](tools/clip-tagger.md) | 7 | deferred | — |

---

## Suggested near-term order

1. ~~Stage 0 setup~~ ✅  
2. ~~Frame extractor (single-video + tests)~~ ✅  
3. ~~Frame cleaner~~ ✅ — D11 detector still to implement (rule decided)  
4. ~~Quality encoder~~ ✅  
5. ~~Clip catalog~~ ✅  
6. ~~Batch extract~~ ✅  
7. Drop more personal/friend clips → catalog → batch extract → clean  
8. Splitter + class-count plots *(~2 days)*  
9. Baseline end-to-end *(~1–2 days)*  
10. First CNN train run *(~2 days)*  
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
