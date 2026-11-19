# Label review (`gfc-review-labels`)

**Stage:** 2 — Data quality  
**Status:** specified (after the interim write-up)  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [clip sorter](clip-sorter.md) · [frame cleaner](frame-cleaner.md) · [evaluation](evaluation.md)

## What it does (high level)

Uses a trained model to find frames whose label may be wrong or which are not usable game frames, and shows them in a local page so a person decides: the label is right (a real model error), the frame is not usable (quarantine), or the whole clip has the wrong game (label override). Decisions feed back into the pipeline through the cleaner's quarantine list and a clip label override file.

## Why we need it

Labels come per clip, from folder or file names, so mistakes arrive in clip-sized chunks: a mislabelled clip puts 10–40 wrong frames into training or into a measured split. Menus, lobbies and loading screens inside a game's clips are another kind of noise (D11). A model that confidently disagrees with a label is the cheapest pointer to both (confident learning); a person checks only those frames. On the first 7-way run, val had 86 flagged frames in 26 clips out of 1,250.

## Rules

- **Never on test splits.** Choosing which test frames to fix from the model's mistakes would bias the final score (D13). `test_session` and `test_source` are refused.
- **No self-review of training frames.** A model has largely memorised its own training frames. For `train`, predictions come from out-of-fold models (step 2 below), never from the model that trained on them.
- Decisions change the data only through the existing cleaner quarantine and one new override file; nothing is deleted.

## Connections

| | |
|---|---|
| **Reads** | A run folder (`run.json`, `eval/val/predictions.csv`, or predictions made here); split folder; `data/frames/` |
| **Writes** | `data/review/<session>/` (decisions, cache); appends to `data/manifests/quarantine.csv`; writes `data/manifests/label_overrides.csv` |
| **Then** | `gfc-derive-frames` (applies overrides), `gfc-clean-frames --slots` (applies quarantine), `gfc-split`, retrain |

## Usage

```text
gfc-review-labels --run data/runs/cnn/<run_id> --split val                 # step 1: val, from the run's evaluation
gfc-review-labels --oof --split-dir data/manifests/splits/v1 --folds 5     # step 2: out-of-fold predictions for train
gfc-review-labels --oof-dir data/review/oof_<id> --split train             # step 2: review train
gfc-review-labels ... --min-conf-wrong 0.9 --max-conf 0.6                  # flag thresholds
python -m game_frame_classifier.label_review ...
```

| Flag | Meaning |
|---|---|
| `--run` | Run folder whose `eval/<split>/predictions.csv` is used (val) |
| `--split` | `val` or `train` (test splits refused, exit 2) |
| `--oof` | Make out-of-fold predictions for `train` (step 2) |
| `--folds` | Folds for `--oof` (default 5) |
| `--oof-dir` | Out-of-fold predictions to review |
| `--max-conf` | Flag frames whose top probability is below this (default 0.6) |
| `--min-conf-wrong` | "Confidently wrong" threshold, used for ordering (default 0.9) |
| `--session`, `--port`, `--no-open`, `--data-root` | As in the clip sorter |

## Behaviour

