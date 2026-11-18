# Public dataset use plan (draft)

Draft justification and operational plan for using creator-licensed public gameplay datasets in this **course / personal, non-commercial** project. Complements [public-game-datasets.md](public-game-datasets.md). **Does not close D12.**

**Hard filter (2026-11-18):** keep only packages that ship **labelled still frames** or **labelled videos** (game/class label on the media). Drop metadata-only catalogs, annotation tables without media, and non-gameplay UI crops. Live list: [public-sources-ledger.md](public-sources-ledger.md).

**Working stance (for this draft):** for school and local personal research, rely on the **dataset creator’s stated license** when it permits non-commercial / educational use with clear attribution. Publisher IP is noted but not treated as an automatic blocker for *local, non-redistributed* training in this course context. This is a project ethics note, not legal advice.

**Related:** [source acquisition](../roadmap/tools/source-acquisition.md) · [data layout](../data-layout.md) · [D12](../design-decisions.md#d12--confirmed-sources-for-lol-overwatch-2-marvel-rivals) · [D19](../design-decisions.md) · [D26](../design-decisions.md) · [D33](../design-decisions.md)

---

## Draft justification (course / personal)

**Need.** Current runs cover Valorant, League of Legends and CS2 only ([results](../results.md)). Minecraft, Overwatch 2 and Marvel Rivals lack enough local footage for the ~2–3k frames/game target. Public research dumps are the only near-term way to add Minecraft volume; OW2 / Rivals still lean on personal and friends’ clips.

**Use.** Frames stay **local**, are **not redistributed**, and train a student project classifier. Reports name sources and licenses. That matches the proposal’s non-commercial, provenance-reportable data story and source-acquisition ethics fields (`source → terms note → date accessed`).

**Creator terms.** Prefer datasets whose authors publish MIT, Apache-2.0, CC BY, or CC BY-NC / BY-NC-SA for the packaged media. Attribution is kept in a ledger (below) so obligations are visible and removable.

**Limits we accept in the draft.**

- NC licenses (**MineRL** as BY-NC-SA, **PAWA**, **Game-Intention**) are fine for the course; they must be **removed before any monetization**.
- YouTube-derived packs (**Gameplay Images**, **Gamed**) are last-resort / thin probes: creator CC BY on packaging, weak provenance, leakage risk if frames are shuffled.
- Public data does **not** replace personal/friends captures for OW2 / Marvel Rivals volume or for in-the-wild Minecraft (shaders, packs, Bedrock).

**What we will not do under this draft.** Scrape Twitch/YouTube/esports without a dataset license; mix several public dumps into one `<source>` folder; redistribute third-party gameplay media in the repo or a public model card beyond required attribution text.

---

## Freeness ranking (creator packaging)

Rank is **freest → most constrained** for *this* local educational use. “Freest” means fewest ongoing obligations and easiest path if the project later goes commercial (after dropping NC sources).

| Rank | Tier | Meaning | Datasets |
|---:|---|---|---|
| 1 | **Permissive research media** | MIT (or equivalent) on the released demos; keep copyright notice; no NC clause from the dataset authors | **BEDD / BASALT** demos; **OpenAI VPT** contractor demos (MIT + Mojang disclaimer on the card) |
| 2 | **Attribution-only (CC BY)** | Free to use if you attribute; commercial use of the *packaging* is often allowed under CC BY, but YouTube/game residual rights remain messy — treat as course-OK, monetize-only-after-review or drop | **Gameplay Images** (Minecraft stills); **Gamed** (Valorant/CS2) |
| 3 | **Non-commercial / share-alike** | Explicitly OK for school/personal NC; **must drop before monetization**; ShareAlike may affect how derivatives are shared | **MineRL** (treat as **CC BY-NC-SA 4.0** despite Zenodo MIT label — confirm before download); **PAWA** (CC BY-NC 4.0); **Game-Intention** OW subset (CC BY-NC 4.0) |
| 4 | **Last-resort stills** | Uploader-tagged free packaging on labelled screenshots | **MARVELRIVALSYOLO** (Apache-2.0 tag) |

Dropped by the labelled-media filter: MineDojo YT metadata, LoL-V2T annotations-only, OW2 killfeed crops, match-stat tables, ungated VOD scrapes. See the ledger.

**Suggested prototype order**

1. **Gamed** stills — `python scripts/prototype_public_stills.py --dataset gamed`
2. **Gameplay Images** Minecraft stills — same script `--dataset gameplay_images`
3. Later: VPT / BEDD / MineRL videos via `data/raw/.../public_*/` + `gfc-make-sources`
4. OW2 / Rivals: personal/friends first; optional Game-Intention / MARVELRIVALSYOLO for D12

---

## What needs to be done to use each

Common steps for every public source:

1. Add a ledger row (`status: planned` → `active` when files land).  
2. Create **one** folder under `frame_sources/<Game>/public_…/` (stills) or `data/raw/<Game>/public_…/` then make-sources (videos). Never mix datasets in one source folder.  
3. Record URL, license SPDX, attribution blurb, date accessed, and “commercial OK?” on the ledger.  
4. Ingest → clean → split with **clip/session** units (D01/D02); enforce source caps (D33).  
5. **Toggle for a run** without deleting files: pick a split preset under `config/splits/` or set `include_source_kinds` / `exclude_sources` in a new `split_id` (see [dataset-splitter.md](../roadmap/tools/dataset-splitter.md)).  
6. Cite active ledger rows that actually appear in that run’s `sources.csv`.  
7. To remove a dataset for good: ledger `retired` + delete its `public_*` tree + rebuild.

| Source id (proposed) | Game(s) | Tier | Before first use | Ingest notes | Attribution obligation (while active) | Drop before monetize? |
|---|---|---|---|---|---|---|
| `public_vpt_contractor` | Minecraft | 1 | Prefer official Azure indexes from [Video-Pre-Training](https://github.com/openai/Video-Pre-Training/); save LICENSE + README disclaimer quote; date-stamp | Keep each `.mp4` as its own clip; do not merge with MineRL | MIT notice + credit OpenAI VPT; note Minecraft © Microsoft/Mojang | Optional (permissive); drop if you want personal-only |
| `public_bedd_basalt` | Minecraft | 1 | Zenodo/OpenAI links from BEDD paper; confirm MIT datasheet text still present | Trajectory/session identity; separate from VPT folder even if visually similar | MIT notice + BEDD/BASALT citation | Optional |
| `public_minerl` | Minecraft | 3 | **Resolve** GitHub BY-NC-SA vs Zenodo MIT in writing (or treat as NC-SA); copy LICENSE into ledger | Contiguous demos as clips; optional texture variant as metadata, not a second game | CC BY-NC-SA attribution + share-alike if you redistribute adaptations (we will not redistribute media) | **Yes — required** |
| `public_pawa` | Minecraft | 3 | Accept HF gate; confirm CC BY-NC + Usage Guidelines on card | Episodes as clips; watch size (TB-scale) | CC BY-NC attribution | **Yes — required** |
| `public_gameplay_images` | Minecraft | 2 | Kaggle canonical; avoid relying on HF mirror alone; accept no official clip IDs | **Fabricate clip groups** from filename/order or one synthetic clip per N frames so splits are not frame-shuffled; label limitation in ledger | CC BY 4.0 + credit Adit Magotra / Kaggle dataset | Strongly drop before monetize (YouTube provenance) |
| `public_gamed` | Valorant, CS2 | 2 | HF card; use `video_id` for splits; ignore authors’ leaky frame split | One source id, or `public_gamed_valorant` / `public_gamed_cs2` if you want per-game folders | CC BY 4.0 + credit dataset card; note Valve/Riot residual | Strongly drop before monetize |
| `public_game_intention_ow` | Overwatch_2 | 3 | Read full card; confirm NC; sample HUD coverage | Preserve video/clip ids if present | CC BY-NC attribution | **Yes — required** |
| `public_marvelrivals_yolo` | Marvel_Rivals | 4 | Record Apache tag + that these are replay screenshots | Stills → treat each file or small groups as clips; weak session story | Apache-2.0 NOTICE if required by the tag | Drop before monetize (thin rights story) |

**OW2 / Rivals volume without public dumps:** keep recording under personal and `contributor_*` sources; that remains the conservative path and needs no public attribution.

---

## Tracking active public sources (attribution in, attribution out)

### Design choice

Use **two layers**, both keyed by the same `<source_id>`:

1. **On disk (already decided layout):** `data/raw/<Game>/<source_id>/` and `data/frame_sources/<Game>/<source_id>/…` — deleting the tree removes the data from training once catalog/split are rebuilt (D19, D26).
2. **Tracked ledger (new):** `docs/research/public-sources-ledger.md` (or later a generated CSV the catalog can read) — the **only** place that lists which public datasets are **active**, their SPDX license, and the exact attribution sentence for reports.

Personal and friends’ sources stay out of this ledger (they are not third-party dataset attributions). Optional: a `kind=personal|contributor|public` field in a future catalog ethics column; until then, the `public_` prefix marks public rows.

### Ledger columns (draft)

| Column | Purpose |
|---|---|
| `source_id` | Folder name under each game (`public_minerl`, …) |
| `status` | `planned` \| `active` \| `retired` |
| `games` | e.g. `Minecraft` |
| `dataset_name` | Human name |
| `official_url` | Stable URL |
| `license_spdx` | e.g. `MIT`, `CC-BY-4.0`, `CC-BY-NC-SA-4.0` |
| `commercial_ok` | `yes` / `no` / `review` (NC ⇒ `no`) |
| `attribution_text` | Exact blurb for the report / README ethics section |
| `date_accessed` | ISO date terms were checked |
| `date_activated` / `date_retired` | When data entered or left training |
| `notes` | Leakage rules, mirror warnings, license conflicts |

### How attribution stays in sync

| Event | Actions |
|---|---|
| Activate a dataset | `status: active`; write attribution_text; put files only under that `source_id`; rebuild catalog/split; report lists all **active** rows |
| Unhappy with one dataset | `status: retired` + `date_retired`; delete `data/**/<source_id>/`; rebuild catalog/split; retrain; report regenerates from active rows only → that attribution disappears |
| Monetize later | Retire **every** row with `commercial_ok: no` (and preferably all `public_*` if you want personal-only); delete those trees; retrain on personal/contributor only; public attribution section empty or historical footnote |
| Audit | `sources.csv` from `gfc-split` already reports per-source share; cross-check that every `public_*` in data appears as `active` in the ledger and vice versa |

### Report wording (template)

While any public row is active, the ethics / data section can say:

> Training includes third-party research datasets listed in `docs/research/public-sources-ledger.md` (active rows only). Each is stored under its own `source_id` so it can be removed without touching personal or contributor footage. Licenses and attribution text are copied from that ledger. Non-commercial-licensed sources will be removed before any commercial use.

### What we are *not* doing in this draft

- Committing raw public videos or frames to git.
- Putting attribution only in a one-off README sentence with no ledger (easy to forget a drop).
- Closing D12 or editing source-acquisition policy until you approve names for LoL / OW2 / Rivals.

---

## Open for your approval

1. Keep `public_gamed` + `public_gameplay_images` active for course experiments, or retire them after the smoke?
2. Next video prototype: `public_vpt_contractor` / `public_bedd_basalt` / `public_minerl`?
3. For D12 (OW2 / Rivals): personal/friends only, or also `public_game_intention_ow` / `public_marvelrivals_yolo`?

Prototype stills for Gamed and Gameplay Images were downloaded into this worktree’s gitignored `data/` only (not the main checkout).

