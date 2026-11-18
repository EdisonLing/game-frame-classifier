"""Colour-histogram + logistic-regression baseline trainer.

Fits a multinomial logistic regression on per-channel RGB histograms of the
same 256×144 frames the CNN uses. Spec: ``docs/roadmap/tools/baseline.md``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from game_frame_classifier.split_manifest import (
    LABELS,
    SlotRow,
    image_path,
    load_image_u8,
    load_split,
    split_hashes,
)
from game_frame_classifier.sourcing.manifests import write_json

_SCHEMA = "gfc.baseline/1"
_REQUIRED_KEYS = {"schema", "seed", "bins", "c_grid", "max_iter", "class_weight"}


class BaselineError(RuntimeError):
    """Expected config or input error with a command exit code."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def histogram_features(image_u8: np.ndarray, bins: int = 16) -> np.ndarray:
    """Per-channel RGB histograms, each normalised to sum 1; shape (3 * bins,)."""
    if bins < 1:
        raise ValueError(f"bins must be >= 1, got {bins}")
    if image_u8.ndim != 3 or image_u8.shape[2] != 3:
        raise ValueError(f"expected HxWx3 image, got shape {image_u8.shape}")
    height, width, _ = image_u8.shape
    n_pixels = float(height * width)
    edges = np.linspace(0, 256, bins + 1, dtype=np.float64)
    parts: list[np.ndarray] = []
    for channel in range(3):
        counts, _ = np.histogram(image_u8[:, :, channel], bins=edges)
        parts.append((counts.astype(np.float64) / n_pixels).astype(np.float32))
    return np.concatenate(parts, axis=0)


def _features_for_rows(
    rows: Sequence[SlotRow],
    data_root: Path,
    bins: int,
    *,
    tier_mode: str = "assigned",
) -> np.ndarray:
    if not rows:
        return np.zeros((0, 3 * bins), dtype=np.float32)
    out = np.empty((len(rows), 3 * bins), dtype=np.float32)
    for i, row in enumerate(rows):
        path = image_path(row, data_root, tier_mode)
        out[i] = histogram_features(load_image_u8(path), bins=bins)
    return out


def _labels_for_rows(rows: Sequence[SlotRow]) -> np.ndarray:
    return np.asarray([row.label for row in rows], dtype=np.int64)


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _library_versions() -> dict[str, str]:
    import joblib
    import sklearn

    return {
        "numpy": np.__version__,
        "scikit-learn": sklearn.__version__,
        "joblib": joblib.__version__,
    }


def _make_run_id(tag: str | None) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if tag:
        return f"{stamp}_{tag}"
    return stamp


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)


def load_config(path: Path) -> dict[str, Any]:
    """Load and minimally validate baseline settings."""
    if not path.is_file():
        raise BaselineError(f"missing config: {path}", 2)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineError(f"invalid JSON config: {path}", 2) from exc
    missing = _REQUIRED_KEYS - set(config)
    if missing or config.get("schema") != _SCHEMA:
        raise BaselineError(
            f"invalid baseline config; missing {sorted(missing)} or unsupported schema",
            2,
        )
    if not isinstance(config["c_grid"], list) or not config["c_grid"]:
        raise BaselineError("c_grid must be a non-empty list", 2)
    if int(config["bins"]) < 1:
        raise BaselineError("bins must be >= 1", 2)
    return config


def _build_pipeline(c: float, *, max_iter: int, class_weight: str, seed: int):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    C=float(c),
                    max_iter=int(max_iter),
                    class_weight=class_weight,
                    random_state=int(seed),
                    solver="lbfgs",
                ),
            ),
        ]
    )


def _macro_f1(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    from sklearn.metrics import f1_score

    present = sorted({int(v) for v in y_true.tolist()})
    if not present:
        return 0.0
    return float(
        f1_score(
            y_true,
            y_pred,
            labels=present,
            average="macro",
            zero_division=0,
        )
    )


def _accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) == 0:
        return 0.0
    return float(np.mean(y_true == y_pred))


def _search_c(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    c_grid: Sequence[float],
    *,
    max_iter: int,
    class_weight: str,
    seed: int,
) -> tuple[float, list[dict[str, float]], Any]:
    rows: list[dict[str, float]] = []
    best_c: float | None = None
    best_f1 = float("-inf")
    best_pipe = None
    for c in sorted(float(v) for v in c_grid):
        pipe = _build_pipeline(c, max_iter=max_iter, class_weight=class_weight, seed=seed)
        pipe.fit(x_train, y_train)
        pred = pipe.predict(x_val)
        acc = _accuracy(y_val, pred)
        f1 = _macro_f1(y_val, pred)
        rows.append({"C": c, "val_accuracy": acc, "val_macro_f1": f1})
        # Ties go to the smaller C (c_grid is walked ascending).
        if f1 > best_f1:
            best_c = c
            best_f1 = f1
            best_pipe = pipe
    assert best_c is not None and best_pipe is not None
    return best_c, rows, best_pipe


