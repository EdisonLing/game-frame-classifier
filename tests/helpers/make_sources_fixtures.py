"""Shared builders for gfc-make-sources unit and system tests."""

from __future__ import annotations

import json
from pathlib import Path

from tests.helpers.ffmpeg_fixtures import make_testsrc_video, requires_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "config" / "recipe.json"


def data_tree(tmp_path: Path, *, game: str = "Valorant", source: str = "tester") -> tuple[Path, Path]:
    """Return (data_root, source_dir) with raw/<game>/<source>/ ready."""
    data_root = tmp_path / "data"
    source_dir = data_root / "raw" / game / source
    source_dir.mkdir(parents=True)
    return data_root, source_dir


def seed_index(fs_root: Path, entries: dict) -> Path:
    path = fs_root / "_index" / "by_sha256.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return path


def make_raw_clip(
    source_dir: Path,
    name: str,
    *,
    duration_s: float = 12.0,
    width: int = 320,
    height: int = 180,
    color: str | None = None,
) -> Path:
    """Synthetic CFR clip under a raw source folder (unique title via file name)."""
    path = source_dir / name
    if color is not None:
        from tests.helpers.ffmpeg_fixtures import make_color_video

        return make_color_video(
            path, duration_s=duration_s, width=width, height=height, color=color,
        )
    return make_testsrc_video(path, duration_s=duration_s, width=width, height=height)


__all__ = [
    "RECIPE",
    "ROOT",
    "data_tree",
    "make_raw_clip",
    "requires_ffmpeg",
    "seed_index",
]
