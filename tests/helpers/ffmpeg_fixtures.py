"""Deterministic synthetic videos for system tests (no committed binaries)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


requires_ffmpeg = pytest.mark.skipif(
    not ffmpeg_available(),
    reason="ffmpeg/ffprobe not on PATH",
)


def trim_video_copy(
    src: Path,
    dst: Path,
    *,
    duration_s: float,
) -> Path:
    """
    Fast local smoke helper: stream-copy the first ``duration_s`` seconds.

    Keeps personal-clip tests scalable when the dropped file is hundreds of MB.
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg/ffprobe required to trim fixtures")
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-t",
        f"{duration_s:g}",
        "-i",
        str(src),
        "-c",
        "copy",
        str(dst),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return dst


def make_color_video(
    path: Path,
    *,
    duration_s: float = 15.0,
    width: int = 640,
    height: int = 360,
    fps: int = 30,
    color: str = "red",
) -> Path:
    """
    Create a constant-color CFR video with ffmpeg lavfi.

    Scalable: tests generate fixtures in tmp_path; nothing large is committed.
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg/ffprobe required to build fixtures")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={width}x{height}:r={fps}",
        "-t",
        f"{duration_s:g}",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return path
