"""Split-manifest rows, image paths and uint8 decode for training.

Reads `data/manifests/splits/<split_id>/` CSVs and JPEG frames under the data
root. Depends on NumPy and Pillow only. Spec: `docs/roadmap/tools/dataset-loader.md`.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from game_frame_classifier.sourcing.labels import GAMES

LABELS: tuple[str, ...] = GAMES

_TEST_SPLITS = frozenset({"test_session", "test_source"})
_ALLOWED_SPLITS = frozenset({"train", "val", "test_session", "test_source"})
_TIER_MODES = frozenset({"assigned", "full", "low"})

SPLIT_COLUMNS = (
    "slot_id",
    "clip_key",
    "game",
    "label",
    "source",
    "source_kind",
    "session",
    "split",
    "tier",
    "path",
    "path_full",
    "path_low",
    "bucket",
    "target_time_s",
    "public_examples_ok",
)


@dataclass(frozen=True)
class SlotRow:
    """One used slot from a split CSV."""

    slot_id: str
    clip_key: str
    game: str
    label: int
    source: str
    source_kind: str
    session: str
    split: str
    tier: str
    path: str
    path_full: str
    path_low: str
    bucket: int
    target_time_s: float
    public_examples_ok: bool


def _parse_bool(value: str) -> bool:
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no", ""):
        return False
    raise ValueError(f"invalid boolean: {value!r}")


def _row_from_csv(raw: dict[str, str]) -> SlotRow:
    game = raw["game"]
    label = int(raw["label"])
    expected = LABELS.index(game)
    if label != expected:
        raise ValueError(
            f"label/game mismatch for {raw.get('slot_id', '?')}: "
            f"game={game!r} label={label} expected={expected}"
        )
    return SlotRow(
        slot_id=raw["slot_id"],
        clip_key=raw["clip_key"],
        game=game,
        label=label,
        source=raw["source"],
        source_kind=raw["source_kind"],
        session=raw["session"],
        split=raw["split"],
        tier=raw["tier"],
        path=raw["path"],
        path_full=raw["path_full"],
        path_low=raw["path_low"],
        bucket=int(raw["bucket"]),
        target_time_s=float(raw["target_time_s"]),
        public_examples_ok=_parse_bool(raw["public_examples_ok"]),
    )


def load_split(split_dir: Path, name: str, *, allow_test: bool = False) -> list[SlotRow]:
    """Load one split CSV; refuse test splits unless allow_test=True."""
    if name not in _ALLOWED_SPLITS:
        raise ValueError(f"unknown split name: {name!r}")
    if name in _TEST_SPLITS and not allow_test:
        raise PermissionError(
            f"refusing to load {name!r} without allow_test=True (D13)"
        )
    path = Path(split_dir) / f"{name}.csv"
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in SPLIT_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")
        return [_row_from_csv(row) for row in reader]


def split_hashes(split_dir: Path) -> dict[str, str]:
    """Return SHA-256 per split file from summary.json."""
    summary_path = Path(split_dir) / "summary.json"
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    hashes = data.get("split_hashes")
    if not isinstance(hashes, dict):
        raise ValueError(f"{summary_path}: missing split_hashes object")
    return {str(k): str(v) for k, v in hashes.items()}


def image_path(row: SlotRow, data_root: Path, tier_mode: str = "assigned") -> Path:
    """Resolve the JPEG path for a row under data_root."""
    if tier_mode not in _TIER_MODES:
        raise ValueError(f"unknown tier_mode: {tier_mode!r}")
    if tier_mode == "assigned":
        rel = row.path
    elif tier_mode == "full":
        rel = row.path_full
    else:
        rel = row.path_low
    return Path(data_root) / Path(*rel.split("/"))


def load_image_u8(path: Path) -> np.ndarray:
    """Decode JPEG to RGB uint8 (144, 256, 3); never resize."""
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        width, height = rgb.size
        if width != 256 or height != 144:
            raise ValueError(
                f"expected 256x144, got {width}x{height} for {path}"
            )
        return np.asarray(rgb, dtype=np.uint8)


def class_weights(rows: list[SlotRow]) -> np.ndarray:
    """Balanced weights n / (k * count_c) over LABELS; 0 when count_c is 0."""
    k = len(LABELS)
    counts = np.zeros(k, dtype=np.float64)
    for row in rows:
        counts[row.label] += 1.0
    n = float(len(rows))
    weights = np.zeros(k, dtype=np.float64)
    for c in range(k):
        if counts[c] > 0:
            weights[c] = n / (k * counts[c])
    return weights
