# Evaluation and report figures (`gfc-evaluate`)

**Stage:** 4–5 — shared by the baseline and the CNN  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md)

> Spec answers while building: matplotlib is required in `.venv-rocm` via the `train` optional group and is checked in [amd-gpu-setup.md](../../amd-gpu-setup.md) §2.3; figure writers still skip with a printed note if matplotlib is missing so metrics work in lean environments.

## What it does (high level)

Scores six-way and seven-way runs, including six-game classification and open-set detection, and writes the metrics, figures and paired run comparison the reports need.

## Why we need it

Both models must be measured by the same code on the same rows, or their comparison is not trustworthy. It is also the only door to the held-out test splits, so access to them is controlled and logged in one place (D13).

## Connections

| | |
|---|---|
| **Reads** | A run folder from [`gfc-train-baseline`](baseline.md) or [`gfc-train-cnn`](cnn-trainer.md); split manifests from [`gfc-split`](dataset-splitter.md) through the [loader](dataset-loader.md) |
| **Writes** | `<run>/eval/<split>/`, `data/runs/holdout_access.jsonl`, comparison and data-report folders |
| **Called by** | Both trainers at the end of training (`split = val`), and by hand |

`run.json` fields evaluation relies on (trainers must write these): `run_id`, `model_type`, `labels`, `split_dir`, `split_id`, `split_hashes` (`{split name: sha256}`, same shape as `split_manifest.split_hashes`).

## Usage

```text
gfc-evaluate --run data/runs/cnn/<run_id> --split val
gfc-evaluate --run data/runs/cnn/<run_id> --split val --tier-diagnostic
gfc-evaluate --run data/runs/cnn/<run_id> --split test_source --reason "final evaluation"
gfc-evaluate --compare data/runs/baseline/<run_id> data/runs/cnn/<run_id> --split val
gfc-evaluate --data-report --split-dir data/manifests/splits/v1
python -m game_frame_classifier.evaluation ...
```

| Flag | Meaning |
|---|---|
| `--run` | Run folder; its `run.json` names the split folder and model type |
| `--split` | `train`, `val`, `test_session`, `test_source` |
| `--tier-diagnostic` | Also score every row at `full` and at `low` |
| `--reason` | Required for test splits; stored in the access log |
| `--compare A B` | Side-by-side table from two runs' existing results on `--split` |
| `--data-report` | Dataset figures for a split folder; no model involved |
| `--examples N` | Examples per panel in the grid (default 8) |
| `--data-root`, `--split-dir` | Overrides |

## Behaviour

### Predictor interface

```python
class Predictor(Protocol):
    labels: tuple[str, ...]
    def predict_proba(self, rows: list[SlotRow], data_root: Path, tier_mode: str = "assigned") -> np.ndarray   # (N, 6 or 7)

def load_predictor(run_dir: Path) -> Predictor      # dispatches on run.json "model_type"
```

Evaluation knows nothing else about a model. A new model type only has to provide this.

### Checks before scoring

- The run's `split_id` matches the split folder, and the folder's current file hashes are compared with those stored in `run.json`; a difference (data added since training) is printed and recorded, not an error.
- The run's labels equal either `GAMES` or `CLASSES`.
- For `test_session` / `test_source`: the split folder must contain `freeze.json` (gate G1) and `--reason` must be given. One line `{utc, run, split, reason, git_commit}` is appended to `data/runs/holdout_access.jsonl`.
- `val` chooses the open-set threshold. Every other split refuses until `<run>/eval/val/open_set.json` exists.

### Metrics (`metrics.json`)

| Key | Content |
|---|---|
| `n`, `accuracy`, `macro_f1` | Headline, on the assigned-tier rows |
| `per_class` | Precision, recall, F1, support for each game |
| `confusion` | 6×6 counts, rows = true, columns = predicted, in label order |
| `lookalike` | Overwatch 2 ↔ Marvel Rivals: each direction's confusion rate and the pair's mean F1 |
| `by_tier` | Accuracy and macro-F1 for the rows assigned `full` and for those assigned `crf45` |
| `by_encoder` | Accuracy and n for `crf45` rows per encoder (`h264_d3d12va`, `libx264`), joined from `clips_index.low_encoder`; also by encoder within each game where both occur. A large gap is the signal to revisit D28 |
| `by_source` | Accuracy and n per source (and `source_kind`) |
| `by_clip` | Accuracy and n per `clip_key`, worst first (per-video error breakdown) |
| `six_game` | Accuracy and macro-F1 on six-game rows; a seven-way prediction of Other is wrong |
| `open_set` | `s = 1 - max p(game)`; val threshold at at most 5% six-game false alarms; false-alarm rate, Other detection, AUROC, coverage and covered accuracy |
| `provenance` | Run id, model type, split id, split hash, hash-changed flag, time |

