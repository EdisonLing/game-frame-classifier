"""Pad to 16:9 when needed, then scale to the train size (D27, Frame Export Kit spec §5.7)."""

from __future__ import annotations

import shutil
from pathlib import Path

from .ffbin import FFTools, ToolError, run_capture
from .hashing import jpeg_size
from .recipe import Recipe


def pad_dims(width: int, height: int, tolerance: float) -> tuple[int, int] | None:
    """Even padded size that makes the image 16:9, or None when already within tolerance."""
    target = 16 / 9
    if abs(width / height - target) <= tolerance * target:
        return None
    if width / height < target:
        return -(-height * 16 // 18) * 2, height
    return width, -(-width * 9 // 32) * 2


def derive_filter(width: int, height: int, recipe: Recipe) -> str:
    out_w, out_h = recipe.compact_size
    parts = []
    pad = pad_dims(width, height, recipe.aspect_tolerance)
    if pad:
        pad_w, pad_h = pad
        parts.append(f"pad={pad_w}:{pad_h}:{(pad_w - width) // 2}:{(pad_h - height) // 2}:black")
    parts.append(f"scale={out_w}:{out_h}:flags={recipe.scale_flags}")
    return ",".join(parts)


def derive_dir(tools: FFTools, src_dir: Path, dst_dir: Path, recipe: Recipe) -> int:
    """Derive every %06d.jpg in src_dir into dst_dir with the same names; returns the count."""
    files = sorted(src_dir.glob("*.jpg"))
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True)
    if not files:
        return 0
    q = str(recipe.jpeg_qscale)
    sizes = {jpeg_size(f) for f in files}
    sequential = [f.name for f in files] == [f"{k:06d}.jpg" for k in range(len(files))]
    if len(sizes) == 1 and sequential:
        width, height = next(iter(sizes))
        proc = run_capture(
            [tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
             "-protocol_whitelist", "file", "-f", "image2", "-start_number", "0",
             "-i", src_dir / "%06d.jpg", "-vf", derive_filter(width, height, recipe),
             "-fps_mode", "passthrough", "-c:v", "mjpeg", "-q:v", q,
             "-start_number", "0", "-f", "image2", dst_dir / "%06d.jpg"],
            timeout=3600,
        )
        if proc.returncode == 0 and len(list(dst_dir.glob("*.jpg"))) == len(files):
            return len(files)
        for leftover in dst_dir.glob("*.jpg"):
            leftover.unlink()
    for f in files:
        width, height = jpeg_size(f)
        proc = run_capture(
            [tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
             "-protocol_whitelist", "file", "-f", "image2", "-pattern_type", "none",
             "-i", f, "-vf", derive_filter(width, height, recipe), "-frames:v", "1",
             "-c:v", "mjpeg", "-q:v", q, "-f", "image2", "-update", "1", dst_dir / f.name],
            timeout=120,
        )
        if proc.returncode != 0:
            raise ToolError(f"derive failed for {f.name}: {proc.stderr.strip()[-300:]}", proc.returncode)
    return len(files)
