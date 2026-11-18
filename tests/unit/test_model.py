"""Unit tests for FrameCNN shapes, parameter counts and config overrides."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from game_frame_classifier.model import FrameCNN, count_parameters
from game_frame_classifier.train import (
    SCHEMA,
    apply_set_overrides,
    load_config,
    TrainError,
)


def test_forward_shape():
    model = FrameCNN()
    x = torch.randn(2, 3, 144, 256)
    y = model(x)
    assert y.shape == (2, 6)


def test_parameter_count_flatten():
    model = FrameCNN(head="flatten")
    assert count_parameters(model) == 9_827_878


def test_parameter_count_gap():
    model = FrameCNN(head="gap")
    assert count_parameters(model) == 390_438


def test_eval_mode_deterministic():
    model = FrameCNN()
    model.eval()
    x = torch.randn(2, 3, 144, 256)
    with torch.no_grad():
        a = model(x)
        b = model(x)
    assert torch.equal(a, b)


def test_other_channel_tuple_builds():
    model = FrameCNN(channels=(16, 32, 64, 128), fc_dim=64, head="flatten")
    x = torch.randn(1, 3, 144, 256)
    y = model(x)
    assert y.shape == (1, 6)
    assert count_parameters(model) > 0


def test_set_model_head_gap(tmp_path):
    cfg_path = tmp_path / "train_cnn.json"
    cfg_path.write_text(
        """
{
  "schema": "gfc.train_cnn/1",
  "seed": 360,
  "model": {"channels": [32, 64, 128, 256], "fc_dim": 256, "dropout": 0.5, "head": "flatten"},
  "optim": {"name": "adam", "lr": 0.001, "weight_decay": 0.0001},
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
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(cfg_path)
    assert config["schema"] == SCHEMA
    resolved = apply_set_overrides(config, ["model.head=gap"])
    assert resolved["model"]["head"] == "gap"
    assert config["model"]["head"] == "flatten"


def test_unknown_config_key_rejected(tmp_path):
    cfg_path = tmp_path / "train_cnn.json"
    cfg_path.write_text(
        """
{
  "schema": "gfc.train_cnn/1",
  "seed": 360,
  "model": {"channels": [32, 64, 128, 256], "fc_dim": 256, "dropout": 0.5, "head": "flatten"},
  "optim": {"name": "adam", "lr": 0.001, "weight_decay": 0.0001},
  "batch_size": 64,
  "epochs": 2,
  "early_stop_patience": 6,
  "class_weights": "balanced",
  "device": "cpu",
  "cache": "ram",
  "num_workers": 0,
  "augment": {
    "affine_p": 0.0, "scale": [0.85, 1.15], "translate": [0.02, 0.02],
    "jitter_p": 0.0, "brightness": 0.2, "contrast": 0.2, "saturation": 0.2, "hue": 0.02
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(cfg_path)
    with pytest.raises(TrainError, match="unknown config key"):
        apply_set_overrides(config, ["not_a_real_key=1"])
