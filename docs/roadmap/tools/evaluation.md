# Evaluation and report figures (`gfc-evaluate`)

**Stage:** 4–5 — shared by the baseline and the CNN  
**Status:** planned  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md)

## What it does (high level)

Scores any trained run on a split and writes the numbers and figures the reports need: accuracy, per-game precision, recall and F1, a confusion matrix, breakdowns by tier, source and clip, and a grid of example predictions. It also draws the data figures (class counts, example frames) and builds the baseline-versus-CNN table.

## Why we need it

Both models must be measured by the same code on the same rows, or their comparison is not trustworthy. It is also the only door to the held-out test splits, so access to them is controlled and logged in one place (D13).

## Connections

| | |
|---|---|
| **Reads** | A run folder from [`gfc-train-baseline`](baseline.md) or [`gfc-train-cnn`](cnn-trainer.md); split manifests from [`gfc-split`](dataset-splitter.md) through the [loader](dataset-loader.md) |
| **Writes** | `<run>/eval/<split>/`, `data/runs/holdout_access.jsonl`, comparison and data-report folders |
| **Called by** | Both trainers at the end of training (`split = val`), and by hand |

## Usage

```text
gfc-evaluate --run data/runs/cnn/<run_id> --split val
gfc-evaluate --run data/runs/cnn/<run_id> --split val --tier-diagnostic
gfc-evaluate --run data/runs/cnn/<run_id> --split test_source --reason "final report"
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
    def predict_proba(self, rows: list[SlotRow], data_root: Path, tier_mode: str = "assigned") -> np.ndarray   # (N, 6)

def load_predictor(run_dir: Path) -> Predictor      # dispatches on run.json "model_type"
```

Evaluation knows nothing else about a model. A new model type only has to provide this.

### Checks before scoring

- The run's `split_id` matches the split folder, and the folder's current file hashes are compared with those stored in `run.json`; a difference (data added since training) is printed and recorded, not an error.
- The run's `labels` equal `split_manifest.LABELS`.
- For `test_session` / `test_source`: the split folder must contain `freeze.json` (gate G1) and `--reason` must be given. One line `{utc, run, split, reason, git_commit}` is appended to `data/runs/holdout_access.jsonl`.

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
| `provenance` | Run id, model type, split id, split hash, hash-changed flag, time |

A class with no rows in the split gets `null` scores and is left out of macro-F1; this is stated in the file.

### Tier diagnostic (`tier_diagnostic.json`)

With `--tier-diagnostic`, every row is predicted twice, at `path_full` and at `path_low`: accuracy and macro-F1 at each tier, the difference, and the share of rows whose prediction changes between tiers. This is the "accuracy at each quality level" result from the proposal, on paired frames (D04).

### Files written to `<run>/eval/<split>/`

| File | Content |
|---|---|
| `predictions.csv` | `slot_id, game, label, pred, pred_game, correct, confidence, p_<game>` ×6, `tier, source, clip_key, session` |
| `metrics.json` | Above |
| `confusion.png` | Row-normalised matrix with counts in the cells |
| `examples.png` | Two panels: highest-confidence correct and highest-confidence wrong, each tile captioned true → predicted and confidence; wrong panel favours the look-alike pair when present |
| `tier_diagnostic.json` | Only with `--tier-diagnostic` |

Example grids use only rows with `public_examples_ok = true`, so a contributor who did not consent to public examples never appears in a figure.

### Comparison (`--compare`)

Reads both runs' `metrics.json` for the split (they must share `split_id` and split hash) and writes `data/runs/compare/<runA>__<runB>/<split>.md` and `.csv`: accuracy, macro-F1, per-game F1 and the look-alike numbers side by side with the difference.

### Data report (`--data-report`)

Writes to `<split_dir>/report/`: `class_counts.png` (slots per game, stacked by split, from `counts.csv`) and `example_frames.png` (a few `full` frames per game from `train`, consent-filtered). Together with `counts.csv` and `sources.csv` these cover the data section of a report.

## Decisions (D38)

| | |
|---|---|
| One module for both models | Same rows, same metric code, same figures |
| Headline metric | Macro-F1 beside accuracy; classes will not be perfectly balanced (D34) |
| Tier results | `by_tier` on the half-and-half set is always present; the paired diagnostic is opt-in because it doubles inference |
| Test access | Frozen split, stated reason, logged (D13, G1) |
| Unknown | Added after first results: `--unknown-threshold` picked on val, reported as coverage and accuracy on covered rows (D24) |

## Working defaults

| | Default | Alternative |
|---|---|---|
| Example choice | Highest-confidence correct and wrong | Random sample; one row per game |
| Figures | matplotlib PNG, 200 dpi | PDF for LaTeX |

## Testing

| Kind | Cases |
|---|---|
| **Unit: metrics** | Hand-built 3-class predictions → exact accuracy, per-class P/R/F1, macro-F1 and confusion matrix; class with zero support handled; look-alike numbers from a known matrix; `by_tier`, `by_source`, `by_clip` group correctly |
| **Unit: guards** | Test split without `freeze.json` refused; without `--reason` refused; accepted case appends exactly one log line; label-order mismatch refused; examples exclude rows without consent |
| **System** | Fake predictor (always right / always one class) on a synthetic split → all files written, metrics as expected, PNGs non-empty; `--tier-diagnostic` with a predictor that depends on the path gives the expected flip rate; `--compare` on two fake runs writes the table; `--data-report` writes both figures |

**How to run:** `pytest tests/unit/test_evaluation.py tests/system/test_evaluation.py` (skips without NumPy / matplotlib)

## Acceptance checks

- [ ] Baseline and CNN evaluated by the same command with identical output layout
- [ ] Confusion matrix and example grid generated for `val`
- [ ] Test splits unreachable before freeze, and every access logged
- [ ] Comparison table produced from two runs
- [ ] CLI entry `gfc-evaluate` in `pyproject.toml`

## Ties to proposal and decisions

Evaluation paragraph: per-game accuracy and F1, confusion matrix, accuracy at each quality level, per-video breakdowns. D04, D13, D14, D17, D24, D38.
