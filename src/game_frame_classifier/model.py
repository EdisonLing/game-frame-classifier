"""From-scratch FrameCNN: 256×144 RGB frame → configurable game logits.

Spec: `docs/roadmap/tools/cnn-trainer.md`. Architecture D16 / D16b.
"""

from __future__ import annotations

from typing import Sequence

import torch
from torch import nn


def _conv_block(in_ch: int, out_ch: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(in_ch, out_ch, kernel_size=3, padding=1, bias=False),
        nn.BatchNorm2d(out_ch),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(kernel_size=2),
    )


class FrameCNN(nn.Module):
    """Conv blocks then either flatten+FC or global average pooling."""

    def __init__(
        self,
        channels: Sequence[int] = (32, 64, 128, 256),
        fc_dim: int = 256,
        dropout: float = 0.5,
        head: str = "flatten",
        num_classes: int = 7,
    ) -> None:
        super().__init__()
        if head not in ("flatten", "gap"):
            raise ValueError(f"unknown head: {head!r}")
        if len(channels) < 1:
            raise ValueError("channels must be non-empty")
        self.channels = tuple(int(c) for c in channels)
        if any(channel < 1 for channel in self.channels):
            raise ValueError("channels must contain positive values")
        pooled_h = 144 // (2 ** len(self.channels))
        pooled_w = 256 // (2 ** len(self.channels))
        if pooled_h < 1 or pooled_w < 1:
            raise ValueError("too many channel blocks for a 144x256 input")
        self.fc_dim = int(fc_dim)
        self.dropout_p = float(dropout)
        self.head = head
        self.num_classes = int(num_classes)

        blocks: list[nn.Module] = []
        in_ch = 3
        for out_ch in self.channels:
            blocks.append(_conv_block(in_ch, out_ch))
            in_ch = out_ch
        self.features = nn.Sequential(*blocks)

        last_ch = self.channels[-1]
        if head == "flatten":
            flat_dim = last_ch * pooled_h * pooled_w
            self.classifier = nn.Sequential(
                nn.Flatten(),
                nn.Linear(flat_dim, self.fc_dim),
                nn.ReLU(inplace=True),
                nn.Dropout(self.dropout_p),
                nn.Linear(self.fc_dim, self.num_classes),
            )
        else:
            self.classifier = nn.Sequential(
                nn.AdaptiveAvgPool2d(1),
                nn.Flatten(),
                nn.Dropout(self.dropout_p),
                nn.Linear(last_ch, self.num_classes),
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


def count_parameters(model: nn.Module) -> int:
    """Total trainable parameters."""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