def _write_c_search(path: Path, rows: Sequence[dict[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["C", "val_accuracy", "val_macro_f1"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@dataclass
class BaselinePredictor:
    """Evaluation-facing predictor for a fitted baseline run."""

    labels: tuple[str, ...]
    pipeline: Any
    bins: int

    def predict_proba(
        self,
        rows: list[SlotRow],
        data_root: Path,
        tier_mode: str = "assigned",
    ) -> np.ndarray:
        x = _features_for_rows(rows, Path(data_root), self.bins, tier_mode=tier_mode)
        if len(rows) == 0:
            return np.zeros((0, len(self.labels)), dtype=np.float64)
        proba = self.pipeline.predict_proba(x)
        # Map sklearn class order onto LABELS / GAMES index order.
        class_to_col = {int(c): i for i, c in enumerate(self.pipeline.classes_)}
        out = np.zeros((len(rows), len(self.labels)), dtype=np.float64)
        for label_idx in range(len(self.labels)):
            src = class_to_col.get(label_idx)
            if src is not None:
                out[:, label_idx] = proba[:, src]
        row_sums = out.sum(axis=1, keepdims=True)
        nonzero = row_sums.squeeze(-1) > 0
        out[nonzero] = out[nonzero] / row_sums[nonzero]
        return out


def load_baseline_predictor(run_dir: Path) -> BaselinePredictor:
    """Load a fitted baseline run for evaluation."""
    import joblib

    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if meta.get("model_type") != "baseline":
        raise ValueError(f"{run_dir}: model_type is not 'baseline'")
    labels = tuple(meta["labels"])
    if labels != LABELS:
        raise ValueError(f"{run_dir}: labels do not match LABELS order")
    bins = int(meta["config"]["bins"])
    pipeline = joblib.load(run_dir / "model.joblib")
    return BaselinePredictor(labels=labels, pipeline=pipeline, bins=bins)


def train_baseline(
    *,
    split_dir: Path,
    data_root: Path,
    config: dict[str, Any],
    run_dir: Path,
    tag: str | None = None,
) -> dict[str, Any]:
    """Train on train/val, write the run folder, return run.json payload."""
    import joblib

    split_dir = Path(split_dir).resolve()
    data_root = Path(data_root)
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    seed = int(config["seed"])
    bins = int(config["bins"])
    _seed_everything(seed)

    train_rows = load_split(split_dir, "train")
    val_rows = load_split(split_dir, "val")
    if not train_rows:
        raise BaselineError("train split is empty", 2)
    if not val_rows:
        raise BaselineError("val split is empty", 2)
    train_games = sorted({row.game for row in train_rows})
    if len(train_games) < 2:
        raise BaselineError(
            f"train has only {len(train_games)} game ({', '.join(train_games)}); "
            "the baseline needs at least two games to fit a classifier",
            2,
        )

    x_train = _features_for_rows(train_rows, data_root, bins)
    x_val = _features_for_rows(val_rows, data_root, bins)
    y_train = _labels_for_rows(train_rows)
    y_val = _labels_for_rows(val_rows)

    np.save(run_dir / "features_train.npy", x_train)
    np.save(run_dir / "features_val.npy", x_val)

    chosen_c, search_rows, pipe = _search_c(
        x_train,
        y_train,
        x_val,
        y_val,
        config["c_grid"],
        max_iter=int(config["max_iter"]),
        class_weight=str(config["class_weight"]),
        seed=seed,
    )
    _write_c_search(run_dir / "c_search.csv", search_rows)
    joblib.dump(pipe, run_dir / "model.joblib")

    val_pred = pipe.predict(x_val)
    val_acc = _accuracy(y_val, val_pred)
    val_f1 = _macro_f1(y_val, val_pred)
    print(f"chosen C={chosen_c}")
    print(f"val accuracy={val_acc:.6f}")
    print(f"val macro-F1={val_f1:.6f}")

    summary = json.loads((split_dir / "summary.json").read_text(encoding="utf-8"))
    split_id = str(summary.get("split_id", split_dir.name))
    payload: dict[str, Any] = {
        "run_id": run_dir.name,
        "model_type": "baseline",
        "labels": list(LABELS),
        "split_dir": str(split_dir),
        "split_id": split_id,
        "split_hashes": split_hashes(split_dir),
        "config": config,
        "seed": seed,
        "tag": tag or "",
        "chosen_C": chosen_c,
        "val_accuracy": val_acc,
        "val_macro_f1": val_f1,
        "git_commit": _git_commit(),
        "versions": _library_versions(),
        "n_train": len(train_rows),
        "n_val": len(val_rows),
    }
    write_json(payload, run_dir / "run.json")
    return payload


def _maybe_evaluate(run_dir: Path, data_root: Path) -> None:
    try:
        from game_frame_classifier import evaluation
    except ImportError:
        print("evaluation not available yet; run gfc-evaluate --run <run_dir> --split val later")
        return
    evaluation.evaluate_run(run_dir, "val", data_root=data_root)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfc-train-baseline",
        description="Train the colour-histogram logistic-regression baseline.",
    )
    p.add_argument("--split-dir", required=True, type=Path, help="Split folder")
    p.add_argument("--data-root", type=Path, default=Path("data"), help="Data root")
    p.add_argument(
        "--config",
        type=Path,
        default=Path("config/baseline.json"),
        help="Baseline settings JSON",
    )
    p.add_argument("--tag", default=None, help="Suffix for the run id")
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Run folder (default: <data-root>/runs/baseline/<run_id>)",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = load_config(Path(args.config))
        run_id = _make_run_id(args.tag)
        run_dir = Path(args.out) if args.out is not None else (
            Path(args.data_root) / "runs" / "baseline" / run_id
        )
        train_baseline(
            split_dir=Path(args.split_dir),
            data_root=Path(args.data_root),
            config=config,
            run_dir=run_dir,
            tag=args.tag,
        )
        _maybe_evaluate(run_dir, Path(args.data_root))
        return 0
    except BaselineError as exc:
        print(str(exc), file=sys.stderr)
        return int(exc.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
