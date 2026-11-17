"""Folders the Frame Export Kit may write to.

Every write path goes through ensure_inside_home. The one exception is the finished zip
when the user passes --output: it goes into that existing folder and nothing else does.
"""

from __future__ import annotations

from pathlib import Path

from game_frame_classifier.sourcing.ffbin import pack_root


class UnsafePathError(RuntimeError):
    """A write was about to happen outside the tool folder."""


def app_home() -> Path:
    """The extracted tool folder (or the repo root when run from a checkout)."""
    return pack_root()


def config_dir() -> Path:
    return app_home() / "config"


def output_dir() -> Path:
    return app_home() / "output"


def ensure_inside_home(path: Path) -> Path:
    """Resolved path (junctions and symlinks followed) if it is inside the tool folder."""
    home = app_home().resolve()
    target = Path(path).resolve()
    if target != home and home not in target.parents:
        raise UnsafePathError(f"refusing to write outside the tool folder: {target.name}")
    return target
