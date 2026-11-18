"""Shared evaluation for baseline and CNN runs (`gfc-evaluate`).

Scores a trained run on a split, writes metrics and figures, gates held-out
test access (D13 / G1), compares two runs, and draws dataset report figures.
Spec: `docs/roadmap/tools/evaluation.md`.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np

from game_frame_classifier.sourcing.manifests import write_json
from game_frame_classifier.sourcing.labels import CLASSES, GAMES, OTHER
from game_frame_classifier.split_manifest import SlotRow, load_split, split_hashes

LABELS = CLASSES
OPEN_SET_FALSE_ALARM_RATE = 0.05
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 360

LOOKALIKE = ("Overwatch_2", "Marvel_Rivals")
_TEST_SPLITS = frozenset({"test_session", "test_source"})
_ALLOWED_SPLITS = frozenset({"train", "val", "test_session", "test_source"})
_RUN_JSON_REQUIRED = (
    "run_id",
    "model_type",
    "labels",
    "split_dir",
    "split_id",
    "split_hashes",
)

# model_type -> dotted module attribute that returns a Predictor for a run_dir
_PREDICTOR_LOADERS: dict[str, tuple[str, str]] = {
    "baseline": ("game_frame_classifier.baseline", "load_baseline_predictor"),
    "cnn": ("game_frame_classifier.train", "load_cnn_predictor"),
}

# Tests register callables here; takes precedence over the module registry.
_PREDICTOR_REGISTRY: dict[str, Callable[[Path], "Predictor"]] = {}


class Predictor(Protocol):
    labels: tuple[str, ...]

    def predict_proba(
        self,
        rows: list[SlotRow],
        data_root: Path,
        tier_mode: str = "assigned",
    ) -> np.ndarray:
        """Return class probabilities shaped (N, len(labels))."""


def register_predictor_loader(model_type: str, loader: Callable[[Path], Predictor]) -> None:
    """Register a predictor loader (used by tests and optional plugins)."""
    _PREDICTOR_REGISTRY[model_type] = loader


def clear_predictor_registry() -> None:
    """Remove test/plugin loaders; restores the built-in module registry only."""
    _PREDICTOR_REGISTRY.clear()


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        return (out.stdout or "").strip() or "unknown"
    except OSError:
        return "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_run_json(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "run.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in _RUN_JSON_REQUIRED if k not in data]
    if missing:
        raise ValueError(f"{path}: missing fields {missing}")
    return data


def load_predictor(run_dir: Path) -> Predictor:
    """Dispatch on run.json model_type; lazy-import baseline/train modules."""
    run = _load_run_json(run_dir)
    model_type = str(run["model_type"])
    if model_type in _PREDICTOR_REGISTRY:
        return _PREDICTOR_REGISTRY[model_type](Path(run_dir))
    if model_type not in _PREDICTOR_LOADERS:
        raise ValueError(f"unknown model_type {model_type!r}")
    module_name, attr = _PREDICTOR_LOADERS[model_type]
    try:
        module = __import__(module_name, fromlist=[attr])
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"model type {model_type!r} is not available yet ({module_name})"
        ) from exc
    loader = getattr(module, attr, None)
    if loader is None:
        raise RuntimeError(
            f"model type {model_type!r} is not available yet "
            f"({module_name}.{attr} missing)"
        )
    return loader(Path(run_dir))


def _resolve_split_dir(run: dict[str, Any], split_dir: Path | None) -> Path:
    if split_dir is not None:
        return Path(split_dir)
    return Path(run["split_dir"])


def _check_labels(run: dict[str, Any]) -> None:
    labels = tuple(run["labels"])
    if labels not in {GAMES, CLASSES}:
        raise ValueError(
            f"run labels {labels} do not match a supported label set"
        )


def _hash_changed(run: dict[str, Any], split_dir: Path) -> bool:
    stored = {str(k): str(v) for k, v in dict(run["split_hashes"]).items()}
    current = split_hashes(split_dir)
    return stored != current


def _require_test_access(
    split: str,
    split_dir: Path,
    *,
    reason: str | None,
    run_dir: Path,
    data_root: Path,
) -> None:
    if split not in _TEST_SPLITS:
        return
    freeze = Path(split_dir) / "freeze.json"
    if not freeze.is_file():
        raise PermissionError(
            f"refusing {split!r}: {freeze} missing (gate G1 / D13)"
        )
    if not reason or not str(reason).strip():
        raise PermissionError(
            f"refusing {split!r}: --reason is required for test splits"
        )
    run = _load_run_json(run_dir)
    log_dir = Path(data_root) / "runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "holdout_access.jsonl"
    line = {
        "utc": _utc_now(),
        "run": str(run["run_id"]),
        "split": split,
        "reason": str(reason).strip(),
        "git_commit": _git_commit(),
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float | None]:
    """Scores for one class. No support: all null. A class with rows that is never predicted
    gets precision 0 (not null), so it counts as F1 0 in macro-F1 instead of being dropped."""
    if tp + fn == 0:
        return None, None, None
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn)
    f1 = 0.0 if precision + recall == 0 else 2.0 * precision * recall / (precision + recall)
    return precision, recall, f1


def compute_classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    *,
    labels: tuple[str, ...] = LABELS,
) -> dict[str, Any]:
    """Accuracy, per-class P/R/F1, macro-F1 and confusion; zero-support → null."""
    y_true = np.asarray(y_true, dtype=np.int64)
    y_pred = np.asarray(y_pred, dtype=np.int64)
    n_labels = len(labels)
    n = int(y_true.shape[0])
    confusion = np.zeros((n_labels, n_labels), dtype=np.int64)
    for t, p in zip(y_true.tolist(), y_pred.tolist()):
        if 0 <= t < n_labels and 0 <= p < n_labels:
            confusion[t, p] += 1
    per_class: dict[str, dict[str, Any]] = {}
    f1_values: list[float] = []
    for i, name in enumerate(labels):
        support = int(confusion[i].sum())
        tp = int(confusion[i, i])
        fp = int(confusion[:, i].sum() - tp)
        fn = int(confusion[i].sum() - tp)
        precision, recall, f1 = _precision_recall_f1(tp, fp, fn)
        if support == 0:
            per_class[name] = {
                "precision": None,
                "recall": None,
                "f1": None,
                "support": 0,
            }
        else:
            per_class[name] = {
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "support": support,
            }
            if f1 is not None:
                f1_values.append(float(f1))
    accuracy = float((y_true == y_pred).mean()) if n else 0.0
    macro_f1 = float(np.mean(f1_values)) if f1_values else None
    return {
        "n": n,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "per_class": per_class,
        "confusion": confusion.tolist(),
        "zero_support_note": (
            "A class with no rows gets null scores and is left out of macro-F1."
        ),
    }


def compute_six_game_metrics(
    rows: list[SlotRow],
    y_pred: np.ndarray,
) -> dict[str, Any]:
    """Score only six-game rows; predicting Other remains an ordinary error."""
    keep = np.asarray([row.game in GAMES for row in rows], dtype=bool)
    y_true = np.asarray([row.label for row in rows], dtype=np.int64)[keep]
    pred = np.asarray(y_pred, dtype=np.int64)[keep]
    f1s: list[float] = []
    for label in range(len(GAMES)):
        support = int(np.sum(y_true == label))
        if not support:
            continue
        tp = int(np.sum((y_true == label) & (pred == label)))
        fp = int(np.sum((y_true != label) & (pred == label)))
        fn = int(np.sum((y_true == label) & (pred != label)))
        _, _, f1 = _precision_recall_f1(tp, fp, fn)
        f1s.append(float(f1 or 0.0))
    return {
        "n": int(len(y_true)),
        "accuracy": float(np.mean(y_true == pred)) if len(y_true) else 0.0,
        "macro_f1": float(np.mean(f1s)) if f1s else None,
    }


def _open_scores(probs: np.ndarray) -> np.ndarray:
    return 1.0 - np.max(np.asarray(probs, dtype=np.float64)[:, :len(GAMES)], axis=1)


def _threshold_at_false_alarm(scores: np.ndarray, rate: float = OPEN_SET_FALSE_ALARM_RATE) -> float:
    """Largest empirical tail no greater than ``rate`` under the strict ``score > tau`` rule."""
    values = np.sort(np.asarray(scores, dtype=np.float64))
    if not len(values):
        raise ValueError("cannot choose open-set threshold without six-game val rows")
    allowed = int(np.floor(rate * len(values)))
    if allowed < 1:
        return float(values[-1])
    return float(values[-allowed - 1])


def _binary_auroc(scores: np.ndarray, positive: np.ndarray) -> float | None:
    """AUROC by average ranks, including ties, without a scikit-learn dependency."""
    values = np.asarray(scores, dtype=np.float64)
    pos = np.asarray(positive, dtype=bool)
    n_pos = int(pos.sum())
    n_neg = int((~pos).sum())
    if not n_pos or not n_neg:
        return None
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    rank_sum = float(ranks[pos].sum())
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def compute_open_set_metrics(
    rows: list[SlotRow],
    probs: np.ndarray,
    *,
    tau: float,
    seven_way: bool,
) -> dict[str, Any]:
    scores = _open_scores(probs)
    is_other = np.asarray([row.game == OTHER for row in rows], dtype=bool)
    is_game = ~is_other
    flagged = scores > tau
    y_true = np.asarray([row.label for row in rows], dtype=np.int64)
    pred = np.asarray(probs).argmax(axis=1)
    covered = is_game & ~flagged
    out: dict[str, Any] = {
        "tau": float(tau),
        "false_alarm_rate": float(np.mean(flagged[is_game])) if is_game.any() else None,
        "coverage": float(np.mean(~flagged[is_game])) if is_game.any() else None,
        "accuracy_on_covered": (
            float(np.mean(pred[covered] == y_true[covered])) if covered.any() else None
        ),
    }
    if is_other.any():
        out["other_detection_rate"] = float(np.mean(flagged[is_other]))
        out["auroc"] = _binary_auroc(scores, is_other)
        if seven_way:
            out["argmax_other_rate"] = float(np.mean(pred[is_other] == len(GAMES)))
    return out


def _lookalike_metrics(confusion: list[list[int]], labels: tuple[str, ...]) -> dict[str, Any]:
    i = labels.index(LOOKALIKE[0])
    j = labels.index(LOOKALIKE[1])
    row_i = sum(confusion[i])
    row_j = sum(confusion[j])
    rate_i_to_j = (confusion[i][j] / row_i) if row_i else None
    rate_j_to_i = (confusion[j][i] / row_j) if row_j else None
    # mean F1 of the pair from the confusion-derived per-class F1s
    def _f1_for(idx: int) -> float | None:
        tp = confusion[idx][idx]
        fp = sum(confusion[r][idx] for r in range(len(labels))) - tp
        fn = sum(confusion[idx]) - tp
        _, _, f1 = _precision_recall_f1(tp, fp, fn)
        return f1

    f1_i = _f1_for(i)
    f1_j = _f1_for(j)
    if f1_i is None and f1_j is None:
        mean_f1 = None
    elif f1_i is None:
        mean_f1 = f1_j
    elif f1_j is None:
        mean_f1 = f1_i
    else:
        mean_f1 = (f1_i + f1_j) / 2.0
    return {
        "pair": list(LOOKALIKE),
        f"{LOOKALIKE[0]}_to_{LOOKALIKE[1]}": rate_i_to_j,
        f"{LOOKALIKE[1]}_to_{LOOKALIKE[0]}": rate_j_to_i,
        "mean_f1": mean_f1,
    }


def _group_accuracy(
    rows: list[SlotRow],
    y_true: np.ndarray,
    y_pred: np.ndarray,
    key_fn: Callable[[SlotRow], str],
) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        buckets.setdefault(key_fn(row), []).append(idx)
    out: dict[str, dict[str, Any]] = {}
    for key, idxs in buckets.items():
        yt = y_true[idxs]
        yp = y_pred[idxs]
        metrics = compute_classification_metrics(yt, yp)
        out[key] = {
            "n": metrics["n"],
            "accuracy": metrics["accuracy"],
            "macro_f1": metrics["macro_f1"],
        }
    return out


def _by_tier(rows: list[SlotRow], y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    return _group_accuracy(rows, y_true, y_pred, lambda r: r.tier)


def _load_low_encoders(data_root: Path) -> dict[str, str]:
    path = Path(data_root) / "manifests" / "clips_index.csv"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("clip_key", "")
            enc = (row.get("low_encoder") or "").strip()
            out[key] = enc
    return out


def _encoder_for_row(row: SlotRow, encoders: dict[str, str]) -> str:
    if row.tier != "crf45":
        return ""
    enc = encoders.get(row.clip_key, "")
    if not enc:
        # quick mode (empty path_low) or missing: count as such
        if not row.path_low:
            return "(quick_mode)"
        return "(missing)"
    return enc


def _by_encoder(
    rows: list[SlotRow],
    y_true: np.ndarray,
    y_pred: np.ndarray,
    data_root: Path,
) -> dict[str, Any]:
    encoders = _load_low_encoders(data_root)
    crf_idxs = [i for i, r in enumerate(rows) if r.tier == "crf45"]
    overall: dict[str, dict[str, Any]] = {}
    by_game: dict[str, dict[str, dict[str, Any]]] = {}
    for i in crf_idxs:
        row = rows[i]
        enc = _encoder_for_row(row, encoders)
        overall.setdefault(enc, {"n": 0, "correct": 0})
        overall[enc]["n"] += 1
        overall[enc]["correct"] += int(y_true[i] == y_pred[i])
        by_game.setdefault(row.game, {}).setdefault(enc, {"n": 0, "correct": 0})
        by_game[row.game][enc]["n"] += 1
        by_game[row.game][enc]["correct"] += int(y_true[i] == y_pred[i])

    def _acc(block: dict[str, dict[str, int]]) -> dict[str, dict[str, Any]]:
        return {
            k: {
                "n": v["n"],
                "accuracy": (v["correct"] / v["n"]) if v["n"] else None,
            }
            for k, v in block.items()
        }

    return {
        "overall": _acc(overall),
        "by_game": {g: _acc(encs) for g, encs in by_game.items()},
    }


def _by_source(rows: list[SlotRow], y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    buckets: dict[str, list[int]] = {}
    kinds: dict[str, str] = {}
    for idx, row in enumerate(rows):
        buckets.setdefault(row.source, []).append(idx)
        kinds[row.source] = row.source_kind
    out: dict[str, dict[str, Any]] = {}
    for source, idxs in buckets.items():
        yt = y_true[idxs]
        yp = y_pred[idxs]
        acc = float((yt == yp).mean()) if idxs else 0.0
        out[source] = {
            "n": len(idxs),
            "accuracy": acc,
            "source_kind": kinds[source],
        }
    return out


def _by_clip(rows: list[SlotRow], y_true: np.ndarray, y_pred: np.ndarray) -> list[dict[str, Any]]:
    buckets: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        buckets.setdefault(row.clip_key, []).append(idx)
    items: list[dict[str, Any]] = []
    for clip_key, idxs in buckets.items():
        yt = y_true[idxs]
        yp = y_pred[idxs]
        acc = float((yt == yp).mean()) if idxs else 0.0
        items.append({"clip_key": clip_key, "n": len(idxs), "accuracy": acc})
    items.sort(key=lambda x: (x["accuracy"], -x["n"], x["clip_key"]))
    return items


def build_metrics(
    rows: list[SlotRow],
    probs: np.ndarray,
    *,
    run: dict[str, Any],
    split: str,
    split_dir: Path,
    data_root: Path,
    hash_changed: bool,
    tau: float | None = None,
) -> dict[str, Any]:
    probs = np.asarray(probs, dtype=np.float64)
    labels = tuple(run["labels"])
    if probs.ndim != 2 or probs.shape[0] != len(rows) or probs.shape[1] != len(labels):
        raise ValueError(
            f"predict_proba shape {probs.shape} != ({len(rows)}, {len(labels)})"
        )
    included = np.asarray([r.label < len(labels) for r in rows], dtype=bool)
    class_rows = [row for row, keep in zip(rows, included.tolist()) if keep]
    class_probs = probs[included]
    y_true = np.asarray([r.label for r in class_rows], dtype=np.int64)
    y_pred = class_probs.argmax(axis=1)
    base = compute_classification_metrics(y_true, y_pred, labels=labels)
    all_pred = probs.argmax(axis=1)
    if tau is None:
        game_mask = np.asarray([row.game in GAMES for row in rows], dtype=bool)
        tau = _threshold_at_false_alarm(_open_scores(probs)[game_mask])
    metrics: dict[str, Any] = {
        "n": base["n"],
        "accuracy": base["accuracy"],
        "macro_f1": base["macro_f1"],
        "per_class": base["per_class"],
        "confusion": base["confusion"],
        "zero_support_note": base["zero_support_note"],
        "lookalike": _lookalike_metrics(base["confusion"], labels),
        "by_tier": _by_tier(class_rows, y_true, y_pred),
        "by_encoder": _by_encoder(class_rows, y_true, y_pred, data_root),
        "by_source": _by_source(class_rows, y_true, y_pred),
        "by_clip": _by_clip(class_rows, y_true, y_pred),
        "six_game": compute_six_game_metrics(rows, all_pred),
        "open_set": compute_open_set_metrics(
            rows, probs, tau=tau, seven_way=labels == CLASSES,
        ),
        "provenance": {
            "run_id": run["run_id"],
            "model_type": run["model_type"],
            "split_id": run["split_id"],
            "split": split,
            # Hash of the split file actually scored; compare pairs runs on this.
            "split_hash": split_hashes(split_dir).get(split),
            "train_time_split_hash": dict(run["split_hashes"]).get(split),
            "hash_changed": hash_changed,
            "time": _utc_now(),
        },
    }
    return metrics


def write_predictions_csv(
    path: Path,
    rows: list[SlotRow],
    probs: np.ndarray,
    labels: tuple[str, ...],
) -> None:
    probs = np.asarray(probs, dtype=np.float64)
    y_pred = probs.argmax(axis=1)
    conf = probs.max(axis=1)
    columns = [
        "slot_id",
        "game",
        "label",
        "pred",
        "pred_game",
        "correct",
        "confidence",
        "open_score",
        *[f"p_{g}" for g in labels],
        "tier",
        "source",
        "clip_key",
        "session",
    ]
    out_rows: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        pred = int(y_pred[i])
        item: dict[str, Any] = {
            "slot_id": row.slot_id,
            "game": row.game,
            "label": row.label,
            "pred": pred,
            "pred_game": labels[pred],
            "correct": "true" if pred == row.label else "false",
            "confidence": float(conf[i]),
            "open_score": float(1.0 - np.max(probs[i, :len(GAMES)])),
            "tier": row.tier,
            "source": row.source,
            "clip_key": row.clip_key,
            "session": row.session,
        }
        for j, g in enumerate(labels):
            item[f"p_{g}"] = float(probs[i, j])
        out_rows.append(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(out_rows)


def _try_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError:
        print(
            "matplotlib not installed; skipping figures "
            "(metrics and CSV still written)",
            file=sys.stderr,
        )
        return None


def write_confusion_png(path: Path, confusion: list[list[int]], labels: tuple[str, ...] = LABELS) -> bool:
    plt = _try_matplotlib()
    if plt is None:
        return False
    mat = np.asarray(confusion, dtype=np.float64)
    row_sums = mat.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        norm = np.divide(mat, row_sums, out=np.zeros_like(mat), where=row_sums > 0)
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(norm, cmap="Blues", vmin=0.0, vmax=1.0)
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, str(int(mat[i, j])), ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return True


def write_examples_png(
    path: Path,
    rows: list[SlotRow],
    probs: np.ndarray,
    data_root: Path,
    *,
    examples: int = 8,
    labels: tuple[str, ...] = LABELS,
) -> bool:
    plt = _try_matplotlib()
    if plt is None:
        return False
    from game_frame_classifier.split_manifest import image_path, load_image_u8

    probs = np.asarray(probs, dtype=np.float64)
    y_pred = probs.argmax(axis=1)
    conf = probs.max(axis=1)
    consented = [
        i for i, r in enumerate(rows) if r.public_examples_ok
    ]
    correct = [i for i in consented if y_pred[i] == rows[i].label]
    wrong = [i for i in consented if y_pred[i] != rows[i].label]

    def _pick(idxs: list[int], *, favour_lookalike: bool) -> list[int]:
        if not idxs:
            return []
        if favour_lookalike:
            look = {
                labels.index(LOOKALIKE[0]),
                labels.index(LOOKALIKE[1]),
            }

            def sort_key(i: int) -> tuple:
                true_l = rows[i].label
                pred_l = int(y_pred[i])
                is_pair = true_l in look and pred_l in look and true_l != pred_l
                return (0 if is_pair else 1, -float(conf[i]))

            ordered = sorted(idxs, key=sort_key)
        else:
            ordered = sorted(idxs, key=lambda i: -float(conf[i]))
        return ordered[:examples]

    correct_pick = _pick(correct, favour_lookalike=False)
    wrong_pick = _pick(wrong, favour_lookalike=True)
    n_cols = max(len(correct_pick), len(wrong_pick), 1)
    fig, axes = plt.subplots(2, n_cols, figsize=(2.2 * n_cols, 5.0))
    if n_cols == 1:
        axes = np.asarray(axes).reshape(2, 1)

    def _draw(row_axes, picks: list[int], title: str) -> None:
        for col in range(n_cols):
            ax = row_axes[col]
            ax.axis("off")
            if col >= len(picks):
                continue
            i = picks[col]
            row = rows[i]
            img = load_image_u8(image_path(row, data_root, "assigned"))
            ax.imshow(img)
            ax.set_title(
                f"{row.game} → {labels[int(y_pred[i])]}\n{float(conf[i]):.2f}",
                fontsize=7,
            )
        # Axes are off, so a y-label would not show; label the row in axes coordinates.
        label = title if picks else f"{title}: none"
        row_axes[0].text(-0.08, 0.5, label, transform=row_axes[0].transAxes, rotation=90,
                         ha="right", va="center", fontsize=9)

    _draw(axes[0], correct_pick, "correct")
    _draw(axes[1], wrong_pick, "wrong")
    fig.suptitle("Highest-confidence correct / wrong (consent-filtered)", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return True


def run_tier_diagnostic(
    predictor: Predictor,
    rows: list[SlotRow],
    data_root: Path,
) -> dict[str, Any]:
    paired = [r for r in rows if r.path_full and r.path_low]
    skipped_quick = len(rows) - len(paired)
    if not paired:
        return {
            "n_paired": 0,
            "n_skipped_quick": skipped_quick,
            "full": None,
            "low": None,
            "accuracy_delta_full_minus_low": None,
            "flip_rate": None,
        }
    probs_full = np.asarray(
        predictor.predict_proba(paired, data_root, tier_mode="full"),
        dtype=np.float64,
    )
    probs_low = np.asarray(
        predictor.predict_proba(paired, data_root, tier_mode="low"),
        dtype=np.float64,
    )
    y_true = np.asarray([r.label for r in paired], dtype=np.int64)
    pred_full = probs_full.argmax(axis=1)
    pred_low = probs_low.argmax(axis=1)
    m_full = compute_classification_metrics(y_true, pred_full)
    m_low = compute_classification_metrics(y_true, pred_low)
    flip_rate = float((pred_full != pred_low).mean())
    return {
        "n_paired": len(paired),
        "n_skipped_quick": skipped_quick,
        "full": {"accuracy": m_full["accuracy"], "macro_f1": m_full["macro_f1"]},
        "low": {"accuracy": m_low["accuracy"], "macro_f1": m_low["macro_f1"]},
        "accuracy_delta_full_minus_low": m_full["accuracy"] - m_low["accuracy"],
        "flip_rate": flip_rate,
    }


def evaluate_run(
    run_dir: Path,
    split: str,
    *,
    data_root: Path | None = None,
    split_dir: Path | None = None,
    tier_diagnostic: bool = False,
    reason: str | None = None,
    examples: int = 8,
) -> Path:
    """Score one run on a split; write `<run>/eval/<split>/`. Return that folder."""
    run_dir = Path(run_dir)
    if split not in _ALLOWED_SPLITS:
        raise ValueError(f"unknown split name: {split!r}")
    run = _load_run_json(run_dir)
    _check_labels(run)
    resolved_split_dir = _resolve_split_dir(run, split_dir)
    if str(run["split_id"]) != resolved_split_dir.name:
        print(
            f"warning: run split_id {run['split_id']!r} != folder name "
            f"{resolved_split_dir.name!r}",
            file=sys.stderr,
        )
    root = Path(data_root) if data_root is not None else Path("data")
    _require_test_access(
        split,
        resolved_split_dir,
        reason=reason,
        run_dir=run_dir,
        data_root=root,
    )
    changed = _hash_changed(run, resolved_split_dir)
    if changed:
        print(
            "warning: split file hashes differ from run.json "
            "(data may have been added since training); recorded in metrics",
            file=sys.stderr,
        )
    allow_test = split in _TEST_SPLITS
    rows = load_split(resolved_split_dir, split, allow_test=allow_test)
    predictor = load_predictor(run_dir)
    labels = tuple(run["labels"])
    if tuple(predictor.labels) != labels:
        raise ValueError(
            f"predictor labels {predictor.labels} != run labels {labels}"
        )
    probs = np.asarray(
        predictor.predict_proba(rows, root, tier_mode="assigned"),
        dtype=np.float64,
    )
    out_dir = run_dir / "eval" / split
    out_dir.mkdir(parents=True, exist_ok=True)
    if split == "val":
        game_mask = np.asarray([row.game in GAMES for row in rows], dtype=bool)
        tau = _threshold_at_false_alarm(_open_scores(probs)[game_mask])
    else:
        threshold_path = run_dir / "eval" / "val" / "open_set.json"
        if not threshold_path.is_file():
            raise PermissionError(
                f"refusing {split!r}: score val first to choose the open-set threshold"
            )
        tau = float(json.loads(threshold_path.read_text(encoding="utf-8"))["tau"])
    write_predictions_csv(out_dir / "predictions.csv", rows, probs, labels)
    metrics = build_metrics(
        rows,
        probs,
        run=run,
        split=split,
        split_dir=resolved_split_dir,
        data_root=root,
        hash_changed=changed,
        tau=tau,
    )
    write_json(metrics, out_dir / "metrics.json")
    write_json(metrics["open_set"], out_dir / "open_set.json")
    write_confusion_png(out_dir / "confusion.png", metrics["confusion"], labels)
    write_examples_png(
        out_dir / "examples.png",
        rows,
        probs,
        root,
        examples=examples,
        labels=labels,
    )
    if tier_diagnostic:
        diag = run_tier_diagnostic(predictor, rows, root)
        write_json(diag, out_dir / "tier_diagnostic.json")
    return out_dir


def _read_prediction_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _six_macro_f1_arrays(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    f1s: list[float] = []
    game_rows = y_true < len(GAMES)
    yt, yp = y_true[game_rows], y_pred[game_rows]
    for label in range(len(GAMES)):
        if not np.any(yt == label):
            continue
        tp = int(np.sum((yt == label) & (yp == label)))
        fp = int(np.sum((yt != label) & (yp == label)))
        fn = int(np.sum((yt == label) & (yp != label)))
        _, _, f1 = _precision_recall_f1(tp, fp, fn)
        f1s.append(float(f1 or 0.0))
    return float(np.mean(f1s)) if f1s else None


def _bootstrap_comparison(
    pred_a: list[dict[str, str]],
    pred_b: list[dict[str, str]],
    tau_a: float,
    tau_b: float,
) -> dict[str, Any]:
    by_slot_b = {row["slot_id"]: row for row in pred_b}
    if set(by_slot_b) != {row["slot_id"] for row in pred_a}:
        raise ValueError("prediction rows differ between runs")
    ordered_b = [by_slot_b[row["slot_id"]] for row in pred_a]
    clips = np.asarray([row["clip_key"] for row in pred_a], dtype=object)
    y_true = np.asarray([int(row["label"]) for row in pred_a], dtype=np.int64)
    pred_a_values = np.asarray([int(row["pred"]) for row in pred_a], dtype=np.int64)
    pred_b_values = np.asarray([int(row["pred"]) for row in ordered_b], dtype=np.int64)
    score_a = np.asarray([float(row["open_score"]) for row in pred_a], dtype=np.float64)
    score_b = np.asarray([float(row["open_score"]) for row in ordered_b], dtype=np.float64)
    unique_clips = sorted(set(clips.tolist()))
    clip_indices = {clip: np.flatnonzero(clips == clip) for clip in unique_clips}

    def values(indices: np.ndarray) -> dict[str, float | None]:
        yt = y_true[indices]
        other = yt == len(GAMES)
        game = ~other
        return {
            "six_game_macro_f1_a": _six_macro_f1_arrays(yt, pred_a_values[indices]),
            "six_game_macro_f1_b": _six_macro_f1_arrays(yt, pred_b_values[indices]),
            "other_detection_rate_a": (
                float(np.mean(score_a[indices][other] > tau_a)) if other.any() else None
            ),
            "other_detection_rate_b": (
                float(np.mean(score_b[indices][other] > tau_b)) if other.any() else None
            ),
            "auroc_a": _binary_auroc(score_a[indices], other) if game.any() and other.any() else None,
            "auroc_b": _binary_auroc(score_b[indices], other) if game.any() and other.any() else None,
        }

    all_indices = np.arange(len(pred_a), dtype=np.int64)
    observed = values(all_indices)
    metric_pairs = {
        "six_game_macro_f1": ("six_game_macro_f1_a", "six_game_macro_f1_b"),
        "other_detection_rate": ("other_detection_rate_a", "other_detection_rate_b"),
        "auroc": ("auroc_a", "auroc_b"),
    }
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    samples: dict[str, list[float]] = {name: [] for name in metric_pairs}
    if unique_clips:
        for _ in range(BOOTSTRAP_RESAMPLES):
            selected = rng.choice(unique_clips, size=len(unique_clips), replace=True)
            indices = np.concatenate([clip_indices[str(clip)] for clip in selected])
            result = values(indices)
            for name, (a_key, b_key) in metric_pairs.items():
                a, b = result[a_key], result[b_key]
                if a is not None and b is not None:
                    samples[name].append(float(b) - float(a))
    out: dict[str, Any] = {
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
        "unit": "clip_key",
        "confidence": 0.95,
        "metrics": {},
    }
    for name, (a_key, b_key) in metric_pairs.items():
        a, b = observed[a_key], observed[b_key]
        diffs = samples[name]
        out["metrics"][name] = {
            "run_a": a,
            "run_b": b,
            "difference_b_minus_a": None if a is None or b is None else float(b) - float(a),
            "ci_low": float(np.percentile(diffs, 2.5)) if diffs else None,
            "ci_high": float(np.percentile(diffs, 97.5)) if diffs else None,
            "valid_resamples": len(diffs),
        }
    return out


def compare_runs(
    run_a: Path,
    run_b: Path,
    split: str,
    *,
    data_root: Path | None = None,
) -> Path:
    """Write side-by-side comparison from two runs' existing metrics.json."""
    run_a = Path(run_a)
    run_b = Path(run_b)
    meta_a = json.loads((run_a / "eval" / split / "metrics.json").read_text(encoding="utf-8"))
    meta_b = json.loads((run_b / "eval" / split / "metrics.json").read_text(encoding="utf-8"))
    prov_a = meta_a["provenance"]
    prov_b = meta_b["provenance"]
    if prov_a["split_id"] != prov_b["split_id"]:
        raise ValueError(
            f"split_id mismatch: {prov_a['split_id']!r} vs {prov_b['split_id']!r}"
        )
    if prov_a.get("split_hash") != prov_b.get("split_hash"):
        raise ValueError(
            "split hash mismatch between runs; refusing comparison "
            f"({prov_a.get('split_hash')} vs {prov_b.get('split_hash')})"
        )
    id_a = str(prov_a["run_id"])
    id_b = str(prov_b["run_id"])
    root = Path(data_root) if data_root is not None else Path("data")
    out_dir = root / "runs" / "compare" / f"{id_a}__{id_b}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows_out: list[dict[str, Any]] = []

    def add(metric: str, a: Any, b: Any) -> None:
        try:
            diff: Any = (None if a is None or b is None else float(b) - float(a))
        except (TypeError, ValueError):
            diff = None
        rows_out.append({"metric": metric, "run_a": a, "run_b": b, "diff_b_minus_a": diff})

    add("accuracy", meta_a["accuracy"], meta_b["accuracy"])
    add("macro_f1", meta_a["macro_f1"], meta_b["macro_f1"])
    for game in LABELS:
        fa = meta_a["per_class"].get(game, {}).get("f1")
        fb = meta_b["per_class"].get(game, {}).get("f1")
        add(f"f1_{game}", fa, fb)
    for key in (
        f"{LOOKALIKE[0]}_to_{LOOKALIKE[1]}",
        f"{LOOKALIKE[1]}_to_{LOOKALIKE[0]}",
        "mean_f1",
    ):
        add(f"lookalike_{key}", meta_a["lookalike"][key], meta_b["lookalike"][key])
    add("six_game_macro_f1", meta_a["six_game"]["macro_f1"], meta_b["six_game"]["macro_f1"])
    for key in ("false_alarm_rate", "other_detection_rate", "auroc", "coverage", "accuracy_on_covered"):
        add(f"open_set_{key}", meta_a["open_set"].get(key), meta_b["open_set"].get(key))

    bootstrap = _bootstrap_comparison(
        _read_prediction_rows(run_a / "eval" / split / "predictions.csv"),
        _read_prediction_rows(run_b / "eval" / split / "predictions.csv"),
        float(meta_a["open_set"]["tau"]),
        float(meta_b["open_set"]["tau"]),
    )
    write_json(bootstrap, out_dir / f"{split}.json")

    csv_path = out_dir / f"{split}.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["metric", "run_a", "run_b", "diff_b_minus_a"]
        )
        writer.writeheader()
        writer.writerows(rows_out)

    md_lines = [
        f"# Compare `{id_a}` vs `{id_b}` on `{split}`",
        "",
        f"- split_id: `{prov_a['split_id']}`",
        f"- split_hash: `{prov_a.get('split_hash')}`",
        "",
        "| metric | run_a | run_b | diff (b−a) |",
        "|---|---:|---:|---:|",
    ]
    for row in rows_out:
        md_lines.append(
            f"| {row['metric']} | {row['run_a']} | {row['run_b']} | {row['diff_b_minus_a']} |"
        )
    md_lines.extend(["", "## Paired bootstrap (95% CI over videos)", ""])
    for name, result in bootstrap["metrics"].items():
        md_lines.append(
            f"- {name}: {result['difference_b_minus_a']} "
            f"[{result['ci_low']}, {result['ci_high']}]"
        )
    (out_dir / f"{split}.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return out_dir


def write_data_report(split_dir: Path, *, data_root: Path | None = None) -> Path:
    """Dataset figures under `<split_dir>/report/` (no model)."""
    split_dir = Path(split_dir)
    report_dir = split_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    root = Path(data_root) if data_root is not None else Path("data")
    counts_path = split_dir / "counts.csv"
    if not counts_path.is_file():
        raise FileNotFoundError(counts_path)

    plt = _try_matplotlib()
    if plt is not None:
        # class_counts.png: slots per game, stacked by split
        by_game: dict[str, dict[str, int]] = {}
        splits_seen: list[str] = []
        with open(counts_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                game = row["game"]
                split = row["split"]
                if game == "ALL" or split == "ALL":
                    continue
                if split not in splits_seen:
                    splits_seen.append(split)
                by_game.setdefault(game, {})
                by_game[game][split] = int(float(row["slots"]))
        games = [g for g in LABELS if g in by_game] or sorted(by_game)
        fig, ax = plt.subplots(figsize=(9, 5))
        x = np.arange(len(games))
        bottom = np.zeros(len(games))
        for split in splits_seen:
            heights = np.asarray([by_game.get(g, {}).get(split, 0) for g in games], dtype=float)
            ax.bar(x, heights, bottom=bottom, label=split)
            bottom = bottom + heights
        ax.set_xticks(x)
        ax.set_xticklabels(games, rotation=30, ha="right")
        ax.set_ylabel("slots")
        ax.set_title("Slots per game by split")
        ax.legend()
        fig.tight_layout()
        fig.savefig(report_dir / "class_counts.png", dpi=200)
        plt.close(fig)

        # example_frames.png: a few full frames per game from train, consent-filtered
        train_csv = split_dir / "train.csv"
        if train_csv.is_file():
            rows = load_split(split_dir, "train", allow_test=False)
            from game_frame_classifier.split_manifest import image_path, load_image_u8

            per_game: dict[str, list[SlotRow]] = {g: [] for g in LABELS}
            for row in rows:
                if (
                    row.public_examples_ok
                    and row.tier == "full"
                    and len(per_game[row.game]) < 3
                ):
                    per_game[row.game].append(row)
            n_games = len(LABELS)
            fig, axes = plt.subplots(n_games, 3, figsize=(6, 2 * n_games))
            for gi, game in enumerate(LABELS):
                for ci in range(3):
                    ax = axes[gi, ci]
                    ax.axis("off")
                    if ci < len(per_game[game]):
                        row = per_game[game][ci]
                        img = load_image_u8(image_path(row, root, "assigned"))
                        ax.imshow(img)
                        if ci == 0:
                            ax.set_ylabel(game, fontsize=8)
            fig.suptitle("Example full frames (train, consent-filtered)", fontsize=10)
            fig.tight_layout()
            fig.savefig(report_dir / "example_frames.png", dpi=200)
            plt.close(fig)
        else:
            print(f"warning: {train_csv} missing; skipped example_frames.png", file=sys.stderr)
    return report_dir


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gfc-evaluate", description="Evaluate a trained run")
    p.add_argument("--run", type=Path, help="Run folder with run.json")
    p.add_argument(
        "--split",
        choices=sorted(_ALLOWED_SPLITS),
        help="Split to score",
    )
    p.add_argument("--tier-diagnostic", action="store_true")
    p.add_argument("--reason", default=None, help="Required for test splits")
    p.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        type=Path,
        help="Two run folders to compare on --split",
    )
    p.add_argument(
        "--data-report",
        action="store_true",
        help="Dataset figures for --split-dir (no model)",
    )
    p.add_argument("--examples", type=int, default=8)
    p.add_argument("--data-root", type=Path, default=None)
    p.add_argument("--split-dir", type=Path, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.data_report:
            if args.split_dir is None:
                raise SystemExit("--data-report requires --split-dir")
            out = write_data_report(args.split_dir, data_root=args.data_root)
            print(f"data report written to {out}")
            return 0
        if args.compare is not None:
            if args.split is None:
                raise SystemExit("--compare requires --split")
            out = compare_runs(
                args.compare[0],
                args.compare[1],
                args.split,
                data_root=args.data_root,
            )
            print(f"comparison written to {out}")
            return 0
        if args.run is None or args.split is None:
            raise SystemExit("--run and --split are required (unless --compare / --data-report)")
        out = evaluate_run(
            args.run,
            args.split,
            data_root=args.data_root,
            split_dir=args.split_dir,
            tier_diagnostic=args.tier_diagnostic,
            reason=args.reason,
            examples=args.examples,
        )
        print(f"evaluation written to {out}")
        return 0
    except (PermissionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
