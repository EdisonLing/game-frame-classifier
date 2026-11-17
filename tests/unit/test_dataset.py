"""Unit tests for dataset transforms and FrameDataset decode path."""

from __future__ import annotations

import inspect

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torchvision")

from game_frame_classifier.dataset import (
    AugmentConfig,
    FrameDataset,
    eval_transform,
    train_transform,
)
from game_frame_classifier.split_manifest import load_split
from tests.helpers.loader_fixtures import build_split_fixture


def test_eval_transform_formula():
    x = torch.randint(0, 256, (3, 144, 256), dtype=torch.uint8)
    y = eval_transform()(x)
    expected = (x.float() / 255.0 - 0.5) / 0.5
    assert y.dtype == torch.float32
    assert torch.allclose(y, expected)
    assert torch.equal(y, eval_transform()(x))


def test_train_transform_shape_dtype():
    cfg = AugmentConfig()
    x = torch.randint(0, 256, (3, 144, 256), dtype=torch.uint8)
    y = train_transform(cfg)(x.clone())
    assert y.shape == (3, 144, 256)
    assert y.dtype == torch.float32


def test_no_flip_in_train_pipeline():
    src = inspect.getsource(train_transform)
    for banned in (
        "RandomHorizontalFlip",
        "RandomVerticalFlip",
        "hflip",
        "vflip",
        "HorizontalFlip",
        "VerticalFlip",
    ):
        assert banned not in src


def test_train_with_zero_probs_matches_eval():
    cfg = AugmentConfig(affine_p=0.0, jitter_p=0.0)
    x = torch.randint(0, 256, (3, 144, 256), dtype=torch.uint8)
    assert torch.allclose(train_transform(cfg)(x.clone()), eval_transform()(x.clone()))


def test_asymmetric_image_never_mirrored(tmp_path):
    data_root, split_dir = build_split_fixture(
        tmp_path, n_per_game=1, splits=("train",), asymmetric=True
    )
    rows = load_split(split_dir, "train")
    ds = FrameDataset(rows[:1], data_root, transform=None, cache="none")
    raw = ds._decode_u8(0)
    rb = raw[0].float() - raw[2].float()
    assert float(rb[:, :128].mean()) > float(rb[:, 128:].mean())

    # Geometry only: colour jitter can rotate hue enough to confuse R−B.
    tfm = train_transform(AugmentConfig(affine_p=1.0, jitter_p=0.0))
    for _ in range(200):
        out = tfm(raw.clone())
        img = out * 0.5 + 0.5
        diff = img[0] - img[2]
        assert float(diff[:, :128].mean()) > float(diff[:, 128:].mean())
