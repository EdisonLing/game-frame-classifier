"""Deterministic synthetic videos for system tests (no committed binaries)."""

from __future__ import annotations

import functools
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


requires_ffmpeg = pytest.mark.skipif(
    not ffmpeg_available(),
    reason="ffmpeg/ffprobe not on PATH",
)


@functools.lru_cache(maxsize=1)
def gpu_encoder_available() -> bool:
    """True when the D3D12 GPU encoder self-test passes on this machine."""
    if not ffmpeg_available():
        return False
    from game_frame_classifier.sourcing.ffbin import find_tools
    from game_frame_classifier.sourcing.gpu import detect_gpu

    with tempfile.TemporaryDirectory() as tmp:
        return detect_gpu(find_tools(), Path(tmp) / "probe").available


requires_gpu = pytest.mark.skipif(
    not gpu_encoder_available(),
    reason="no working D3D12 GPU encoder on this machine",
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


def _run_ffmpeg(args: list[str]) -> None:
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg/ffprobe required to build fixtures")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def encoder_available(name: str) -> bool:
    if not ffmpeg_available():
        return False
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True
    ).stdout
    return any(line.split()[1:2] == [name] for line in out.splitlines())


def make_testsrc_video(
    path: Path,
    *,
    duration_s: float = 12.0,
    width: int = 640,
    height: int = 360,
    fps: int = 30,
    pix_fmt: str = "yuv420p",
    codec_args: tuple[str, ...] = (),
) -> Path:
    """Moving test pattern (testsrc2), so every sampled frame differs.
    testsrc2 rounds its size down to even numbers, so odd sizes are scaled up afterwards.
    The file name is written as the title tag, so two clips made with the same settings
    still differ in bytes (the Frame Export Kit skips byte-identical clips as duplicates).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    src_w, src_h = width - width % 2, height - height % 2
    scale = ["-vf", f"scale={width}:{height}:flags=neighbor"] if (src_w, src_h) != (width, height) else []
    _run_ffmpeg([
        "-f", "lavfi", "-i", f"testsrc2=s={src_w}x{src_h}:r={fps}:d={duration_s:g}",
        *scale, "-pix_fmt", pix_fmt, "-metadata", f"title={path.name}", *codec_args, str(path),
    ])
    return path


def make_vfr_offset_video(path: Path) -> Path:
    """60 fps source with every 7th frame dropped, a 9.2-10.9 s gap and a 2.74 s start offset."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=s=640x360:r=60:d=23",
        "-vf", "select='not(between(t\\,9.2\\,10.9))*not(eq(mod(n\\,7)\\,3))',setpts=PTS+1.37/TB",
        "-fps_mode", "vfr", "-output_ts_offset", "1.37", "-pix_fmt", "yuv420p", str(path),
    ])
    return path


def make_hdr_pq_video(path: Path) -> Path:
    """6 s 10-bit HEVC tagged BT.2020 / PQ (needs libx265)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-vf", "format=yuv420p10le",
        "-c:v", "libx265", "-preset", "ultrafast",
        "-x265-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:log-level=error",
        "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc", str(path),
    ])
    return path


def make_attached_pic_video(path: Path, work_dir: Path) -> Path:
    """6 s 640x360 clip plus a larger 1280x720 cover-art stream."""
    plain = make_testsrc_video(Path(work_dir) / "plain_for_cover.mp4", duration_s=6)
    cover = Path(work_dir) / "cover.jpg"
    _run_ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=1280x720", "-frames:v", "1", str(cover)])
    _run_ffmpeg([
        "-i", str(plain), "-i", str(cover), "-map", "0", "-map", "1", "-c", "copy",
        "-disposition:v:1", "attached_pic", str(path),
    ])
    return Path(path)
