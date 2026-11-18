# Colour-histogram baseline (`gfc-train-baseline`)

**Stage:** 4 — Baseline model  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md)

## What it does (high level)

Reduces each frame to a 48-number colour histogram and fits a multinomial logistic regression to predict the game. It uses the same frames, splits and tiers as the CNN.

## Why we need it

A colour histogram throws away all spatial layout, so this model can only use palette and art style. It sets the bar the CNN has to clear and shows what layout adds, most of all on the look-alike pair Overwatch 2 and Marvel Rivals. The progress report needs a non-deep baseline with one quantitative and one qualitative result.

## Connections

| | |
|---|---|
| **Reads** | `train` and `val` manifests from [`gfc-split`](dataset-splitter.md) through [`split_manifest`](dataset-loader.md); `config/baseline.json` |
| **Writes** | `data/runs/baseline/<run_id>/` |
| **Then** | [`gfc-evaluate`](evaluation.md) on `val` runs automatically at the end of training |

## Usage

```text
gfc-train-baseline --split-dir data/manifests/splits/v1
gfc-train-baseline --split-dir data/manifests/splits/v1 --tag bins32 --config config/baseline.json
python -m game_frame_classifier.baseline --split-dir ...
```

| Flag | Meaning |
|---|---|
| `--split-dir` | Split folder (required) |
| `--data-root` | Data root (default `data`) |
| `--config` | Settings (default `config/baseline.json`) |
| `--tag` | Suffix for the run id |
| `--out` | Run folder (default `data/runs/baseline/<run_id>`) |

## Config (`config/baseline.json`)

```json
{
  "schema": "gfc.baseline/1",
  "seed": 360,
  "bins": 16,
  "c_grid": [0.01, 0.1, 1.0, 10.0],
  "max_iter": 2000,
  "class_weight": "balanced"
}
```

## Method

### Features

```python
def histogram_features(image_u8: np.ndarray, bins: int = 16) -> np.ndarray   # shape (3 * bins,), float32
```

For each of R, G, B: count pixels in `bins` equal-width bins over 0–255 (width 16 for 16 bins), divide by the pixel count so each channel sums to 1, then concatenate R, G, B. The input is the 256×144 frame exactly as the CNN receives it before normalisation; no resize, no colour-space change.

Features for a split are computed once and cached in the run folder as `features_<split>.npy`.

### Model

`sklearn.pipeline.Pipeline([StandardScaler(), LogisticRegression(C=c, max_iter=..., class_weight="balanced", random_state=seed)])` with the default lbfgs solver (multinomial).

One model is fitted on `train` for each value in `c_grid`. The one with the best macro-F1 on `val` is kept; ties go to the smaller `C`. No test split is read. Because `val` both picks `C` and reports the score, the val number is slightly optimistic; the CNN's best-epoch selection has the same bias, so the comparison stays fair.

### Prediction interface

```python
class BaselinePredictor:
    labels: tuple[str, ...]
    def predict_proba(self, rows: list[SlotRow], data_root: Path, tier_mode: str = "assigned") -> np.ndarray   # (N, 6)
```

This is the interface [evaluation](evaluation.md) calls for every model type.

## Run folder

```text
data/runs/baseline/<run_id>/
  run.json              # model_type "baseline", config, labels, seed, split_dir, split_id, split hashes, git commit, versions, chosen C
  model.joblib          # fitted pipeline
  c_search.csv          # C, val accuracy, val macro-F1
  features_train.npy  features_val.npy
  eval/val/...          # written by evaluation
```

## Decisions

| | |
|---|---|
| Frames | Same 256×144 files and tier assignment as the CNN, so the only difference between the two models is the model |
| Stack | scikit-learn |
| Imbalance | `class_weight="balanced"` (D34) |
| Unknown | The baseline is six-way only; no threshold |

## Working defaults (D36)

| | Default | Alternative |
|---|---|---|
| Bins | 16 per channel (proposal) | 32; joint 3-D histogram; HSV |
| Scaling | `StandardScaler` | None |
| `C` | Picked on val from four values | Fixed 1.0 |

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Feature length is `3 * bins`; each channel block sums to 1; a solid-colour image puts all mass in the expected bin of each channel; value 255 falls in the last bin; `predict_proba` shape `(N, 6)` with rows summing to 1 |
| **System** | Synthetic split of three solid-ish colours standing in for three games → train → val accuracy far above chance; run folder holds every file listed; rerun with the same seed gives identical `c_search.csv` |
| **Manual / report** | Real val metrics, confusion matrix and example grid from evaluation |

**How to run:** `pytest tests/unit/test_baseline.py tests/system/test_baseline.py` (skips without scikit-learn)

## Acceptance checks

- [x] Beats chance on val: accuracy above the largest class's share of val, and macro-F1 above 1/6 (synthetic three-colour split in system tests; real-data check left for the reviewer)
- [ ] Confusion matrix saved; look-alike pair visible (needs `gfc-evaluate` on a real run; left for the reviewer)
- [ ] One quantitative metric and one qualitative example for the progress report (needs a real val run + evaluation figures; left for the reviewer)
- [x] Reads frames only through `split_manifest`
- [x] CLI entry `gfc-train-baseline` in `pyproject.toml`

## Ties to proposal and decisions

Baseline Model section; Evaluation: "the CNN should clearly outperform the colour-histogram baseline". D05, D34, D36.
