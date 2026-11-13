# Frame to Game — APS360 Roadmap

CNN that maps a single gameplay frame → one of six games (Valorant, League of Legends, CS2, Minecraft, Overwatch 2, Marvel Rivals).

**Course focus:** frame classification only. Clip / interval tagging is not a model change — it is deterministic multi-frame inference (sample frames → predict → majority vote / threshold). Defer that until after the model works.

**Working assumption:** start with personal clips you already have to build and verify the data tools; only after that pipeline is solid do we chase volume from public/streamer sources.

**Related docs:** [docs index](../INDEX.md) · [design decisions](../design-decisions.md)

---

## Progress snapshot *(updated 2026-11-12)*

| Area | Status | Extent |
|---|---|---|
| Planning docs (roadmap, tool pages, design decisions, docs layout) | **done** | Living docs; open decisions still blank until we decide them |
| Stage 0 — repo / env / pytest | **done** | See Stage 0 checklist below |
| Stage 1 — frame extractor | **implemented** | Single-video CLI/API + unit/system/personal tests; **not** batch-over-catalog yet |
| Stage 1 — frame cleaner | **implemented** | Black / blur / aHash dedupe + reject log; D11 non-game filter **not** included |
| Stage 1 — catalog / quality encoder | **not started** | Next up: catalog or quality encoder |
| Stages 2–7 | **not started** | No heavy pipeline framework yet — see note below |

**Verified:** extractor + cleaner tests green; sample under `data/frames/valorant_smoke/` and cleaned output under `data/frames/valorant_smoke_cleaned/`.

### Pipeline manager?

**Not yet.** Each tool is manifest in → manifest out (`extract` → `clean` → later `split`). For APS360, chain with CLI or a thin `gfc-run` script later. Avoid Airflow/Prefect-style systems until batch volume hurts.

---

## Project deadlines

| Deliverable | Weight | Deadline |
|---|---|---|
| Project Proposal | 5% | Fri Oct 16 — done |
| **Progress Report** | **5%** | **Fri Nov 20** |
| Final Report | 10% | Tue Dec 8 |

Progress report expects: **most/all data**, a **baseline with results**, a **primary CNN with results**, plus a short feasibility argument.

---

## Does “personal clips first” align with next week?

**Yes for tooling. Not enough alone for the progress report.**

| Progress-report ask | Personal-clips-first tools | Still needed by Nov 20 |
|---|---|---|
| Data processing done + stats + examples | Build extract / clean / split / quality tools on your clips | Scale to **most** of the target (~2–3k frames/game) once tools work |
| Plan for never-before-seen test data | Hold out personal sessions as a personal-clip test set | Also plan unseen-streamer public test videos |
| Baseline + quantitative/qualitative results | Same cleaned frames feed the baseline | Implement colour-histogram + logistic regression and run it |
| Primary CNN + results | Same dataset | Train at least a first CNN and show curves / sample preds |

**Practical order for the next ~8 days:** finish Stage 1–2 on personal clips quickly → Stage 3 volume → Stage 4 baseline → Stage 5 first CNN → package into progress report. Do not spend the whole week only on tooling.

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

Quality re-encoding is shared by **augmentation** and **quality-tier eval** (CRF 0 / 28 / 38).

---

## Stages

### Stage 0 — Repo & environment ✅ **complete**
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
| **System / integration** | Real ffmpeg or a tiny checked-in fixture clip end-to-end | `tests/system/` — may skip if ffmpeg/fixture missing |
| **Manual spot-check** | Visual “does this look right?” (blur reject, HUD not flipped) | Documented on the tool page; not a substitute for automated tests |

**Fixture policy:** do not commit large personal clips. Use a tiny synthetic video (e.g. generated by ffmpeg in the test, or a ≤2s checked-in fixture under `tests/fixtures/`). Personal-clip smoke runs stay local and undocumented paths.

---

### Stage 1 — Personal-clip data tools *(in progress)*
Prove every data step on clips you already have before caring about volume.

| Tool | Status | Extent | Detail |
|---|---|---|---|
| Clip catalog | planned | — | [tools/clip-catalog.md](tools/clip-catalog.md) |
| Frame extractor | **implemented** | Single video → frames @ 5s, 256×144 JPEG, CSV/JSON manifest, CLI `gfc-extract-frames` / module API; unit + synthetic system + optional personal smoke (20s stream-copy trim). **Gaps:** no catalog-driven batch; full-clip personal runs are manual CLI (not default in pytest); game label still passed by hand | [tools/frame-extractor.md](tools/frame-extractor.md) |
| Frame cleaner | **implemented** | Manifest in → kept/reject manifests; black + blur + aHash dedupe; reasons logged. **Gaps:** no D11 non-game/lobby detector; thresholds are v1 defaults (tunable via CLI) | [tools/frame-cleaner.md](tools/frame-cleaner.md) |
| Quality encoder | planned | **next candidates:** catalog or this | [tools/quality-encoder.md](tools/quality-encoder.md) |

