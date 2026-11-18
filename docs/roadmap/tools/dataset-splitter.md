# Dataset splitter (`gfc-split`)

**Stage:** 2 — Dataset assembly  
**Status:** implemented
**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md)

## What it does (high level)

Groups clips into recording sessions, assigns each session to `train`, `val`, `test_session` or `test_source`, picks the quality tier of every slot, and writes the split manifests and the per-game data tables. Assignments are stored in a ledger so they never change when more clips arrive.

## Why we need it

Frame-random splits leak near-duplicates from one video into train and test, the failure called out for TwitchCategory in the proposal. Every model number depends on this step being right, and on it staying right while contributors keep sending footage.

## Connections

| | |
|---|---|
| **Reads** | `data/manifests/slots_clean.csv` (from the [cleaner](frame-cleaner.md)), `data/manifests/clips_index.csv` (from [`gfc-derive-frames`](derive-frames.md)), `config/split.json`, its own `ledger.csv` |
| **Writes** | `data/manifests/splits/<split_id>/` |
| **Read by** | [loader](dataset-loader.md), [baseline](baseline.md), [CNN trainer](cnn-trainer.md), [evaluation](evaluation.md) |

## Usage

```text
gfc-split                      # draft: assign new clips, rewrite manifests
gfc-split --plan               # print sessions and per-source sizes; write nothing
gfc-split --reset              # draft only: forget the ledger and assign from scratch
gfc-split --freeze             # lock this split_id (needs the gate in config filled in)
python -m game_frame_classifier.dataset_splitter
```

| Flag | Meaning |
|---|---|
| `--data-root` | Data root (default `data`) |
| `--config` | Split policy (default `config/split.json`) |
| `--plan` | Report only |
| `--reset` | Delete the ledger of an unfrozen `split_id` first; refused once frozen |
| `--freeze` | Write `freeze.json`; refused while `test_design` in the config is empty |

Exit codes: `0` success, `1` policy conflict (see Ledger rules), `2` usage or missing input.

## Config (`config/split.json`)

```json
{
  "schema": "gfc.split/1",
  "split_id": "v1",
  "seed": 360,
  "targets": { "train": 0.70, "val": 0.15, "test_session": 0.15 },
  "session_gap_min": 30,
  "holdout_sources": {},
  "max_source_share": 1.0,
  "test_design": ""
}
```

| Key | Meaning |
|---|---|
| `split_id` | Folder name under `splits/`. A different policy gets a new id and its own ledger |
| `targets` | Share of each game's slots per split, among sources that are not held out |
| `session_gap_min` | Session rule (below) |
| `holdout_sources` | `{ "<Game>": ["<source>", ...] }`; every clip of those sources for that game goes to `test_source` |
| `max_source_share` | Largest share of one game's **train** slots a single source may hold; `1.0` = no cap |
| `test_design` | One line stating the agreed held-out design (gate G1). Empty until agreed; `--freeze` refuses while empty |

## Behaviour

### 1. Sessions (D30)

Within one `(game, source)`:

1. Clips with a `recorded_start_utc` are sorted by it. A clip's end is start + `duration_s`.
2. A clip joins the current session when its start is no later than the session's latest end + `session_gap_min`. Overlapping clips always share a session.
3. A clip with no recorded start is its own session.
4. Sessions are labelled `<source>:<game>:s<NNN>` in time order, untimed ones last by `clip_key`. The label is for reports and can renumber when earlier footage arrives; the ledger is keyed by clip, and nothing should key on a session label across runs.

Clips whose start time comes only from file modification time (`recorded_start_source = mtime`) are used but counted in the report as low-trust.

### 2. Split assignment (D31)

Splits, from least to most held out: `train` < `val` < `test_session` < `test_source`.

For each session:

1. **Held-out source.** If the source is listed in `holdout_sources` for that game, the session is `test_source`.
2. **Known clips.** Otherwise, if any of its clips is already in the ledger, the session takes the most held-out split among them. This matters when a new clip bridges two sessions that were assigned to different splits:
   - **Draft:** clips that were in a less held-out split move up and are listed in `reassigned.csv`.
   - **Frozen:** no assigned clip moves, because a model trained earlier may already have seen it. The bridging clip is left out (`unused.csv`, reason `bridges_splits`) and the two old sessions stay as they were; in the split files each part is labelled `<session>.<split>`, so no session label spans two splits.
