"""Train FrameCNN on a split, pick best val macro-F1, write a run folder.

Spec: `docs/roadmap/tools/cnn-trainer.md`. CLI: ``gfc-train-cnn``.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import random
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn
from torch.utils.data import DataLoader

from game_frame_classifier.public_sources import copy_split_licenses
from game_frame_classifier.dataset import (
    AugmentConfig,
    FrameDataset,
    eval_transform,
    make_loader,
    train_transform,
)
from game_frame_classifier.model import FrameCNN, count_parameters
from game_frame_classifier.split_manifest import (
    SlotRow,
    class_weights,
    labels_for_set,
    load_split,
    split_hashes,
)
from game_frame_classifier.sourcing.labels import OTHER

SCHEMA = "gfc.train_cnn/1"
NORMALISATION = {"mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5]}

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

HISTORY_COLUMNS = (
    "epoch",
    "train_loss",
    "train_acc",
    "val_loss",
    "val_acc",
    "val_macro_f1",
    "lr",
    "seconds",
)


class TrainError(ValueError):
    """Config or input problem for the CNN trainer."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "train_cnn.json"


def _require_keys(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TrainError(f"{path} must be an object")
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing:
        raise TrainError(f"{path} missing config keys: {sorted(missing)}")
    if unknown:
        raise TrainError(f"unknown config keys in {path}: {sorted(unknown)}")
    return value


def _whole_number(value: Any, path: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise TrainError(f"{path} must be a whole number >= {minimum}")
    return value


def _probability(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrainError(f"{path} must be a number in [0, 1]")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise TrainError(f"{path} must be a number in [0, 1]")
    return number


def _nonnegative_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrainError(f"{path} must be a number >= 0")
    number = float(value)
    if number < 0:
        raise TrainError(f"{path} must be a number >= 0")
    return number


def validate_config(config: dict[str, Any]) -> None:
    """Validate the resolved config before constructing data or model objects."""
    config.setdefault("label_set", "seven")
    root = _require_keys(
        config,
        {
            "schema",
            "label_set",
            "seed",
            "model",
            "optim",
            "batch_size",
            "epochs",
            "early_stop_patience",
            "class_weights",
            "device",
            "cache",
            "num_workers",
            "augment",
        },
        "config",
    )
    if root["schema"] != SCHEMA:
        raise TrainError(f"config schema must be {SCHEMA!r}")
    if root["label_set"] not in {"six", "seven"}:
        raise TrainError("label_set must be 'six' or 'seven'")
    _whole_number(root["seed"], "seed", 0)
    _whole_number(root["batch_size"], "batch_size", 1)
    _whole_number(root["epochs"], "epochs", 1)
    _whole_number(root["early_stop_patience"], "early_stop_patience", 1)
    _whole_number(root["num_workers"], "num_workers", 0)
    if root["class_weights"] != "balanced":
        raise TrainError("class_weights must be 'balanced'")
    if root["device"] not in ("auto", "cpu", "cuda", "mps"):
        raise TrainError("device must be one of auto, cpu, cuda or mps")
    if root["cache"] not in ("ram", "none"):
        raise TrainError("cache must be 'ram' or 'none'")

    model = _require_keys(
        root["model"], {"channels", "fc_dim", "dropout", "head"}, "model"
    )
    channels = model["channels"]
    if (
        not isinstance(channels, list)
        or len(channels) != 4
        or any(type(channel) is not int or channel < 1 for channel in channels)
    ):
        raise TrainError("model.channels must contain four positive whole numbers")
    _whole_number(model["fc_dim"], "model.fc_dim", 1)
    _probability(model["dropout"], "model.dropout")
    if model["head"] not in ("flatten", "gap"):
        raise TrainError("model.head must be 'flatten' or 'gap'")

    optim = _require_keys(root["optim"], {"name", "lr", "weight_decay"}, "optim")
    if str(optim["name"]).lower() != "adam":
        raise TrainError("optim.name must be 'adam'")
    for key, minimum in (("lr", 0.0), ("weight_decay", 0.0)):
        value = optim[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TrainError(f"optim.{key} must be a number >= {minimum}")
        if float(value) < minimum or (key == "lr" and float(value) == 0.0):
            comparator = "> 0" if key == "lr" else ">= 0"
            raise TrainError(f"optim.{key} must be {comparator}")

    augment = _require_keys(
        root["augment"],
        {
            "affine_p",
            "scale",
            "translate",
            "jitter_p",
            "brightness",
            "contrast",
            "saturation",
            "hue",
        },
        "augment",
    )
    _probability(augment["affine_p"], "augment.affine_p")
    _probability(augment["jitter_p"], "augment.jitter_p")
    for key in ("brightness", "contrast", "saturation"):
        _nonnegative_number(augment[key], f"augment.{key}")
    hue = _probability(augment["hue"], "augment.hue")
    if hue > 0.5:
        raise TrainError("augment.hue must be in [0, 0.5]")
    for key in ("scale", "translate"):
        pair = augment[key]
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in pair
            )
        ):
            raise TrainError(f"augment.{key} must contain two numbers")
    if not 0 < float(augment["scale"][0]) <= float(augment["scale"][1]):
        raise TrainError("augment.scale must be positive and ordered")
    if any(not 0 <= float(value) <= 1 for value in augment["translate"]):
        raise TrainError("augment.translate values must be in [0, 1]")


def _parse_set_value(raw: str) -> Any:
    text = raw.strip()
    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower == "null" or lower == "none":
        return None
    try:
        if text.startswith("[") or text.startswith("{"):
            return json.loads(text)
        if "." in text or "e" in lower:
            return float(text)
        return int(text)
    except (json.JSONDecodeError, ValueError):
        return text


def apply_set_overrides(config: dict[str, Any], sets: Sequence[str]) -> dict[str, Any]:
    """Apply dotted ``key=value`` overrides; unknown keys raise."""
    out = deepcopy(config)
    for item in sets:
        if "=" not in item:
            raise TrainError(f"invalid --set (expected key=value): {item!r}")
        key, raw = item.split("=", 1)
        parts = [p for p in key.split(".") if p]
        if not parts:
            raise TrainError(f"invalid --set key: {item!r}")
        value = _parse_set_value(raw)
        cursor: dict[str, Any] = out
        for part in parts[:-1]:
            if part not in cursor or not isinstance(cursor[part], dict):
                raise TrainError(f"unknown config key: {'.'.join(parts)}")
            cursor = cursor[part]
        leaf = parts[-1]
        if leaf not in cursor:
            raise TrainError(f"unknown config key: {'.'.join(parts)}")
        if isinstance(cursor[leaf], dict) and not isinstance(value, dict):
            raise TrainError(f"cannot replace object key with scalar: {'.'.join(parts)}")
        cursor[leaf] = value
    validate_config(out)
    return out


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TrainError(f"missing config: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrainError(f"invalid JSON config: {path}") from exc
    validate_config(data)
    return data


def resolve_device(requested: str) -> torch.device:
    name = requested.strip().lower()
    if name == "cpu":
        return torch.device("cpu")
    if name == "cuda":
        if not torch.cuda.is_available():
            raise TrainError("device cuda requested but torch.cuda.is_available() is False")
        return torch.device("cuda")
    if name == "mps":
        if not getattr(torch.backends, "mps", None) or not torch.backends.mps.is_available():
            raise TrainError("device mps requested but not available")
        return torch.device("mps")
    if name != "auto":
        raise TrainError(f"unknown device: {requested!r}")
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def git_commit() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def make_run_id(tag: str | None = None) -> str:
    base = datetime.now().strftime("%Y%m%d-%H%M%S")
    if tag:
        return f"{base}_{tag}"
    return base


def model_from_config(model_cfg: dict[str, Any], num_classes: int = 7) -> FrameCNN:
    return FrameCNN(
        channels=tuple(model_cfg["channels"]),
        fc_dim=int(model_cfg["fc_dim"]),
        dropout=float(model_cfg["dropout"]),
        head=str(model_cfg["head"]),
        num_classes=num_classes,
    )


def augment_from_config(aug: dict[str, Any]) -> AugmentConfig:
    scale = aug["scale"]
    translate = aug["translate"]
    return AugmentConfig(
        affine_p=float(aug["affine_p"]),
        scale=(float(scale[0]), float(scale[1])),
        translate=(float(translate[0]), float(translate[1])),
        jitter_p=float(aug["jitter_p"]),
        brightness=float(aug["brightness"]),
        contrast=float(aug["contrast"]),
        saturation=float(aug["saturation"]),
        hue=float(aug["hue"]),
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def macro_f1(y_true: np.ndarray, y_pred: np.ndarray, num_classes: int) -> float:
    """Macro-F1 over classes that appear in y_true (zero-support classes skipped)."""
    scores: list[float] = []
    for c in range(num_classes):
        support = int(np.sum(y_true == c))
        if support == 0:
            continue
        tp = int(np.sum((y_true == c) & (y_pred == c)))
        fp = int(np.sum((y_true != c) & (y_pred == c)))
        fn = int(np.sum((y_true == c) & (y_pred != c)))
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        if prec + rec == 0:
            scores.append(0.0)
        else:
            scores.append(2.0 * prec * rec / (prec + rec))
    if not scores:
        return 0.0
    return float(np.mean(scores))


def _accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) == 0:
        return 0.0
    return float(np.mean(y_true == y_pred))


# ---------------------------------------------------------------------------
# Train / eval loops
# ---------------------------------------------------------------------------


def _run_train_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimiser: torch.optim.Optimizer,
    device: torch.device,
) -> tuple[float, float]:
    model.train()
    total_loss = 0.0
    total_correct = 0
    total_n = 0
    for images, labels, _ in loader:
        images = images.to(device)
        labels = labels.to(device)
        optimiser.zero_grad(set_to_none=True)
        logits = model(images)
        loss = criterion(logits, labels)
        loss.backward()
        optimiser.step()
        batch_n = int(labels.size(0))
        total_loss += float(loss.item()) * batch_n
        preds = logits.argmax(dim=1)
        total_correct += int((preds == labels).sum().item())
        total_n += batch_n
    if total_n == 0:
        return 0.0, 0.0
    return total_loss / total_n, total_correct / total_n


@torch.no_grad()
def _run_eval(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    num_classes: int,
) -> tuple[float, float, float, np.ndarray, np.ndarray]:
    model.eval()
    total_loss = 0.0
    total_n = 0
    all_true: list[np.ndarray] = []
    all_pred: list[np.ndarray] = []
    for images, labels, _ in loader:
        images = images.to(device)
        labels = labels.to(device)
        logits = model(images)
        loss = criterion(logits, labels)
        batch_n = int(labels.size(0))
        total_loss += float(loss.item()) * batch_n
        total_n += batch_n
        preds = logits.argmax(dim=1)
        all_true.append(labels.detach().cpu().numpy())
        all_pred.append(preds.detach().cpu().numpy())
    if total_n == 0:
        empty = np.array([], dtype=np.int64)
        return 0.0, 0.0, 0.0, empty, empty
    y_true = np.concatenate(all_true)
    y_pred = np.concatenate(all_pred)
    return (
        total_loss / total_n,
        _accuracy(y_true, y_pred),
        macro_f1(y_true, y_pred, num_classes),
        y_true,
        y_pred,
    )


def plot_curves(history_rows: list[dict[str, Any]], best_epoch: int, out_path: Path) -> bool:
    """Write curves.png without a GUI backend; plotting can never fail training."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        epochs = [int(r["epoch"]) for r in history_rows]
        fig = Figure(figsize=(10, 4))
        FigureCanvasAgg(fig)
        axes = fig.subplots(1, 2)
        axes[0].plot(
            epochs, [float(r["train_loss"]) for r in history_rows], label="train"
        )
        axes[0].plot(
            epochs, [float(r["val_loss"]) for r in history_rows], label="val"
        )
        axes[0].axvline(
            best_epoch, color="gray", linestyle="--", label=f"best {best_epoch}"
        )
        axes[0].set_xlabel("epoch")
        axes[0].set_ylabel("loss")
        axes[0].legend()
        axes[0].set_title("Loss")
        axes[1].plot(
            epochs, [float(r["train_acc"]) for r in history_rows], label="train"
        )
        axes[1].plot(
            epochs, [float(r["val_acc"]) for r in history_rows], label="val"
        )
        axes[1].axvline(
            best_epoch, color="gray", linestyle="--", label=f"best {best_epoch}"
        )
        axes[1].set_xlabel("epoch")
        axes[1].set_ylabel("accuracy")
        axes[1].legend()
        axes[1].set_title("Accuracy")
        fig.tight_layout()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=150)
        return True
    except Exception as exc:  # plotting is an optional run artifact
        print(f"could not write curves.png; skipping figure ({exc})")
        return False


def _checkpoint_payload(
    model: nn.Module,
    config: dict[str, Any],
    labels: Sequence[str],
    epoch: int,
    val_metrics: dict[str, float],
) -> dict[str, Any]:
    return {
        # clone() is required on CPU: detach().cpu() alone can share model storage,
        # allowing later optimiser steps to overwrite the selected best epoch.
        "model_state": {
            k: v.detach().cpu().clone() for k, v in model.state_dict().items()
        },
        "config": deepcopy(config),
        "labels": list(labels),
        "normalisation": deepcopy(NORMALISATION),
        "epoch": int(epoch),
        "val_metrics": dict(val_metrics),
    }


def save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, path)


# ---------------------------------------------------------------------------
# Predictor
# ---------------------------------------------------------------------------


class CnnPredictor:
    """Load a trained CNN run and score rows with softmax probabilities."""

    def __init__(
        self,
        model: FrameCNN,
        labels: tuple[str, ...],
        device: torch.device,
        batch_size: int = 64,
    ) -> None:
        self.model = model
        self.labels = labels
        self.device = device
        self.batch_size = batch_size
        self.model.to(device)
        self.model.eval()

    @torch.no_grad()
    def predict_proba(
        self,
        rows: list[SlotRow],
        data_root: Path,
        tier_mode: str = "assigned",
    ) -> np.ndarray:
        if not rows:
            return np.zeros((0, len(self.labels)), dtype=np.float64)
        ds = FrameDataset(
            rows,
            Path(data_root),
            tier_mode=tier_mode,
            transform=eval_transform(),
            cache="none",
        )
        loader = make_loader(
            ds,
            batch_size=self.batch_size,
            shuffle=False,
            seed=0,
            num_workers=0,
        )
        chunks: list[np.ndarray] = []
        order: list[int] = []
        for images, _labels, indices in loader:
            images = images.to(self.device)
            logits = self.model(images)
            probs = F.softmax(logits, dim=1).detach().cpu().numpy()
            chunks.append(probs)
            order.extend(int(i) for i in indices.tolist())
        stacked = np.concatenate(chunks, axis=0)
        out = np.zeros_like(stacked)
        for pos, row_i in enumerate(order):
            out[row_i] = stacked[pos]
        return out


def load_cnn_predictor(run_dir: Path) -> CnnPredictor:
    """Rebuild FrameCNN from run.json + best.pt (weights_only=True)."""
    run_dir = Path(run_dir)
    run_path = run_dir / "run.json"
    if not run_path.is_file():
        raise TrainError(f"missing run.json: {run_path}")
    meta = json.loads(run_path.read_text(encoding="utf-8"))
    if meta.get("model_type") != "cnn":
        raise TrainError(f"run is not model_type cnn: {run_dir}")
    labels = tuple(meta["labels"])
    config = meta["config"]
    try:
        device = resolve_device(str(meta.get("device", "auto")))
    except TrainError:
        device = resolve_device("auto")
    ckpt_path = run_dir / "best.pt"
    payload = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    model = model_from_config(config["model"], num_classes=len(labels))
    model.load_state_dict(payload["model_state"])
    batch_size = int(config.get("batch_size", 64))
    return CnnPredictor(model, labels, device, batch_size=batch_size)


# ---------------------------------------------------------------------------
# Training entry
# ---------------------------------------------------------------------------


def train_run(
    *,
    split_dir: Path,
    data_root: Path,
    config: dict[str, Any],
    run_dir: Path,
    run_id: str,
    limit: int | None = None,
) -> dict[str, Any]:
    validate_config(config)
    split_dir = Path(split_dir).resolve()
    data_root = Path(data_root).resolve()
    run_dir = Path(run_dir)
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise TrainError(f"run folder already exists: {run_dir}") from exc

    seed = int(config["seed"])
    label_set = str(config["label_set"])
    labels = labels_for_set(label_set)
    seed_everything(seed)
    device = resolve_device(str(config["device"]))

    train_rows = load_split(split_dir, "train", label_set=label_set)
    val_rows = load_split(split_dir, "val", label_set=label_set)
    if limit is not None:
        n = int(limit)
        if n < 1:
            raise TrainError("limit must be a whole number >= 1")
        train_rows = train_rows[:n]
        val_rows = val_rows[:n]
    if not train_rows:
        raise TrainError("train split is empty")
    if not val_rows:
        raise TrainError("val split is empty")
    if label_set == "seven" and not any(row.game == OTHER for row in train_rows):
        raise TrainError("no Other frames in train; use label_set six")

    summary = json.loads((split_dir / "summary.json").read_text(encoding="utf-8"))
    split_id = str(summary.get("split_id", split_dir.name))
    hashes = split_hashes(split_dir)

    weights = class_weights(train_rows, labels)
    weight_t = torch.tensor(weights, dtype=torch.float32, device=device)

    model = model_from_config(config["model"], num_classes=len(labels))
    model.to(device)
    param_count = count_parameters(model)

    aug_cfg = augment_from_config(config["augment"])
    # Disable augmentation when all probs are zero (overfit / smoke convenience)
    train_tfm = train_transform(aug_cfg)
    val_tfm = eval_transform()
    cache = str(config.get("cache", "ram"))
    train_ds = FrameDataset(train_rows, data_root, transform=train_tfm, cache=cache)
    val_ds = FrameDataset(val_rows, data_root, transform=val_tfm, cache=cache)

    batch_size = int(config["batch_size"])
    num_workers = int(config.get("num_workers", 0))
    train_loader = make_loader(
        train_ds,
        batch_size=batch_size,
        shuffle=True,
        seed=seed,
        num_workers=num_workers,
    )
    val_loader = make_loader(
        val_ds,
        batch_size=batch_size,
        shuffle=False,
        seed=seed,
        num_workers=0,
    )

    optim_cfg = config["optim"]
    if str(optim_cfg["name"]).lower() != "adam":
        raise TrainError(f"unsupported optimiser: {optim_cfg['name']!r}")
    optimiser = torch.optim.Adam(
        model.parameters(),
        lr=float(optim_cfg["lr"]),
        weight_decay=float(optim_cfg["weight_decay"]),
    )
    criterion = nn.CrossEntropyLoss(weight=weight_t)

    epochs = int(config["epochs"])
    patience = int(config["early_stop_patience"])
    history_rows: list[dict[str, Any]] = []
    history_path = run_dir / "history.csv"
    with history_path.open("w", encoding="utf-8", newline="") as f:
        csv.DictWriter(f, fieldnames=list(HISTORY_COLUMNS)).writeheader()
    best_f1 = -1.0
    best_epoch = 0
    best_state: dict[str, Any] | None = None
    best_val_metrics: dict[str, float] = {}
    epochs_without_improve = 0
    wall_start = time.perf_counter()

    first_epoch_train_loss: float | None = None

    for epoch in range(1, epochs + 1):
        t0 = time.perf_counter()
        train_loss, train_acc = _run_train_epoch(
            model, train_loader, criterion, optimiser, device
        )
        val_loss, val_acc, val_f1, _, _ = _run_eval(
            model, val_loader, criterion, device, len(labels)
        )
        seconds = time.perf_counter() - t0
        lr = float(optimiser.param_groups[0]["lr"])
        row = {
            "epoch": epoch,
            "train_loss": train_loss,
            "train_acc": train_acc,
            "val_loss": val_loss,
            "val_acc": val_acc,
            "val_macro_f1": val_f1,
            "lr": lr,
            "seconds": seconds,
        }
        history_rows.append(row)
        with history_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(HISTORY_COLUMNS))
            writer.writerow({k: row[k] for k in HISTORY_COLUMNS})
        print(
            f"epoch {epoch:02d}  train_loss={train_loss:.4f} train_acc={train_acc:.4f}  "
            f"val_loss={val_loss:.4f} val_acc={val_acc:.4f} val_macro_f1={val_f1:.4f}  "
            f"({seconds:.1f}s)"
        )
        if first_epoch_train_loss is None:
            first_epoch_train_loss = train_loss

        if val_f1 > best_f1:
            best_f1 = val_f1
            best_epoch = epoch
            best_val_metrics = {
                "val_loss": val_loss,
                "val_acc": val_acc,
                "val_macro_f1": val_f1,
            }
            best_state = _checkpoint_payload(
                model, config, labels, epoch, best_val_metrics
            )
            epochs_without_improve = 0
        else:
            epochs_without_improve += 1
            if epochs_without_improve >= patience:
                print(f"early stop at epoch {epoch} (patience {patience})")
                break

    wall_time = time.perf_counter() - wall_start
    last_payload = _checkpoint_payload(
        model,
        config,
        labels,
        int(history_rows[-1]["epoch"]),
        {
            "val_loss": float(history_rows[-1]["val_loss"]),
            "val_acc": float(history_rows[-1]["val_acc"]),
            "val_macro_f1": float(history_rows[-1]["val_macro_f1"]),
        },
    )
    if best_state is None:
        best_state = last_payload
        best_epoch = int(history_rows[-1]["epoch"])
        best_val_metrics = last_payload["val_metrics"]

    save_checkpoint(run_dir / "best.pt", best_state)
    save_checkpoint(run_dir / "last.pt", last_payload)

    plot_curves(history_rows, best_epoch, run_dir / "curves.png")

    # Restore best weights into model for optional end-of-run evaluation
    model.load_state_dict(best_state["model_state"])

    run_meta: dict[str, Any] = {
        "run_id": run_id,
        "model_type": "cnn",
        "label_set": label_set,
        "labels": list(labels),
        "split_dir": str(split_dir),
        "split_id": split_id,
        "split_hashes": hashes,
        "config": deepcopy(config),
        "normalisation": deepcopy(NORMALISATION),
        "param_count": param_count,
        "git_commit": git_commit(),
        "torch_version": torch.__version__,
        "device": str(device),
        "best_epoch": best_epoch,
        "best_val_metrics": best_val_metrics,
        "wall_time_s": wall_time,
        "n_train": len(train_rows),
        "n_val": len(val_rows),
        "first_epoch_train_loss": first_epoch_train_loss,
    }
    (run_dir / "run.json").write_text(
        json.dumps(run_meta, indent=2) + "\n", encoding="utf-8"
    )
    copy_split_licenses(split_dir, run_dir)

    module_name = "game_frame_classifier.evaluation"
    try:
        evaluation = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        print(
            "evaluation not available yet; "
            "run gfc-evaluate --run <run_dir> --split val later"
        )
    else:
        evaluation.evaluate_run(run_dir, "val", data_root=data_root)

    return run_meta


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfc-train-cnn",
        description="Train FrameCNN on a split and write a reproducible run folder.",
    )
    p.add_argument("--split-dir", type=Path, required=True, help="Split folder")
    p.add_argument("--data-root", type=Path, default=Path("data"), help="Data root")
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Settings JSON (default config/train_cnn.json)",
    )
    p.add_argument(
        "--set",
        dest="sets",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override one config value (repeatable, dotted keys)",
    )
    p.add_argument("--epochs", type=int, default=None, help="Shortcut for epochs")
    p.add_argument("--device", type=str, default=None, help="Shortcut for device")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Use only the first N rows of train and val",
    )
    p.add_argument("--tag", type=str, default=None, help="Run id suffix")
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Run folder (default data/runs/cnn/<run_id>)",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        config_path = Path(args.config) if args.config else default_config_path()
        config = load_config(config_path)
        if args.epochs is not None:
            config = apply_set_overrides(config, [f"epochs={int(args.epochs)}"])
        if args.device is not None:
            config = apply_set_overrides(config, [f"device={args.device}"])
        if args.sets:
            config = apply_set_overrides(config, args.sets)

        run_id = make_run_id(args.tag)
        data_root = Path(args.data_root)
        if args.out is not None:
            run_dir = Path(args.out)
        else:
            run_dir = data_root / "runs" / "cnn" / run_id

        train_run(
            split_dir=Path(args.split_dir),
            data_root=data_root,
            config=config,
            run_dir=run_dir,
            run_id=run_id,
            limit=args.limit,
        )
        print(f"wrote {run_dir}")
        return EXIT_OK
    except TrainError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
