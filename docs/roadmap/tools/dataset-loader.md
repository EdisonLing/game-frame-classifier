# Dataset loader and augmentation

**Stage:** 2 — Dataset assembly  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [training pipeline](../../training-pipeline.md)

## What it does (high level)

Library code, no command. Reads a split manifest, loads the 256×144 frame each row points at, and hands it to the baseline as a NumPy array or to the CNN as a normalised tensor. Training-only augmentation lives here too, so there is exactly one place where pixels are read and changed.

## Why we need it

The baseline and the CNN must see the same frames in the same tier, or the comparison between them means nothing. Putting row parsing, tier choice and decoding in one module guarantees that. Augmentation buys robustness to scale and colour differences without extra footage, and must never touch validation or test data (D03).

## Connections

| | |
|---|---|
| **Reads** | `data/manifests/splits/<split_id>/<split>.csv` from [`gfc-split`](dataset-splitter.md); images under `data/frames/` from [`gfc-derive-frames`](derive-frames.md) |
| **Used by** | [baseline](baseline.md) (`split_manifest` only), [CNN trainer](cnn-trainer.md) (`dataset`), [evaluation](evaluation.md) (both) |
| **Writes** | Nothing |

## Modules

### `split_manifest.py` (NumPy + Pillow, no PyTorch)

```python
LABELS: tuple[str, ...]                     # sourcing.labels.GAMES, index = class id

@dataclass(frozen=True)
class SlotRow:
    slot_id: str; clip_key: str; game: str; label: int
    source: str; source_kind: str; session: str
    split: str; tier: str
    path: str; path_full: str; path_low: str
    bucket: int; target_time_s: float
    public_examples_ok: bool

def load_split(split_dir: Path, name: str, *, allow_test: bool = False) -> list[SlotRow]
def split_hashes(split_dir: Path) -> dict[str, str]          # sha256 per split file, from summary.json
def image_path(row: SlotRow, data_root: Path, tier_mode: str = "assigned") -> Path
def load_image_u8(path: Path) -> np.ndarray                   # uint8, shape (144, 256, 3), RGB
def class_weights(rows: list[SlotRow]) -> np.ndarray          # n / (k * count_c), from the rows given
```

- `load_split` accepts `train` and `val` freely. For `test_session` and `test_source` it requires `allow_test=True`, which only [evaluation](evaluation.md) passes (D13).
- `tier_mode`: `assigned` (the row's `tier`, the default everywhere), `full` or `low` (the per-tier diagnostic). `low` raises for a row with an empty `path_low` (quick-mode clip); callers filter those rows first.
- `load_image_u8` opens with Pillow, converts to RGB and raises if the size is not 256×144. It never resizes (D27).
- `label` in the file must equal `LABELS.index(game)`; a mismatch raises.

### `dataset.py` (PyTorch)

```python
class FrameDataset(torch.utils.data.Dataset):
    def __init__(self, rows, data_root, *, tier_mode="assigned", transform=None, cache="ram"): ...
    def __getitem__(self, i) -> tuple[Tensor, int, int]      # image [3,144,256] float32, label, row index

def train_transform(cfg: AugmentConfig) -> Callable
def eval_transform() -> Callable
def make_loader(dataset, *, batch_size, shuffle, seed, num_workers=0) -> DataLoader
```

- The returned row index lets evaluation join predictions back to `SlotRow`s.
- `cache="ram"` keeps each decoded frame as a `uint8` tensor after its first read (about 110 KB per frame, about 1.7 GB for 15,000 frames). `cache="none"` decodes every time.
- `make_loader` uses a `torch.Generator` seeded from `seed` so shuffling is repeatable. `drop_last` is false.

## Transforms

Applied in this order to a `uint8` tensor `[3, 144, 256]`:

| Step | Train | Val / test |
|---|---|---|
| 1. Geometric | With probability 0.5: `RandomAffine(degrees=0, scale=(0.85, 1.15), translate=(0.02, 0.02), fill=0)`; output stays 144×256 | — |
| 2. Colour | With probability 0.8: `ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.02)` | — |
| 3. To float | divide by 255 | divide by 255 |
| 4. Normalise | `(x − 0.5) / 0.5` per channel | same |

Never: horizontal or vertical flips, rotation, crops that change the output size. A flip mirrors the HUD, which is the main cue.

Quality tier is **not** an augmentation. It is fixed per slot by the splitter (D04) and arrives in the `tier` column; the loader only follows `path`.

`AugmentConfig` holds the probabilities and ranges above and is read from the `augment` block of `config/train_cnn.json`. The normalisation constants are stored in every checkpoint.

## Working defaults (D35)

| | Default | Alternative |
|---|---|---|
| When | Online, a fresh random draw each epoch | Offline augmented copies on disk |
| Zoom | 0.85–1.15 (the proposal's 10–20 % range, both directions) | Zoom-out only, 0.85–1.0, which never crops HUD edges |
| Colour | Mild jitter as above | Stronger jitter; per-game gamma shifts |
| Normalisation | Fixed 0.5 / 0.5 | Train-set mean and standard deviation |
| Cache | RAM | None; or a single `.npy` memmap |
| Workers | 0: decode is cached, and on CPU the model step (about 1 s per batch) dwarfs augmentation (about 0.1–0.15 s per batch of 64, measured) | On a GPU the step drops below the augmentation time, so the main process becomes the bottleneck. Then use 2–4 workers with `cache="none"` (each Windows worker would hold its own RAM cache), or a shared `.npy` memmap cache |

## Testing

| Kind | Cases |
|---|---|
| **Unit: manifest** | `load_split` parses a fixture; test splits refused without `allow_test`; label/game mismatch raises; `image_path` follows `tier`, and `full` / `low` override it; `class_weights` values on a known count |
| **Unit: decode** | 256×144 JPEG → `(144, 256, 3)` uint8; other sizes raise; greyscale file comes back as three channels |
| **Unit: transforms** | Eval transform is deterministic and equals `(x/255 − 0.5)/0.5`; train transform keeps shape and dtype; no flip class anywhere in the pipeline; with all probabilities 0 the train transform equals the eval transform; an asymmetric test image is never mirrored over 200 draws |
| **System** | Synthetic split dir + frames → one batch from `make_loader` has shape `[B, 3, 144, 256]`, dtype float32, values in `[-1, 1]`, labels in `0..5`; same seed gives the same batch order; `cache="ram"` and `cache="none"` return identical eval tensors |
| **Manual** | Save a grid of augmented train samples next to their originals; HUD orientation unchanged; at the largest zoom (1.15) about 7 % of each edge is cropped, so check that corner HUD elements are still mostly visible |

**How to run:** `pytest tests/unit/test_split_manifest.py tests/unit/test_dataset.py tests/system/test_dataset.py` (PyTorch tests skip when it is not installed)

## Acceptance checks

- [x] Baseline and CNN load frames through `split_manifest` only
- [x] Val and test pipelines contain no random step
- [x] No resize anywhere in the loader
- [x] Test splits cannot be opened by training code

## Ties to proposal and decisions

Data Processing, augmentation paragraph (random re-encoding replaced by fixed tiers, D04). D03, D13, D27, D35.
