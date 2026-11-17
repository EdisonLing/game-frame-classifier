"""System tests for FrameDataset + make_loader end to end."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torchvision")

from game_frame_classifier.dataset import (
    FrameDataset,
    eval_transform,
    make_loader,
)
from game_frame_classifier.split_manifest import load_split
from tests.helpers.loader_fixtures import build_split_fixture


def test_make_loader_batch_contract(tmp_path):
    data_root, split_dir = build_split_fixture(
        tmp_path, n_per_game=2, splits=("train", "val")
    )
    rows = load_split(split_dir, "train")
    ds = FrameDataset(rows, data_root, transform=eval_transform(), cache="ram")
    loader = make_loader(ds, batch_size=4, shuffle=True, seed=360)
    images, labels, indices = next(iter(loader))
    assert images.shape == (4, 3, 144, 256)
    assert images.dtype == torch.float32
    assert float(images.min()) >= -1.0 - 1e-5
    assert float(images.max()) <= 1.0 + 1e-5
    assert labels.dtype == torch.int64 or labels.dtype == torch.long
    assert int(labels.min()) >= 0
    assert int(labels.max()) <= 5
    assert indices.shape == (4,)


def test_make_loader_same_seed_same_order(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=2, splits=("train",))
    rows = load_split(split_dir, "train")

    def first_indices(seed: int):
        ds = FrameDataset(rows, data_root, transform=eval_transform(), cache="ram")
        loader = make_loader(ds, batch_size=4, shuffle=True, seed=seed)
        _, _, indices = next(iter(loader))
        return indices.tolist()

    assert first_indices(360) == first_indices(360)
    assert first_indices(360) != first_indices(361)


def test_cache_ram_matches_none_on_eval(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=1, splits=("val",))
    rows = load_split(split_dir, "val")
    tfm = eval_transform()
    ds_ram = FrameDataset(rows, data_root, transform=tfm, cache="ram")
    ds_none = FrameDataset(rows, data_root, transform=tfm, cache="none")
    for i in range(len(rows)):
        a, la, ia = ds_ram[i]
        b, lb, ib = ds_none[i]
        assert ia == ib == i
        assert la == lb
        assert torch.equal(a, b)
        # Second read from RAM cache must match
        a2, _, _ = ds_ram[i]
        assert torch.equal(a, a2)


def test_split_manifest_source_has_no_torch():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    src = (root / "src" / "game_frame_classifier" / "split_manifest.py").read_text(
        encoding="utf-8"
    )
    assert "import torch" not in src
    assert "from torch" not in src
