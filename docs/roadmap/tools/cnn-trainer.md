# CNN trainer (`gfc-train-cnn`)

**Stage:** 5 — Primary model  
**Status:** planned  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md)

## What it does (high level)

Defines the from-scratch CNN that maps one 256×144 RGB frame to one of six games, trains it on the `train` split, selects the best epoch on `val`, and saves a checkpoint with everything needed to reproduce or evaluate it.

## Why we need it

This is the primary model. The progress report needs the architecture in more detail than the proposal, a parameter count, training curves and at least one quantitative and one qualitative result.

## Connections

| | |
|---|---|
| **Reads** | `train` and `val` manifests from [`gfc-split`](dataset-splitter.md) through the [loader](dataset-loader.md); `config/train_cnn.json` |
| **Writes** | `data/runs/cnn/<run_id>/` |
| **Then** | [`gfc-evaluate`](evaluation.md) on `val` runs automatically at the end of training |

## Usage

```text
gfc-train-cnn --split-dir data/manifests/splits/v1
gfc-train-cnn --split-dir data/manifests/splits/v1 --tag gap --set model.head=gap
gfc-train-cnn --split-dir data/manifests/splits/v1 --epochs 2 --limit 256      # smoke run
python -m game_frame_classifier.train --split-dir ...
```

| Flag | Meaning |
|---|---|
| `--split-dir` | Split folder (required) |
| `--data-root` | Data root (default `data`) |
| `--config` | Settings (default `config/train_cnn.json`) |
| `--set key=value` | Override one config value (repeatable, dotted keys) |
| `--epochs`, `--device` | Shortcuts for the matching config keys |
| `--limit N` | Use only the first N rows of train and val (smoke runs) |
| `--tag`, `--out` | Run id suffix; run folder (default `data/runs/cnn/<run_id>`) |

## Architecture (`model.py`)

```python
class FrameCNN(nn.Module):
    def __init__(self, channels=(32, 64, 128, 256), fc_dim=256, dropout=0.5, head="flatten", num_classes=6): ...
    def forward(self, x):            # x: [B, 3, 144, 256] → logits [B, 6]
```

Each block: 3×3 convolution (padding 1, no bias) → batch normalisation → ReLU → 2×2 max pool.

| Layer | Output (C×H×W) | Parameters |
|---|---|---:|
| Input | 3×144×256 | — |
| Block 1: conv 3→32, BN | 32×72×128 | 928 |
| Block 2: conv 32→64, BN | 64×36×64 | 18,560 |
| Block 3: conv 64→128, BN | 128×18×32 | 73,984 |
| Block 4: conv 128→256, BN | 256×9×16 | 295,424 |
| Flatten | 36,864 | — |
| FC 36,864→256, ReLU, dropout 0.5 | 256 | 9,437,440 |
| FC 256→6 | 6 | 1,542 |
| **Total** | | **9,827,878** |

96 % of the parameters sit in the first fully connected layer; the convolutional stack is 388,896. Softmax is applied only for reporting; training uses logits.

`head="gap"` replaces flatten and the first FC with global average pooling → dropout → FC 256→6, for 390,438 parameters. This is the flatten versus global-average-pooling comparison planned in the proposal (D16b); flatten is primary because it keeps where on screen a feature fired.

Weights use PyTorch's default initialisation. No pretrained weights.

## Training (`train.py`)

| | |
|---|---|
| Loss | Cross-entropy on logits, class weights from the train split (`split_manifest.class_weights`) |
| Optimiser | Adam, lr 1e-3, weight decay 1e-4 |
| Batch size | 64 |
| Epochs | Up to 30 |
| Selection | Best `val` macro-F1; that epoch's weights are saved as `best.pt` |
| Early stop | No improvement in `val` macro-F1 for 6 epochs |
| Data | `FrameDataset(train, transform=train_transform)`, shuffled; `FrameDataset(val, transform=eval_transform)` |
| Device | `auto`: CUDA, then MPS, then CPU |
| Seed | Python, NumPy and PyTorch seeded from `seed` before the model is built |

Per epoch: train loss and accuracy (running, in train mode), then val loss, accuracy and macro-F1 in eval mode. One line is printed and appended to `history.csv`.

Training never opens a test split. The unknown threshold (D24) is not part of training; the model is always six-way.

Measured on an 8-thread CPU: about 1 s per batch of 64, so about 3 min per epoch at 10,000 train frames. A full run fits in an evening without a GPU.

