"""Unit tests for FrameCNN shapes, parameter counts and config overrides."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

torch = pytest.importorskip("torch")
np = pytest.importorskip("numpy")

from game_frame_classifier.model import FrameCNN, count_parameters
from game_frame_classifier.train import (
    SCHEMA,
    _checkpoint_payload,
    apply_set_overrides,
    git_commit,
    load_config,
    macro_f1,
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


def test_checkpoint_payload_is_immutable_cpu_snapshot():
    model = FrameCNN(head="gap")
    payload = _checkpoint_payload(
        model,
        {"model": {"head": "gap"}},
        ("a", "b", "c", "d", "e", "f"),
        1,
        {"val_macro_f1": 0.5},
    )
    saved = {key: value.clone() for key, value in payload["model_state"].items()}
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.add_(1.0)
    for key, value in saved.items():
        assert torch.equal(payload["model_state"][key], value)


def test_macro_f1_skips_zero_support_classes():
    y_true = np.array([0, 0, 1, 1])
    y_pred = np.array([0, 1, 1, 1])
    assert macro_f1(y_true, y_pred, num_classes=6) == pytest.approx(
        ((2 / 3) + 0.8) / 2
    )


@pytest.mark.parametrize(
    "channels",
    [
        (16, 32, 64),
        (16, 32, 64, 128),
        (8, 16, 32, 64, 128),
    ],
)
def test_other_channel_tuple_builds(channels):
    model = FrameCNN(channels=channels, fc_dim=64, head="flatten")
    x = torch.randn(1, 3, 144, 256)
    y = model(x)
    assert y.shape == (1, 6)
    assert count_parameters(model) > 0


def test_git_commit_is_anchored_to_checkout(tmp_path, monkeypatch):
    expected = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
    ).strip()
    monkeypatch.chdir(tmp_path)
    assert git_commit() == expected


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


def test_invalid_config_value_rejected(tmp_path):
    cfg_path = tmp_path / "train_cnn.json"
    cfg_path.write_text(
        Path("config/train_cnn.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config = load_config(cfg_path)
    with pytest.raises(TrainError, match="class_weights"):
        apply_set_overrides(config, ["class_weights=none"])
    with pytest.raises(TrainError, match="epochs"):
        apply_set_overrides(config, ["epochs=0"])
