# Other as a seventh class (6-way / 7-way switch)

**Stage:** 2–5 — data through evaluation  
**Status:** specified  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md) · decision [D24](../../design-decisions.md)

## What it does (high level)

Adds `Other` (anything that is not one of the six games: other games, desktop, video) as a class the pipeline carries from raw footage to evaluation, and makes the label set a switch: the baseline and the CNN train either **6-way** (the six games; Other frames left out of training) or **7-way** (six games plus Other). Evaluation scores both on the same rows, including how well each flags content that is not one of the six games, so the choice is made by measurement (D24).

## Why we need it

A 6-way model with a confidence threshold has never seen a negative example; other shooters share the HUD cues the model relies on and would be called one of the six with high confidence. Training with explicit non-target examples (outlier exposure) usually detects unfamiliar content better. It can also cost six-game accuracy, and a plain background class is not the strongest open-set method, so the project decides with its own data rather than by assumption.

## Connections

| | |
|---|---|
| **Reads** | `data/raw/_other/<name>/<source>/` (own clips), `frame_sources/_other/<name>/<source>/` (ingested Other packs, already written by `gfc-ingest-pack`) |
| **Changes** | `sourcing/labels.py`, [`gfc-make-sources`](make-sources.md), [`gfc-derive-frames`](derive-frames.md), [`gfc-split`](dataset-splitter.md), [loader](dataset-loader.md), [baseline](baseline.md), [CNN trainer](cnn-trainer.md), [evaluation](evaluation.md) |
| **Unchanged** | Frame Export Kit and ingest (they already produce and place Other packs); extraction; the cleaner |

## Labels

- `sourcing.labels.CLASSES = GAMES + (OTHER,)`: the six games keep indices 0–5, `Other` is 6. Every split row uses this index, so existing six-game splits stay valid.
- Two label sets, named in configs and `run.json`: `six` = `GAMES`, `seven` = `CLASSES`.
- `other_name` (normalised by `normalize_other_name`) records what an Other clip shows (`Apex_Legends`, `desktop`, `mixed_other`). It is metadata for reports and held-out selection, never a label.

## Data

