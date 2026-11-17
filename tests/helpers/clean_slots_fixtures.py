"""Synthetic derived-tree fixtures for slot-mode frame cleaner tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image, ImageDraw, ImageFilter

SIZE = (256, 144)


def solid_rgb(color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", SIZE, color)


def sharp_pattern(
    *,
    bg: tuple[int, int, int] = (20, 20, 40),
    line_a: tuple[int, int, int] = (240, 240, 240),
    line_b: tuple[int, int, int] = (200, 40, 40),
    step: int = 8,
) -> Image.Image:
    im = Image.new("RGB", SIZE, bg)
    draw = ImageDraw.Draw(im)
    for x in range(0, SIZE[0], step):
        draw.line([(x, 0), (x, SIZE[1])], fill=line_a, width=2)
    for y in range(0, SIZE[1], step * 2):
        draw.line([(0, y), (SIZE[0], y)], fill=line_b, width=2)
    return im


def blurry_gradient() -> Image.Image:
    im = Image.new("RGB", SIZE)
    pixels = im.load()
    assert pixels is not None
    for y in range(SIZE[1]):
        for x in range(SIZE[0]):
            v = int(40 + 80 * (x / max(SIZE[0] - 1, 1)))
            pixels[x, y] = (v, v, v)
    return im.filter(ImageFilter.GaussianBlur(radius=8))


def save_jpg(path: Path, image: Image.Image) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95)
    return path


def slot_paths(
    data_root: Path,
    *,
    game: str,
    source: str,
    clip_key: str,
    bucket: int,
    low_tier: str = "crf45",
) -> tuple[Path, Path, str, str]:
    """Return (full_abs, low_abs, path_full_rel, path_low_rel)."""
    b = f"{bucket:06d}"
    rel_full = f"frames/{game}/{source}/{clip_key}/full/{clip_key}_full_b{b}.jpg"
    rel_low = (
        f"frames/{game}/{source}/{clip_key}/{low_tier}/"
        f"{clip_key}_{low_tier}_b{b}.jpg"
    )
    return data_root / rel_full, data_root / rel_low, rel_full, rel_low


def write_slot_images(
    data_root: Path,
    *,
    game: str,
    source: str,
    clip_key: str,
    bucket: int,
    full: Image.Image | Callable[[], Image.Image],
    low: Image.Image | Callable[[], Image.Image] | None = None,
    low_tier: str = "crf45",
) -> dict[str, str]:
    """Write both tier JPEGs; return a slots.csv row dict (paths relative)."""
    full_im = full() if callable(full) else full
    low_im = (low() if callable(low) else low) if low is not None else full_im.copy()
    full_abs, low_abs, rel_full, rel_low = slot_paths(
        data_root,
        game=game,
        source=source,
        clip_key=clip_key,
        bucket=bucket,
        low_tier=low_tier,
    )
    save_jpg(full_abs, full_im)
    save_jpg(low_abs, low_im)
    return {
        "slot_id": f"{clip_key}:b{bucket:06d}",
        "clip_key": clip_key,
        "game": game,
        "source": source,
        "bucket": str(bucket),
        "target_time_s": f"{bucket * 5.0:.1f}",
        "path_full": rel_full,
        "path_low": rel_low,
    }


def write_clips_index(path: Path, rows: Sequence[dict[str, str]]) -> Path:
    fieldnames = [
        "clip_key",
        "clip_sha256",
        "game",
        "source",
        "source_kind",
        "origin",
        "public_examples_ok",
        "recorded_start_utc",
        "recorded_start_source",
        "duration_s",
        "native_width",
        "native_height",
        "padded",
        "hdr",
        "vfr",
        "video_codec",
        "encoder_tag",
        "low_tier",
        "slots",
        "derive_id",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            full = {k: row.get(k, "") for k in fieldnames}
            writer.writerow(full)
    with path.with_suffix(".json").open("w", encoding="utf-8") as f:
        json.dump([{k: row.get(k, "") for k in fieldnames} for row in rows], f, indent=2)
    return path


def write_slots_csv(path: Path, rows: Sequence[dict[str, str]]) -> Path:
    fieldnames = [
        "slot_id",
        "clip_key",
        "game",
        "source",
        "bucket",
        "target_time_s",
        "path_full",
        "path_low",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fieldnames})
    with path.with_suffix(".json").open("w", encoding="utf-8") as f:
        json.dump([dict(row) for row in rows], f, indent=2)
    return path


def write_quarantine(path: Path, rows: Sequence[dict[str, str]]) -> Path:
    fieldnames = ["slot_id", "reason", "note"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path


def clip_index_row(
    *,
    clip_key: str,
    game: str,
    source: str,
    recorded_start_utc: str = "",
    slots: int = 1,
    low_tier: str = "crf45",
) -> dict[str, str]:
    kind = (
        "contributor"
        if source.startswith("contributor_")
        else "public"
        if source.startswith("public_")
        else "personal"
    )
    return {
        "clip_key": clip_key,
        "clip_sha256": clip_key[1:] + "0" * max(0, 64 - (len(clip_key) - 1)),
        "game": game,
        "source": source,
        "source_kind": kind,
        "origin": "test",
        "public_examples_ok": "true",
        "recorded_start_utc": recorded_start_utc,
        "recorded_start_source": "test",
        "duration_s": "60.0",
        "native_width": "1920",
        "native_height": "1080",
        "padded": "false",
        "hdr": "false",
        "vfr": "false",
        "video_codec": "h264",
        "encoder_tag": "",
        "low_tier": low_tier,
        "slots": str(slots),
        "derive_id": "pad16x9_bicubic_256x144_q2",
    }