3. **New session.** Otherwise it is placed by greedy fill, after every session with ledger entries has been counted. Per game, new sessions are visited in order of `sha256("<seed>:<smallest clip_key in session>")`. Each goes to the split with the largest deficit `target − current share`, where shares count kept slots of that game already assigned to `train`, `val` and `test_session`. Ties go to `train`, then `val`, then `test_session`. Before that, while a game has no session yet in `train`, `val` or `test_session`, a new session goes to the first empty one in that order, so a game with three sessions has one in each.

Every clip of the session is then written to the ledger.

**Ledger rules**

- A clip never moves to a less held-out split. After freezing, it never moves at all.
- Freezing locks the policy and every existing assignment, not the contents: new footage still lands in all splits, so the test sets grow. Every result records the split hashes, and [`--compare`](evaluation.md#comparison---compare) only pairs runs scored on the same snapshot. For the final report, all models are scored on one snapshot.
- A ledger entry that contradicts the config (a clip in `train` or `val` whose source is now in `holdout_sources`, or a `test_source` clip whose source is no longer listed) is a policy change: the run stops with exit code `1` and asks for a new `split_id`.
- A source with no ledger entries yet can be added to `holdout_sources` at any time, including after freezing.
- `--reset` exists only for drafts.

### 3. Source cap (D33)

Applied to `train` only, after assignment. The effective cap for a game is `max(max_source_share, 1 / k)`, where `k` is the number of sources with train slots in that game; a tighter cap cannot be met and would drop everything. While any source holds more than the effective cap of a game's used train slots, that source's slots are thinned by dropping those with the highest `sha256("<seed>:<slot_id>")` until it fits. Dropped slots are listed in `unused.csv` with reason `source_cap`. `val` and the test splits are never thinned. With the default `1.0` nothing is dropped and shares are only reported.

### 4. Quality tier (D04)

```text
offset = int(sha256(clip_key)[:8], 16)
tier   = "crf45" if (bucket + offset) % 2 == 1 else "full"
```

Applied to every used slot in every split. `path` is `path_low` for `crf45` and `path_full` for `full`. A slot with an empty `path_low` (quick-mode clip, D04) is always `full`.

### 5. Class balance (D34)

No downsampling. All kept slots are used (subject to the source cap); the trainers apply class weights computed from `train`.

## Outputs (`data/manifests/splits/<split_id>/`)

| File | Content |
|---|---|
| `train.csv`, `val.csv`, `test_session.csv`, `test_source.csv` (+ `.json`) | One row per used slot |
| `ledger.csv` | `clip_key, split, first_assigned_utc, note` |
| `sessions.csv` | `clip_key, game, source, session, recorded_start_utc, recorded_start_source, duration_s, slots_kept, split` |
| `counts.csv` | `game, split, slots, slots_full, slots_low, slots_quick, clips, sessions, sources`, with `ALL` rows per game and per split |
| `sources.csv` | `game, source, source_kind, split, slots, share` (share of that game's slots in that split) |
| `unused.csv` | Kept slots not used, with reason (`source_cap`, `bridges_splits`) |
| `reassigned.csv` | Clips moved to a more held-out split, with the run time and reason |
| `summary.json` | Resolved config, input file hashes, `split_hashes` (`{split name: SHA-256 of its CSV}`, read by `split_manifest.split_hashes`), counts, warnings, `frozen` |
| `freeze.json` | Written by `--freeze`: time, git commit, `test_design` text |

**Split file columns**

| Column | Notes |
|---|---|
| `slot_id`, `clip_key`, `bucket`, `target_time_s` | From `slots_clean` |
| `game`, `label` | Label index per [training pipeline 3.2](../../training-pipeline.md) |
| `source`, `source_kind`, `session` | For per-source and per-clip breakdowns |
| `split`, `tier` | |
| `path` | The image to use (relative to the data root) |
| `path_full`, `path_low` | Both tiers, for the per-tier diagnostic |
| `public_examples_ok` | From `clips_index`; controls which frames may appear in figures |

`counts.csv` and `sources.csv` are the per-game frames, videos and channels tables for reports (D14).

**Warnings** (in `summary.json` and on the console): a game with an empty split (`test_source` only when the game has held-out sources); a game with fewer than three sessions among non-held-out sources; a tier share outside 45–55 % for a game and split with 200 or more slots; any source above 1/15 of a game's train slots (the proposal's cap, reported even when not enforced); low-trust or missing recording times.

## Gates

### G1 — Held-out test design (D32): decide together before `--freeze`

The mechanism above is fixed. What it should hold out is not, and it cannot be changed quietly afterwards: once a test split has been evaluated, redefining it makes every earlier number incomparable.

| Question | Options |
|---|---|
| Which test sets exist | (A) `test_session` only: every source appears in training, different sessions are held out. (B) `test_session` plus `test_source`: for games with enough sources, one or more whole sources are never trained on. (C) `test_source` only |
| Which sources are held out, per game | Chosen from `gfc-split --plan` once most footage is in. Guideline for (B): games with at least three sources; hold out about 10–20 % of the game's slots; never the largest source |
| How the proposal's two test sets map | Proposal: unseen streamers, and held-out personal sessions. Contributors are separate people with their own settings and overlays, so a held-out contributor plays the role of an unseen streamer until public sources exist |
| Session rule | Confirm `session_gap_min` (30) or switch to one session per recording day after reading the session report |
| Test numbers in the progress report | Default (D13): none; report `val`. Alternative: one logged evaluation of `test_session` |

Suggested: (B). It keeps both test sets from the proposal and directly measures whether the model has learned a person's overlay or settings instead of the game.

Until G1 is recorded in `test_design`:

- `gfc-split` runs in draft mode; drafts can be reset.
- Baseline and CNN can be trained and compared on `train` / `val`.
- `gfc-evaluate` refuses `test_session` and `test_source` (no `freeze.json`).

### Not a gate, but confirm before writing a report's data section (D33)

The proposal promised 15 or more channels per game with each capped at 1/15. Current footage is a few people per game, where that cap would discard most of the data. Default now: no cap, shares reported, per-source accuracy in evaluation. Because the cap only thins `train`, it can be tightened later (for example once public sources are added under D12) without touching any held-out set.

## Working defaults

| | Default | Alternative |
|---|---|---|
| Targets | 70 / 15 / 15 per game | Proposal's 60–70 % train for personal clips with a larger held-out share |
| Session gap (D30) | 30 min | Per recording day; longer gap for long-match games |
| Fill scope | Balance per game across all sources | Balance per game and source |
| Source cap (D33) | Off (`1.0`) | `0.0667` (proposal) or a relaxed value |
| Balance (D34) | Class weights | Downsample to the smallest class |

## Testing

| Kind | Cases |
|---|---|
| **Unit: sessions** | Overlapping clips share a session; gap just under / just over the limit; untimed clips are singletons; grouping never crosses game or source |
| **Unit: assignment** | No session in two splits; shares approach targets on a synthetic set of 40 sessions; first three sessions of a game land in three different splits; same seed gives the same result, another seed a different order |
| **Unit: ledger** | Rerun with added clips leaves every earlier clip's split unchanged; in a draft a bridging clip moves the less held-out side up and writes `reassigned.csv`; after freeze the bridging clip is unused with `bridges_splits` and nothing moves; config contradicting the ledger exits `1`; `--reset` refused after freeze |
| **Unit: holdout and cap** | Held-out source appears only in `test_source`; cap thins train only and deterministically; `1.0` drops nothing; a cap below `1 / k` is raised to `1 / k` |
| **Unit: tier** | Rule matches the formula; each clip is half and half to within one slot; unchanged by adding clips |
| **System** | Temp manifests → CLI → reload every split file: disjoint clip sets, disjoint sessions, every `path` equals the path of its tier, counts in `counts.csv` match the files; `--freeze` refused with empty `test_design`, accepted when set |

**How to run:** `pytest tests/unit/test_dataset_splitter.py tests/system/test_dataset_splitter.py`

**Critical property:** the leakage test (a session or clip in more than one split) and the ledger stability test must always stay green.

## Acceptance checks

- [x] No clip or session in more than one split
- [x] Rerun after adding footage changes no existing assignment
- [x] Held-out sources absent from `train` and `val`
- [x] Tier shares about half and half per game and split
- [x] `counts.csv` and `sources.csv` give frames, clips, sessions and sources per game
- [x] `--freeze` blocked until `test_design` is filled in
- [x] CLI entry `gfc-split` in `pyproject.toml`

## Ties to proposal and decisions

Data Processing, Splits paragraph. D01, D02, D03, D04, D13, D14, D30–D34.