**Stage 1 exit (not met yet):** folder of labelled personal clips → cleaned labelled frame set + low-quality variants. Extract + clean work on smoke-scale data; no batch catalog / quality tiers yet.

---

### Stage 2 — Dataset assembly (still personal clips)
Turn cleaned frames into train/val/test without leakage.

| Tool | One-liner | Why it matters | Detail |
|---|---|---|---|
| Dataset splitter | Split by **video/session**, not frame (~70/15/15; personal holdout) | Frame-random splits leak near-duplicates (TwitchCategory failure mode) | [tools/dataset-splitter.md](tools/dataset-splitter.md) |
| Augmentation pipeline | Mild scale + colour/brightness jitter + random low-bitrate on a fraction of train frames | Improves robustness; must run **after** split | [tools/augmentation.md](tools/augmentation.md) |

**Exit:** reproducible manifests for train/val/test; personal sessions held out; class counts plotted.

---

### Stage 3 — Scale volume *(after tools work)*
Same tools, more sources. Progress report wants **most** of the data by Nov 20.

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

### Stage 4 — Baseline model
Non-deep sanity check before (and beside) the CNN.

| Tool | One-liner | Why it matters | Detail |
|---|---|---|---|
| Colour-histogram baseline | RGB histogram → multinomial logistic regression | Progress-report required; shows palette-only performance vs spatial CNN | [tools/baseline.md](tools/baseline.md) |

**Exit:** quantitative metrics + a few qualitative examples (e.g. Minecraft easy, OW2 vs Marvel Rivals hard).

---

### Stage 5 — Primary CNN
From-scratch CNN on 256×144 RGB frames (proposal architecture as starting point).

| Tool | One-liner | Why it matters | Detail |
|---|---|---|---|
| CNN train / eval loop | Train, validate, checkpoint, basic metrics | Core graded model | [tools/cnn-trainer.md](tools/cnn-trainer.md) |

**Exit for progress report:** architecture diagram, param count rough idea, ≥1 quantitative + ≥1 qualitative result, short note on challenges.

**Later (final report):** unknown-class confidence threshold; flatten vs GAP experiment; quality-tier eval; unseen-streamer + personal-clip breakdowns.

---

### Stage 6 — Progress report package *(due Fri Nov 20)*
Write to the rubric, not a second research paper.

- Brief project description (input = frame, output = game / unknown)
- Data processing section: sources, cleaning steps, class counts, example frames, plan for new test data
- Baseline results
- Primary model results
- Feasibility argument for Dec 8

LaTeX, ≤3 pages main text. Template lives under [`../proposal/source/`](../proposal/source/).

---

### Stage 7 — Final report hardening *(Nov 20 → Dec 8)*
- Finish remaining data / channel diversity if still short
- Tune CNN; run full evaluation suite (per-game F1, confusion, quality tiers)
- Optional: unknown threshold; majority-vote clip tagging as a **demo**, not a model change — [tools/clip-tagger.md](tools/clip-tagger.md)
- Final report (10%)

---

## Tool index

| # | Tool | Stage | Status | Extent |
|---|---|---|---|---|
| 1 | [Clip catalog](tools/clip-catalog.md) | 1 | planned | — |
| 2 | [Frame extractor](tools/frame-extractor.md) | 1 | **implemented** | Single-video extract + tests; no batch catalog yet |
| 3 | [Frame cleaner](tools/frame-cleaner.md) | 1 | **implemented** | Black/blur/dedupe + reject log; D11 deferred |
| 4 | [Quality encoder](tools/quality-encoder.md) | 1 | planned | — |
| 5 | [Dataset splitter](tools/dataset-splitter.md) | 2 | planned | — |
| 6 | [Augmentation pipeline](tools/augmentation.md) | 2 | planned | — |
| 7 | [Source acquisition](tools/source-acquisition.md) | 3 | planned | — |
| 8 | [Colour-histogram baseline](tools/baseline.md) | 4 | planned | — |
| 9 | [CNN trainer](tools/cnn-trainer.md) | 5 | planned | — |
| 10 | [Clip tagger (optional demo)](tools/clip-tagger.md) | 7 | deferred | — |

---

## Suggested near-term order (now → Nov 20)

1. ~~Stage 0 setup~~ ✅  
2. ~~Frame extractor (single-video + tests)~~ ✅  
3. ~~Frame cleaner~~ ✅ — D11 non-game rule still open  
4. Clip catalog (batch) **or** quality encoder  
5. Optional thin CLI orchestrator (`extract → clean`) once batching hurts  
6. Splitter + class-count plots  
7. More personal clips / public sources (volume)  
8. Baseline end-to-end  
9. First CNN train run  
10. Progress report figures + writeup  

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