A class with no rows in the split gets `null` scores and is left out of macro-F1; this is stated in the file. A class with rows that the model never predicts gets precision 0 and F1 0 and stays in macro-F1. `provenance.split_hash` is the hash of the split file actually scored (comparisons pair runs on it); `train_time_split_hash` is the one stored in `run.json`.

### Tier diagnostic (`tier_diagnostic.json`)

With `--tier-diagnostic`, every row that has both tiers is predicted twice, at `path_full` and at `path_low` (quick-mode rows, with an empty `path_low`, are left out and counted): accuracy and macro-F1 at each tier, the difference, and the share of rows whose prediction changes between tiers. This is the "accuracy at each quality level" result from the proposal, on paired frames (D04).

### Files written to `<run>/eval/<split>/`

| File | Content |
|---|---|
| `predictions.csv` | Identity, prediction, confidence, `open_score`, one probability column per run label, tier/source/clip/session |
| `metrics.json` | Above |
| `open_set.json` | The `open_set` block, including the val-selected `tau` |
| `confusion.png` | Row-normalised matrix with counts in the cells |
| `examples.png` | Two panels: highest-confidence correct and highest-confidence wrong, each tile captioned true → predicted and confidence; wrong panel favours the look-alike pair when present |
| `tier_diagnostic.json` | Only with `--tier-diagnostic` |

Example grids use only rows with `public_examples_ok = true`, so a contributor who did not consent to public examples never appears in a figure.

### Comparison (`--compare`)

Reads both runs' metrics and predictions for the same split id/hash. In addition to the side-by-side `.md` and `.csv`, it writes `<split>.json` with 95% paired bootstrap intervals for `six_game` macro-F1, Other detection rate and AUROC differences. It resamples whole `clip_key` values 1,000 times with replacement, seed 360.

### Data report (`--data-report`)

Writes to `<split_dir>/report/`: `class_counts.png` (slots per game, stacked by split, from `counts.csv`) and `example_frames.png` (a few `full` frames per game from `train`, consent-filtered). Together with `counts.csv` and `sources.csv` these cover the data section of a report.

## Decisions (D38)

| | |
|---|---|
| One module for both models | Same rows, same metric code, same figures |
| Headline metric | Macro-F1 beside accuracy; classes will not be perfectly balanced (D34) |
| Tier results | `by_tier` on the half-and-half set is always present; the paired diagnostic is opt-in because it doubles inference |
| Test access | Frozen split, stated reason, logged (D13, G1) |
| Open set | Same score and 5% val false-alarm operating point for six-way and seven-way runs (D24) |

## Working defaults

| | Default | Alternative |
|---|---|---|
| Example choice | Highest-confidence correct and wrong | Random sample; one row per game |
| Figures | matplotlib PNG, 200 dpi | PDF for LaTeX |

## Testing

| Kind | Cases |
|---|---|
| **Unit: metrics** | Existing classification/group cases plus six-game errors, known 5% threshold, Other detection, AUROC and coverage |
| **Unit: guards** | Existing held-out guards plus non-val scoring before val threshold refused |
| **System** | Existing files/figures plus six/seven output and reproducible paired video bootstrap comparison |

**How to run:** `pytest tests/unit/test_evaluation.py tests/system/test_evaluation.py` (skips without NumPy / matplotlib)

## Acceptance checks

- [x] Baseline and CNN evaluated by the same command with identical output layout
- [x] Confusion matrix and example grid generated for `val`
- [x] Test splits unreachable before freeze, and every access logged
- [x] Comparison table produced from two runs
- [x] CLI entry `gfc-evaluate` in `pyproject.toml`

## Ties to proposal and decisions

Evaluation paragraph: per-game accuracy and F1, confusion matrix, accuracy at each quality level, per-video breakdowns. D04, D13, D14, D17, D24, D38.
