# CNN trainer (`gfc-train-cnn`)

**Stage:** 5 — Primary model  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md)

## What it does (high level)

Defines the from-scratch CNN that maps one 256×144 RGB frame to either six games or six games plus Other, trains it on `train`, selects the best epoch on `val`, and saves a reproducible checkpoint.

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
    def __init__(self, channels=(32, 64, 128, 256), fc_dim=256, dropout=0.5, head="flatten", num_classes=7): ...
    def forward(self, x):            # x: [B, 3, 144, 256] → logits [B, num_classes]
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
| FC 256→7 | 7 | 1,799 |
| **Total (seven-way)** | | **9,828,135** |

96 % of the parameters sit in the first fully connected layer; the convolutional stack is 388,896. Softmax is applied only for reporting; training uses logits.

`head="gap"` replaces flatten and the first FC with global average pooling → dropout → FC 256→7, for 390,695 parameters. Six-way counts remain 9,827,878 and 390,438.

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
| Device | `auto`: `cuda`, then `mps`, then CPU. PyTorch's ROCm builds for AMD GPUs report through the `cuda` device, so no AMD-specific code is needed. Primary: the RX 9070 XT from `.venv-rocm`; fallback: CPU (D23) |
| Seed | Python, NumPy and PyTorch seeded from `seed` before the model is built |

Per epoch: train loss and accuracy (running, in train mode), then val loss, accuracy and macro-F1 in eval mode. One line is printed and appended to `history.csv`.

Training never opens a test split. `label_set` is `"seven"` (default) or `"six"`; six drops Other rows, while seven outputs seven logits and refuses to run without Other in train. The threshold remains an evaluation concern.

### Training time

Measured with the default model on an 8-thread CPU (PyTorch CPU build): 1.0 s per training batch of 64 (0.93 s with `head="gap"`, since nearly all compute is in the convolutions), 0.39 s per evaluation batch, and 0.11–0.15 s per batch for augmentation in the main process. One forward and backward pass is about 3.3 GFLOP per frame.

| Train frames | Batches per epoch | CPU epoch (incl. val) | 30 epochs on CPU | GPU epoch, `num_workers` 0 | GPU epoch, `num_workers` 2 |
|---:|---:|---:|---:|---:|---:|
| 2,000 (smoke) | 32 | ~40 s | ~20 min | ~9 s | ~7 s ¹ |
| 10,000 (proposal scale) | 157 | ~3.2 min | ~1.6 h | ~45 s | ~17 s |
| 30,000 | 469 | ~9.5 min | ~4.7 h | ~2.3 min | ~42 s |

Val is taken as about a fifth of train. Early stopping may end a run before 30 epochs (not yet measured).