1. **Flag.** From predictions (`slot_id, label, pred, confidence, p_*`): a frame is flagged when the prediction differs from the label, or the top probability is below `--max-conf`. Frames already decided in an earlier session are skipped.
2. **Out-of-fold predictions (train).** Split `train` into `--folds` groups by recording session (`session` column; whole sessions per fold, assigned by `sha256("<seed>:<session>")`). For each fold, train the run's model type and config on the other folds (same `label_set`, seed, early stopping on that run's val) and predict the held-out fold. Write `data/review/oof_<id>/predictions.csv` in the evaluation's format plus `oof.json` (folds, sessions per fold, run config, commit). About 5 short GPU runs.
3. **Order.** Group flagged frames by clip. Clips first where most frames disagree in the same direction (likely a wrong clip label), then by the highest-confidence disagreement; within a clip, by confidence.
4. **Page** (reuses the clip sorter's server and page code): the frame at 256×144 shown large plus the clip's other frames as a strip, the label, the top three predictions with probabilities, clip name and person alias. Keys:

   | Key | Decision | Effect |
   |---|---|---|
   | `C` | Label correct; the model is wrong | Recorded only (a real model error; appears in the review report) |
   | `Q` | Not a usable frame (menu, lobby, desktop, loading, black) | Appends `slot_id, manual:<reason>, note` to `quarantine.csv` (asks the reason once: `lobby`, `menu`, `desktop`, `loading`, `other`) |
   | `R` | The whole clip is labelled wrong | Asks for the right class (`1`–`6`, `7` Other with a name); writes `clip_key, game, other_name, note` to `label_overrides.csv` |
   | `S` | Skip | — |
   | `U` | Undo | — |
   | `A` | Apply the current decision to every flagged frame of this clip | For `C` and `Q` |

5. **Saving.** Decisions appended to `data/review/<session>/decisions.csv` after each key (resumable, like the sorter). Quarantine and override files are written when the session ends or on `--apply`, appending only new rows and never duplicating a `slot_id` or `clip_key`.
6. **Report.** `review_report.json` and `.md`: counts by decision, by class and by alias; clips relabelled; quarantine reasons; model errors confirmed (`C`) by class pair. The quarantined frames with their reasons are the hand-labelled sample the lobby detector (D11) needs.

## Pipeline changes

- **`label_overrides.csv`** (`clip_key, game, other_name, note`): `gfc-derive-frames` applies it when it builds `clips_index` (the clip's `game` and `other_name`, and the derived frames' folder); the original value is kept in a new `game_original` column. Overrides of clips already in a ledger keep their split (the ledger is by clip).
- **`quarantine.csv`**: unchanged format, already read by the cleaner.

## Never

- Never review or change anything in `test_session` or `test_source` rows.
- Never delete frames or clips; never edit `frame_sources/`.
- Never overwrite an existing quarantine or override row.

## Testing

| Kind | Cases |
|---|---|
| **Unit: flags** | Wrong and low-confidence frames flagged; thresholds; decided frames skipped |
| **Unit: folds** | Whole sessions per fold; deterministic; every train session in exactly one fold |
| **Unit: order** | Clip-level disagreement first; confidence ordering |
| **Unit: outputs** | Quarantine rows appended once with `manual:<reason>`; overrides written once; undo; resume |
| **Unit: derive** | Override changes `clips_index.game`, keeps `game_original`, moves the derived folder; other clips unchanged |
| **Guards** | Test splits refused (exit 2); train without `--oof-dir` refused |
| **System** | Synthetic split + a fake run's predictions → page API decisions → quarantine and overrides → derive and clean apply them |

## Acceptance checks

- [ ] Val review from a run's predictions, with quarantine and overrides applied by the next derive and clean
- [ ] Out-of-fold predictions for train, by whole sessions
- [ ] Test splits refused
- [ ] Review report lists confirmed model errors and quarantine reasons
- [ ] CLI entry `gfc-review-labels` in `pyproject.toml`

## Build instructions

Written for an agent that builds exactly this and decides nothing; ask the user if anything is unclear.

1. **Package** `src/game_frame_classifier/label_review/` with `__init__.py` (`__version__ = "1.0.0"`), `__main__.py`, `flags.py`, `oof.py`, `store.py`, `server.py`, `page.html`, `apply.py`, `cli.py`. Reuse `clip_sorter.store` patterns (append-only decisions, replay with a per-item history so undo steps back one) and the sorter's server structure; do not import the sorter's page.
2. **`flags.py`**: `load_predictions(path) -> list[Row]`; `flag(rows, max_conf, decided) -> list[Row]`; `group_and_order(flagged, all_rows) -> list[ClipGroup]` (Behaviour 1 and 3).
3. **`oof.py`**: `assign_folds(rows, folds, seed) -> dict[session, fold]`; `run_oof(run_dir, split_dir, folds, out_dir)`: for each fold write a temporary split folder (train = other folds, val = the run's val) and call `train.train_run` or `baseline.train_baseline` with the run's config; predict the held-out fold with the fold model's predictor; write `predictions.csv` and `oof.json` (Behaviour 2). GPU through the usual device rule.
4. **`store.py`**: decisions CSV `utc, slot_id, clip_key, decision, game, other_name, reason, note`; `append`, `replay`, `undo` semantics as in the sorter.
5. **`server.py` / `page.html`**: endpoints `GET /`, `GET /api/state`, `GET /frame/<slot_id>.jpg` (from `data/frames/`), `POST /api/decide`, `POST /api/undo`; keys as in Behaviour 4; 127.0.0.1 only.
6. **`apply.py`**: `apply(session_dir, data_root)` appends new quarantine rows and override rows (Behaviour 5); `report(session_dir)` (Behaviour 6).
7. **`derive_frames.py`**: read `data/manifests/label_overrides.csv` if present; apply as in Pipeline changes; add `game_original` to `CLIPS_INDEX_COLUMNS`; tests.
8. **`cli.py`**: argparse as in Usage; refuse test splits (exit 2); `sys.stdout.reconfigure(errors="replace")`.
9. **`pyproject.toml`**: `gfc-review-labels = "game_frame_classifier.label_review.cli:main"`. **`.gitignore`**: `data/review/`. **`docs/data-layout.md`**: `data/review/`, `label_overrides.csv`.
10. **Tests** as in the Testing table. Update `docs/roadmap/tools/derive-frames.md` (overrides) and this spec's status.