## Config (`config/train_cnn.json`)

```json
{
  "schema": "gfc.train_cnn/1",
  "seed": 360,
  "model": { "channels": [32, 64, 128, 256], "fc_dim": 256, "dropout": 0.5, "head": "flatten" },
  "optim": { "name": "adam", "lr": 0.001, "weight_decay": 0.0001 },
  "batch_size": 64,
  "epochs": 30,
  "early_stop_patience": 6,
  "class_weights": "balanced",
  "device": "auto",
  "cache": "ram",
  "num_workers": 0,
  "augment": {
    "affine_p": 0.5, "scale": [0.85, 1.15], "translate": [0.02, 0.02],
    "jitter_p": 0.8, "brightness": 0.2, "contrast": 0.2, "saturation": 0.2, "hue": 0.02
  }
}
```

## Run folder

```text
data/runs/cnn/<run_id>/
  run.json        # model_type "cnn", resolved config, labels, normalisation, param_count, split_dir, split_id,
                  # split hashes, git commit, torch version, device, best epoch, wall time
  history.csv     # epoch, train_loss, train_acc, val_loss, val_acc, val_macro_f1, lr, seconds
  curves.png      # loss and accuracy, train vs val, best epoch marked
  best.pt         # {"model_state", "config", "labels", "normalisation", "epoch", "val_metrics"}
  last.pt         # same, last epoch
  eval/val/...    # written by evaluation
```

Checkpoints are loaded with `weights_only=True` plus the config stored beside them. `CnnPredictor` (in `train.py`) rebuilds `FrameCNN` from `run.json`, loads `best.pt` and exposes the same `predict_proba(rows, data_root, tier_mode)` as the baseline.

## Working defaults

| ID | Default | Alternative | Signal to revisit |
|---|---|---|---|
| D16 | 32-64-128-256, one FC of 256 | FC 128 (5,108,390 params) or 512 (19,266,854); a second FC layer | Large train/val gap → smaller FC or GAP; underfit → larger |
| D16b | Flatten primary | GAP via `model.head=gap` | Run both once for the comparison |
| D15 | Single stream | Second stream on HUD crops cut from native stills, fused before the classifier | Look-alike pair still confused after tuning |
| D37 | lr 1e-3, weight decay 1e-4, batch 64, 30 epochs, patience 6 | Cosine or plateau LR schedule; batch 32 / 128; no weight decay | Noisy or plateaued val curve |
| D34 | Class-weighted loss | Unweighted loss on a downsampled balanced set | Per-class recall is uneven |
| D23 | Local CPU | Colab GPU: zip `data/frames/` and the split folder, same command | An epoch takes more than about 10 min |
| — | Logging to `history.csv` + `curves.png` | TensorBoard | Never needed for the reports |

## Testing

| Kind | Cases |
|---|---|
| **Unit: model** | Random `[2, 3, 144, 256]` → logits `[2, 6]`; parameter count is 9,827,878 for the default and 390,438 for `head="gap"`; eval mode is deterministic; other channel tuples build |
| **Unit: config** | `--set model.head=gap` changes the resolved config; unknown keys are rejected |
| **System** | Overfit: 3 classes × 8 synthetic frames, 30 epochs, no augmentation → train accuracy ≥ 0.95; run folder holds every file listed; `history.csv` has one row per epoch; `CnnPredictor` on the run reproduces the saved val predictions; same seed gives the same first-epoch loss on CPU |
| **Manual / report** | Real curves, val metrics, example grid |

**How to run:** `pytest tests/unit/test_model.py tests/system/test_train.py` (skips without PyTorch)

## Acceptance checks (progress report)

- [ ] Train and val curves plotted
- [ ] Val accuracy and macro-F1 reported, next to the baseline's
- [ ] Qualitative: correct and failure examples, look-alike pair included
- [ ] Parameter count and layer table in the report
- [ ] Challenges noted
- [ ] CLI entry `gfc-train-cnn` in `pyproject.toml`

## Acceptance checks (final report extras)

- [ ] `test_source` and `test_session` results, after the split is frozen
- [ ] Per-tier diagnostic (full vs CRF 45)
- [ ] Confusion matrix with emphasis on Overwatch 2 vs Marvel Rivals
- [ ] Flatten vs GAP comparison
- [ ] Unknown threshold tuned on val

## Ties to proposal and decisions

Architecture and Evaluation sections. D15, D16, D16b, D23, D24, D34, D37.