¹ Best case: synthetic augmentation cost and a val loader with 0 workers. On 2,065 real frames 0 workers was faster (6.4 s against 9.6 s, [Reference measurement](#reference-measurement-2065-frames)), so the break-even lies somewhere between about 2,000 and 5,000 train frames.

This table and the [Full-run estimate](#full-run-estimate) below use different inputs: this one the synthetic per-batch timings, that one the per-frame cost measured on real frames. They differ by up to about 30 %; use the full-run estimate for planning.

**GPU column, measured** on a Radeon RX 9070 XT (ROCm 10.1.0 build of PyTorch 2.14, Windows), same method as the CPU column: batches × step time + val batches × eval time, plus augmentation. Per batch of 64 (median of 3 timings, warm-up and `torch.cuda.synchronize()` around each):

| | CPU baseline (above) | CPU, same environment as the GPU | GPU |
|---|---:|---:|---:|
| Train step, flatten head | 1.0 s | 1.28 s | **0.078 s** |
| Train step, GAP head | 0.93 s | 1.07 s | 0.076 s |
| Eval step, flatten head | 0.39 s | 0.59 s | **0.010 s** |
| Augmentation, main process | 0.11–0.15 s | 0.21 s | (same CPU work) 0.21 s |

- **`num_workers` 0:** each batch costs step + augmentation, 0.078 + 0.21 ≈ 0.29 s. Augmentation is about 73 % of it, so **augmentation is the bottleneck**, not the model. A real DataLoader loop measured 0.22–0.36 s per batch, depending on background load.
- **`num_workers` 2:** the worker processes augment in parallel with the GPU step. Measured end to end, 0.076 s per batch in steady state, which is the GPU step time, so the **model step is the bottleneck again**. Starting the workers costs about 4 s per epoch on Windows (included in the table, which assumes `num_workers` 2 with `cache: "none"`). 4 workers gave no gain (0.083 s per batch).
- **Speedup over the CPU baseline:** the model step is about 13× faster (1.0 s to 0.078 s), evaluation about 39×. A whole epoch is 4–5× faster at `num_workers` 0 and 6–14× faster at `num_workers` 2 (larger datasets gain more, because the worker start-up is a fixed cost). 30 epochs at 10,000 train frames take about 8 min on the GPU with 2 workers, against about 1.6 h on the CPU.
- **bf16 autocast** (information only, not used): train step 0.027 s against 0.078 s in float32. Not adopted, since it changes numerics and the float32 path is already fast enough.
- **Real frames:** the full-loop measurement on the project's own frames is in [Reference measurement](#reference-measurement-2065-frames) below: about 7× faster per epoch on the GPU.
- **Memory:** peak GPU memory is about 1.9 GB at batch 64 with the default model.
- Timings on this machine vary with background load (one CPU train-step timing came out at 1.8 s, one augmentation timing at 0.5 s); the table uses the median of 3 repeats. Expect ±30 % on the augmentation-bound figures. The CPU baseline is lower than the same-environment CPU column; background load is the likely reason, but the two were not measured side by side.

#### Reference measurement (2,065 frames)

The only measurement on the project's own frames so far, and the best estimate of training time until the real dataset exists. Repeat it when it does.

| | |
|---|---|
| **Data** | 2,065 JPGs, every frame in the repo's data folders on 2026-11-17: Valorant only, mixed sources (216 from `frames/`, 1,849 from `bench_extract/`). Source sizes: 1,520 at 640×360, 391 at 256×144, 135 at 960×540, 19 at 1920×1080; all resized to 256×144 |
| **Labels** | Arbitrary (six pseudo-classes from the folder name). No split. Timing only; the accuracy means nothing |
| **Loop** | Batch 64, 33 batches per epoch, augmentation on, eval pass over every fifth frame (413 frames), default model, Adam |
| **Machine** | 8-thread CPU and RX 9070 XT, same ROCm environment, background programs running |

| Setup | First epoch | Later epochs | Speedup vs CPU |
|---|---:|---:|---:|
| CPU, 0 workers, RAM cache | 45 s | 45–50 s | 1× |
| GPU, 0 workers, RAM cache | 29 s | **6.4 s** | **about 7×** |
| GPU, 2 workers, no cache (JPEG decode in workers) | 22 s | 9.6 s | about 5× |

- The first GPU epoch carries a one-time warm-up of about 20 s (kernel selection).
- At this size 2 workers are slower than 0: Windows starts the workers anew for each epoch (about 3–4 s), and the val loader paid that too (3.4 s of the 9.6 s, for 0.08 s of real work). Use workers for the train loader only, give the val loader 0 workers (no augmentation), or try `persistent_workers=True` (not measured). Workers should pay off from roughly 5,000 train frames upward.
- The 0-worker GPU epoch (6.4 s) is faster than the table's 9 s because augmentation on these frames cost about 0.12 s per batch, against 0.21 s on the synthetic benchmark.

#### Full-run estimate

`num_workers` is the number of background processes that load and augment batches. With **0**, the main process builds each batch (augmentation, about 0.12–0.2 s) and then the GPU trains on it, one after the other, so the GPU idles during augmentation. With **2**, two extra processes prepare the next batches while the GPU trains, so the GPU step (0.078 s) sets the pace; the price is about 3–4 s per epoch to start the workers on Windows. The CPU rows always use 0.

Epoch time is linear in frame count; per-frame cost taken from the reference measurement above: about 22 ms on the CPU and 3.1 ms on the GPU with 0 workers. The 2-worker column uses 0.078 s per batch plus the worker start-up.

| Train frames | CPU epoch | GPU epoch, 0 workers | GPU epoch, 2 workers |
|---:|---:|---:|---:|
| 2,065 (measured) | 45–50 s | 6.4 s | 9.6 s (start-up dominates) |
| 10,000 | ~3.7 min | ~31 s | ~17 s |
| 30,000 | ~11 min | ~93 s | ~42 s |

Epochs per full run are **not measured yet** (no labelled split has been trained). The config allows up to 30 and stops after 6 epochs without improvement in val macro-F1; for a small from-scratch CNN with Adam at lr 1e-3, assume val plateaus around epoch 10–25, so a run ends at roughly 15–30 epochs. That is a rule of thumb, to be replaced by the first real run. Totals below add about 20 s of one-time GPU warm-up:

| Train frames | Epochs | CPU | GPU, 2 workers | GPU, 0 workers |
|---:|---:|---:|---:|---:|
| 10,000 | 15 | ~55 min | ~4.5 min | ~8 min |
| 10,000 | 20 | ~1.2 h | ~6 min | ~11 min |
| 10,000 | 30 | ~1.9 h | ~9 min | ~16 min |
| 30,000 | 15 | ~2.8 h | ~11 min | ~23 min |
| 30,000 | 20 | ~3.7 h | ~14 min | ~31 min |
| 30,000 | 30 | ~5.5 h | ~21 min | ~47 min |

These are single runs; a sweep or the flatten-versus-GAP comparison multiplies them. The reference frames are mostly benchmark extractions from one game, so augmentation cost on the real dataset may differ. Repeat the measurement once the real split exists.

### Hardware

The code is the same on every device; only the installed PyTorch build changes.

| Option | Setup | Notes |
|---|---|---|
| AMD Radeon RX 9000 on Windows (primary) | Separate `.venv-rocm` with AMD's ROCm build of `torch` / `torchvision`; step by step in [AMD GPU setup](../../amd-gpu-setup.md) | Check with `torch.cuda.is_available()` and `torch.version.hip`. Tested working on an RX 9070 XT (overfit test, an 11-minute training run and the timings above, with no crash and no workaround). About 7× faster per epoch than the CPU |
| CPU (fallback) | `pip install -e ".[dev,train]"` in the normal environment, or `--device cpu` | Use when the GPU environment is broken or busy. Still enough for the progress report: one run in an evening |
| AMD Radeon on Linux or WSL2 | ROCm build of PyTorch | Most mature AMD path |
| Colab GPU | Upload `data/frames/` and the split folder as a zip | Same command; mind session limits |

Before trusting a GPU environment, run the system overfit test and one smoke run (`--epochs 2 --limit 256`) on it and compare the loss curve with the CPU run. Results are not bit-identical across devices.

The RX 9070 XT environment was checked with a standalone script that builds the model from the layer table above (9,827,878 and 390,438 parameters, asserted) before the trainer landed: the overfit setup (3 classes × 8 synthetic frames, 30 epochs, no augmentation, seed 360) reached train accuracy 1.0 on both GPU and CPU. With identical weights, eval-mode logits differ between devices by 1.6e-7 and per-layer gradients by at most 0.3 % relative; the epoch-by-epoch loss curves of the tiny overfit run differ in the first epochs (one optimiser step per epoch amplifies the float differences) and both reach a loss near 0 by epoch 4–6. The trainer's own smoke run (`--epochs 2 --limit 256`, no augmentation, seed 360, synthetic six-class frames) on 2026-11-18 reported `device: cuda` under `.venv-rocm` (ROCm 10.1.0 / PyTorch 2.14); epoch 1 took about 20 s (warm-up) and epoch 2 about 0.5 s, against about 7.5 s then 5.0 s on CPU for the same command. Train loss fell on both devices (CPU 5.46 → 3.55; GPU 5.93 → 3.38); curves are close, not bit-identical.

## Config (`config/train_cnn.json`)

```json
{
  "schema": "gfc.train_cnn/1",
  "label_set": "seven",
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

`num_workers` applies to the train loader only; the val loader always uses 0 workers, since it has no augmentation and would otherwise pay the worker start-up every epoch. The default stays 0 (D35); 2 is the measured choice on the GPU from roughly 5,000 train frames upward (see Training time).

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
| D23 (decided) | Local RX 9070 XT (ROCm build of PyTorch, `.venv-rocm`) | Local CPU (fallback); Colab GPU (see Hardware) | GPU environment breaks after a driver or ROCm update, or GPU and CPU smoke runs disagree |
| — | Logging to `history.csv` + `curves.png` | TensorBoard | Never needed for the reports |

## Testing

| Kind | Cases |
|---|---|
| **Unit: model** | Random `[2, 3, 144, 256]` → seven logits; default counts are 9,828,135 flatten and 390,695 GAP; explicit six-way counts remain unchanged |
| **Unit: config** | `--set model.head=gap` changes the resolved config; unknown keys are rejected |
| **System** | Existing six-way overfit and reproducibility cases; synthetic Other runs in six and seven; seven records seven labels and 9,828,135 parameters; seven without Other refuses |
| **Manual / report** | Real curves, val metrics, example grid |

**How to run:** `pytest tests/unit/test_model.py tests/system/test_train.py` (skips without PyTorch)

## Acceptance checks (progress report)

- [ ] Train and val curves plotted
- [ ] Val accuracy and macro-F1 reported, next to the baseline's
- [ ] Qualitative: correct and failure examples, look-alike pair included
- [ ] Parameter count and layer table in the report
- [ ] Challenges noted
- [x] CLI entry `gfc-train-cnn` in `pyproject.toml`

## Acceptance checks (final report extras)

- [ ] `test_source` and `test_session` results, after the split is frozen
- [ ] Per-tier diagnostic (full vs CRF 45)
- [ ] Confusion matrix with emphasis on Overwatch 2 vs Marvel Rivals
- [ ] Flatten vs GAP comparison
- [ ] Unknown threshold tuned on val

## Ties to proposal and decisions

Architecture and Evaluation sections. D15, D16, D16b, D23, D24, D34, D37.
