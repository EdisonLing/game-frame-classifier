"""PyTorch FrameDataset, train/eval transforms and DataLoader factory.

Reads SlotRows through split_manifest, decodes 256×144 frames once (optional
RAM cache), and applies online augmentation for training only.
Spec: `docs/roadmap/tools/dataset-loader.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import torch
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms as T

from game_frame_classifier.split_manifest import SlotRow, image_path, load_image_u8

_MEAN = 0.5
_STD = 0.5


@dataclass
class AugmentConfig:
    """Online augmentation probabilities and ranges (config augment block)."""

    affine_p: float = 0.5
    scale: tuple[float, float] = (0.85, 1.15)
    translate: tuple[float, float] = (0.02, 0.02)
    jitter_p: float = 0.8
    brightness: float = 0.2
    contrast: float = 0.2
    saturation: float = 0.2
    hue: float = 0.02


def _to_float_normalised(x: torch.Tensor) -> torch.Tensor:
    x = x.float() / 255.0
    return (x - _MEAN) / _STD


def eval_transform() -> Callable[[torch.Tensor], torch.Tensor]:
    """Deterministic uint8 CHW → float32 in [-1, 1]."""

    return _to_float_normalised


def train_transform(cfg: AugmentConfig) -> Callable[[torch.Tensor], torch.Tensor]:
    """Train transform: optional affine and colour jitter, then same normalisation."""
    affine = T.RandomAffine(
        degrees=0,
        scale=tuple(cfg.scale),
        translate=tuple(cfg.translate),
        fill=0,
    )
    jitter = T.ColorJitter(
        brightness=cfg.brightness,
        contrast=cfg.contrast,
        saturation=cfg.saturation,
        hue=cfg.hue,
    )
    affine_p = float(cfg.affine_p)
    jitter_p = float(cfg.jitter_p)

    def _fn(x: torch.Tensor) -> torch.Tensor:
        if affine_p > 0 and torch.rand(()) < affine_p:
            x = affine(x)
        if jitter_p > 0 and torch.rand(()) < jitter_p:
            x = jitter(x)
        return _to_float_normalised(x)

    return _fn


class FrameDataset(Dataset):
    """Slot rows → (image CHW float32, label, row index)."""

    def __init__(
        self,
        rows: list[SlotRow],
        data_root: Path,
        *,
        tier_mode: str = "assigned",
        transform: Callable[[torch.Tensor], torch.Tensor] | None = None,
        cache: str = "ram",
    ) -> None:
        if cache not in ("ram", "none"):
            raise ValueError(f"unknown cache mode: {cache!r}")
        self.rows = list(rows)
        self.data_root = Path(data_root)
        self.tier_mode = tier_mode
        self.transform = transform
        self.cache = cache
        self._ram: dict[int, torch.Tensor] = {}

    def __len__(self) -> int:
        return len(self.rows)

    def _decode_u8(self, index: int) -> torch.Tensor:
        if self.cache == "ram" and index in self._ram:
            return self._ram[index]
        row = self.rows[index]
        path = image_path(row, self.data_root, self.tier_mode)
        arr = load_image_u8(path)
        tensor = torch.from_numpy(arr.copy()).permute(2, 0, 1).contiguous()
        if self.cache == "ram":
            self._ram[index] = tensor
        return tensor

    def __getitem__(self, i: int) -> tuple[torch.Tensor, int, int]:
        image = self._decode_u8(i)
        if self.transform is not None:
            image = self.transform(image)
        return image, self.rows[i].label, i


def make_loader(
    dataset: Dataset,
    *,
    batch_size: int,
    shuffle: bool,
    seed: int,
    num_workers: int = 0,
) -> DataLoader:
    """Build a DataLoader with a seeded generator for repeatable shuffle."""
    generator = torch.Generator()
    generator.manual_seed(int(seed))
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        drop_last=False,
        generator=generator,
    )
