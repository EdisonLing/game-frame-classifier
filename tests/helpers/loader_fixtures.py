"""Synthetic split CSVs and 256×144 JPEGs for dataset-loader tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image

from game_frame_classifier.sourcing.labels import CLASSES, GAMES, OTHER
from game_frame_classifier.split_manifest import SPLIT_COLUMNS

FRAME_W = 256
FRAME_H = 144


def write_frame_jpeg(
    path: Path,
    *,
    colour: tuple[int, int, int] = (40, 80, 120),
    asymmetric: bool = False,
    size: tuple[int, int] = (FRAME_W, FRAME_H),
    mode: str = "RGB",
) -> Path:
    """Write a JPEG under path; size is (width, height)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "L":
        im = Image.new("L", size, colour[0] if isinstance(colour, tuple) else colour)
    else:
        im = Image.new("RGB", size, colour)
        if asymmetric:
            # Inset colour blocks so zoom-out black fill does not erase the cue.
            px = im.load()
            w, h = size
            for y in range(h):
                for x in range(40, 80):
                    px[x, y] = (255, 0, 0)
                for x in range(w - 80, w - 40):
                    px[x, y] = (0, 0, 255)
    im.save(path, format="JPEG", quality=95)
    return path


def _rel(game: str, source: str, clip_key: str, tier: str, name: str, other_name: str = "") -> str:
    if game == OTHER:
        return f"frames/_other/{other_name or 'desktop'}/{source}/{clip_key}/{tier}/{name}"
    return f"frames/{game}/{source}/{clip_key}/{tier}/{name}"


def make_slot_dict(
    *,
    game: str,
    label: int | None = None,
    source: str = "src_a",
    source_kind: str = "personal",
    session: str = "src_a:Valorant:s001",
    split: str = "train",
    tier: str = "full",
    clip_key: str = "c0123456789ab",
    bucket: int = 0,
    target_time_s: float = 0.0,
    public_examples_ok: bool = True,
    slot_suffix: str | None = None,
    other_name: str = "",
) -> dict:
    """One split-CSV row dict; paths relative to data root with forward slashes."""
    if label is None:
        label = CLASSES.index(game)
    slot_id = f"{clip_key}:b{bucket:06d}"
    if slot_suffix:
        slot_id = f"{slot_id}:{slot_suffix}"
    name = f"b{bucket:06d}.jpg"
    path_full = _rel(game, source, clip_key, "full", name, other_name)
    path_low = _rel(game, source, clip_key, "crf45", name, other_name)
    path = path_low if tier == "crf45" else path_full
    return {
        "slot_id": slot_id,
        "clip_key": clip_key,
        "game": game,
        "label": label,
        "source": source,
        "source_kind": source_kind,
        "session": session if ":" in session else f"{source}:{game}:{session}",
        "split": split,
        "tier": tier,
        "path": path,
        "path_full": path_full,
        "path_low": path_low,
        "bucket": bucket,
        "target_time_s": target_time_s,
        "public_examples_ok": public_examples_ok,
        "other_name": other_name,
    }


def write_split_csv(path: Path, rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(SPLIT_COLUMNS))
        writer.writeheader()
        for row in rows:
            out = dict(row)
            ok = out["public_examples_ok"]
            out["public_examples_ok"] = "true" if ok else "false"
            writer.writerow(out)
    return path


def write_summary(split_dir: Path, split_hashes: dict[str, str] | None = None) -> Path:
    split_dir = Path(split_dir)
    split_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "split_id": split_dir.name,
        "frozen": False,
        "split_hashes": split_hashes
        or {
            "train": "a" * 64,
            "val": "b" * 64,
            "test_session": "c" * 64,
            "test_source": "d" * 64,
        },
    }
    path = split_dir / "summary.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def materialise_frames(data_root: Path, rows: list[dict], *, asymmetric: bool = False) -> None:
    """Create full and low JPEGs for every row under data_root."""
    for row in rows:
        colour = (
            20 + (row["label"] * 35) % 200,
            40 + (row["bucket"] * 17) % 180,
            60 + (row["label"] * 11) % 160,
        )
        for rel in (row["path_full"], row["path_low"]):
            write_frame_jpeg(
                data_root / Path(*rel.split("/")),
                colour=colour,
                asymmetric=asymmetric,
            )


def build_split_fixture(
    root: Path,
    *,
    n_per_game: int = 1,
    splits: tuple[str, ...] = ("train", "val"),
    asymmetric: bool = False,
    include_other: bool = False,
) -> tuple[Path, Path]:
    """
    Create data_root and splits/<id>/ with CSVs, summary.json and JPEGs.

    Returns (data_root, split_dir).
    """
    data_root = Path(root) / "data"
    split_dir = data_root / "manifests" / "splits" / "v1"
    split_dir.mkdir(parents=True, exist_ok=True)

    by_split: dict[str, list[dict]] = {name: [] for name in splits}
    bucket = 0
    for split in splits:
        labels = CLASSES if include_other else GAMES
        for game_i, game in enumerate(labels):
            for j in range(n_per_game):
                tier = "full" if (bucket % 2) == 0 else "crf45"
                row = make_slot_dict(
                    game=game,
                    label=game_i,
                    source="src_a",
                    session=f"src_a:{game}:s001",
                    split=split,
                    tier=tier,
                    clip_key=f"c{game_i:012x}",
                    bucket=bucket,
                    target_time_s=float(bucket),
                    other_name="desktop" if game == OTHER else "",
                )
                by_split[split].append(row)
                bucket += 1

    all_rows = [r for rows in by_split.values() for r in rows]
    materialise_frames(data_root, all_rows, asymmetric=asymmetric)
    for name, rows in by_split.items():
        write_split_csv(split_dir / f"{name}.csv", rows)
    write_summary(split_dir)
    return data_root, split_dir