1. **`gfc-make-sources`**: also walks `data/raw/_other/<name>/<source>/` and writes `frame_sources/_other/<name>/<source>/<clip_key>/`, the layout ingest already uses. `clip.json` gets `game = "Other"` and `other_name`. `--game Other` limits a run to Other footage; `--budget-hours` applies per `(other_name, source)`.
2. **`gfc-derive-frames`**: also walks `frame_sources/_other/`, writes `frames/_other/<name>/<source>/<clip_key>/`, and adds an `other_name` column to `clips_index` and `slots` (empty for the six games). `--game Other` works like the other games.
3. **Cleaner**: unchanged. Near-duplicates are compared within `(game, source)`, so all of one person's Other footage is one comparison group.
4. **`gfc-split`**: Other is a class like the six games: sessions per `(game, source)`, the same targets and greedy fill, the same train cap (D33, per source) and source limits. New config key:

   | Key | Meaning |
   |---|---|
   | `holdout_other` | `["<other_name>", ...]`: every Other clip with that name goes to `test_source`, whoever recorded it. This is how evaluation sees content the model never trained on. Same ledger rule as `holdout_sources`: a clip already in `train` or `val` for a newly listed name is a policy change (exit 1, new `split_id`). Default `[]` |

   New output `other_names.csv`: `other_name, split, slots, sessions, sources, share` (share of the split's Other slots), so the variety of Other is visible. `counts.csv` and the warnings include Other like a game.
5. **Loader**: `split_manifest` validates `label == CLASSES.index(game)`. `load_split(..., label_set="six")` drops Other rows; `label_set="seven"` keeps them. Default `seven`.

## Training (baseline and CNN)

- Config key `label_set`: `"seven"` (default) or `"six"`, in `config/baseline.json` and `config/train_cnn.json`; also `--set label_set=six` for the CNN.
- `six`: train and val read without Other rows; outputs 6. `seven`: Other rows included; outputs 7; class weights from train cover all seven (D34).
- `run.json` records `label_set` and `labels` (6 or 7 names). Parameter count for the default CNN at 7 outputs: 9,828,135 (FC 256→7).
- Early stopping and `C` selection use macro-F1 over the run's own label set on val.
- `seven` with no Other rows in train refuses to run (exit 2: "no Other frames in train; use label_set six"), so a seventh output is never trained without examples.

## Evaluation

`gfc-evaluate` reads the run's `labels`. On every scored split:

- **`metrics.json` as today**, over the run's labels (per-class, confusion, `by_*`).
- **`six_game`**: accuracy and macro-F1 over rows of the six games only, where any prediction other than the true game is wrong (a 7-way model calling a Valorant frame Other is an error). This is the number compared across label sets.
- **`open_set`**, the detection of non-six content, the same for both label sets:
  - Score per row: `s = 1 − max over the six games of p(game)` (a 7-way model's probability mass on Other raises `s`).
  - Threshold `τ`: chosen on **val** so that 5 % of val's six-game rows are flagged (`s > τ`): a fixed false-alarm rate. Stored in `eval/val/open_set.json`; scoring another split reuses it and refuses to run before val has been scored.
  - Reported: `tau`; `false_alarm_rate` (six-game rows flagged); `other_detection_rate` (Other rows flagged); `auroc` (s separating Other from six-game rows, threshold-free); `coverage` and `accuracy_on_covered` (six-game rows not flagged, and how many of those are right); for 7-way also `argmax_other_rate` (Other rows whose top class is Other).
  - When a split has no Other rows, only `tau`, `false_alarm_rate`, `coverage` and `accuracy_on_covered` are reported.
- **`--compare`** shows `six_game` and `open_set` side by side for two runs on the same split hash, with **paired bootstrap 95 % confidence intervals** for the differences: resample whole videos (`clip_key`) with replacement, 1,000 times, seed 360, score both runs on each resample (`six_game` macro-F1 difference, `other_detection_rate` difference at each run's own `tau`, `auroc` difference), and take the 2.5th and 97.5th percentiles. Resampling videos rather than frames respects that frames of one video are not independent.

The decisive numbers come from `test_source` once `holdout_other` names are held out and the split is frozen (G1). Before that, `val` Other rows (other content in a different session) give a development reading only.

## Decision rule (D24)

On the same frozen split, scored on `test_source` (held-out Other names and held-out people), 7-way plus threshold is kept over 6-way plus threshold if:

- the `other_detection_rate` difference (7-way minus 6-way) at 5 % false alarms has a 95 % bootstrap interval entirely above 0, and
- the `six_game` macro-F1 difference has a 95 % interval whose lower end is above −0.02.

Otherwise 6-way plus threshold is kept. `auroc` and its interval are reported beside the rule as the threshold-free view. Both runs, the intervals and the outcome are reported either way. A fixed margin (for example "10 points") is not used: it cannot be met when 6-way is already near the ceiling, and on a few dozen videos a fixed margin is within noise.

## Data guidance (for collecting Other footage)

- Never the six games, including streams or compilations that show them; menus and lobbies of the six games stay with their game (D06).
- Variety over volume: many different games and kinds of content, each a separate `<name>`. Shooters with HUDs (the hardest negatives), other MOBAs, block or survival games, desktop, browser, video players.
- Hold out whole names for testing (`holdout_other`), chosen with G1, and never the only shooter in Other.

## Testing

| Kind | Cases |
|---|---|
| **Unit: labels** | `CLASSES` order; `Other` is 6; six-game indices unchanged |
| **Unit: make-sources / derive** | `_other/<name>/<source>` extracted and derived to the expected paths; `other_name` in `clip.json`, `clips_index`, `slots`; `--game Other` |
| **Unit: split** | Other rows get label 6; `holdout_other` sends every clip of a name to `test_source` from any source; ledger contradiction exits 1; `other_names.csv` counts |
| **Unit: loader** | `label_set` six drops Other rows, seven keeps them |
| **Unit: evaluation** | `six_game` on a 7-way model counts Other predictions on game rows as wrong; `tau` gives the 5 % false-alarm rate on a known val; detection rate, AUROC, coverage on hand-built probabilities; test-split scoring refuses before val; bootstrap resamples videos, is reproducible with the seed, and gives an interval containing the observed difference |
| **Unit: trainers** | `seven` without Other rows in train exits 2 |
| **System** | Synthetic split with Other rows → baseline and CNN train in both label sets → `run.json` labels and parameter count; evaluation writes `six_game` and `open_set`; `--compare` of a 6-way and a 7-way run |

## Acceptance checks

- [ ] Own Other clips go from `data/raw/_other/` to split rows with label 6; ingested Other packs too
- [ ] `label_set` switch in both trainers; `run.json` records it
- [ ] `six_game` and `open_set` in `metrics.json` for both label sets; `--compare` shows them with paired bootstrap intervals over videos
- [ ] `holdout_other` places whole names in `test_source`
- [ ] Existing six-game splits, runs and tests unchanged

## Ties to proposal and decisions

D24 (revised 2026-11-18), D04, D06, D13, D33, D34, D38. Proposal: "unknown" output; this replaces a threshold-only design with a measured choice between threshold-only and a trained Other class plus threshold.
