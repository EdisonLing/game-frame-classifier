"""Extract labelled gameplay frames from a video with ffmpeg."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_INTERVAL_S = 5.0
DEFAULT_WIDTH = 256
DEFAULT_HEIGHT = 144
DEFAULT_IMAGE_EXT = "jpg"


class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg/ffprobe is not on PATH."""


@dataclass(frozen=True)
class FrameRecord:
    """One extracted frame and its metadata."""

    frame_id: str
    video_id: str
    game: str
    timestamp_s: float
    path: str
    width: int
    height: int
    source_video: str


def require_ffmpeg() -> str:
    """Return path to ffmpeg, or raise."""
    path = shutil.which("ffmpeg")
    if path is None:
        raise FFmpegNotFoundError("ffmpeg not found on PATH")
    return path


def require_ffprobe() -> str:
    """Return path to ffprobe, or raise."""
    path = shutil.which("ffprobe")
    if path is None:
        raise FFmpegNotFoundError("ffprobe not found on PATH")
    return path


def probe_duration_s(video_path: Path) -> float:
    """Return media duration in seconds via ffprobe."""
    ffprobe = require_ffprobe()
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def planned_timestamps(duration_s: float, interval_s: float = DEFAULT_INTERVAL_S) -> list[float]:
    """
    Timestamps at 0, interval, 2*interval, ... while t < duration.

    Matches ffmpeg `fps=1/interval` sampling for constant-frame-rate sources
    (frame at t=duration is excluded).
    """
    if interval_s <= 0:
        raise ValueError(f"interval_s must be > 0, got {interval_s}")
    if duration_s < 0:
        raise ValueError(f"duration_s must be >= 0, got {duration_s}")

    timestamps: list[float] = []
    t = 0.0
    # Guard against float drift near the end.
    while t < duration_s - 1e-6:
        timestamps.append(round(t, 6))
        t += interval_s
    return timestamps


def frame_filename(video_id: str, index: int, timestamp_s: float, ext: str = DEFAULT_IMAGE_EXT) -> str:
    """Deterministic frame filename."""
    ms = int(round(timestamp_s * 1000))
    return f"{video_id}_f{index:05d}_t{ms:08d}ms.{ext.lstrip('.')}"


def build_ffmpeg_extract_cmd(
    video_path: Path,
    output_dir: Path,
    *,
    interval_s: float,
    width: int,
    height: int,
    image_ext: str,
    max_duration_s: float | None,
) -> list[str]:
    """Build the ffmpeg argv used for extraction (also stored in debug output)."""
    ffmpeg = require_ffmpeg()
    pattern = output_dir / f"frame_%05d.{image_ext.lstrip('.')}"
    vf = f"fps=1/{interval_s:g},scale={width}:{height}:flags=bicubic"

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if max_duration_s is not None:
        cmd.extend(["-t", f"{max_duration_s:g}"])
    cmd.extend(["-i", str(video_path), "-vf", vf])
    if image_ext.lstrip(".").lower() in {"jpg", "jpeg"}:
        cmd.extend(["-q:v", "2"])
    cmd.append(str(pattern))
    return cmd


def _run_ffmpeg_extract(
    video_path: Path,
    output_dir: Path,
    *,
    interval_s: float,
    width: int,
    height: int,
    image_ext: str,
    max_duration_s: float | None,
) -> list[str]:
    cmd = build_ffmpeg_extract_cmd(
        video_path,
        output_dir,
        interval_s=interval_s,
        width=width,
        height=height,
        image_ext=image_ext,
        max_duration_s=max_duration_s,
    )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg extract failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {proc.stderr.strip()}"
        )
    return cmd


def extract_frames(
    video_path: Path | str,
    output_dir: Path | str,
    *,
    game: str,
    video_id: str | None = None,
    interval_s: float = DEFAULT_INTERVAL_S,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    image_ext: str = DEFAULT_IMAGE_EXT,
    max_duration_s: float | None = None,
    write_manifest: bool = True,
    debug: bool = False,
) -> list[FrameRecord]:
    """
    Extract frames from ``video_path`` into ``output_dir``.

    Returns frame records. Writes ``frames_manifest.csv`` and
    ``frames_manifest.json`` when ``write_manifest`` is True.

    ``debug=True`` also writes ``extract_debug.json``, a per-frame
    ``extract_debug_frames.csv``, and copies raw ffmpeg outputs under
    ``output_dir/debug/raw/`` before rename (so you can audit the pipeline).
    """
    video_path = Path(video_path).resolve()
    output_dir = Path(output_dir)
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not game.strip():
        raise ValueError("game label must be non-empty")

    video_id = video_id or video_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = output_dir / "debug" if debug else None
    raw_debug_dir = debug_dir / "raw" if debug_dir is not None else None
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        assert raw_debug_dir is not None
        if raw_debug_dir.exists():
            shutil.rmtree(raw_debug_dir)
        raw_debug_dir.mkdir(parents=True, exist_ok=True)

    full_duration = probe_duration_s(video_path)
    effective_duration = full_duration
    if max_duration_s is not None:
        if max_duration_s <= 0:
            raise ValueError(f"max_duration_s must be > 0, got {max_duration_s}")
        effective_duration = min(full_duration, max_duration_s)

    planned = planned_timestamps(effective_duration, interval_s)
    notes: list[str] = []

    # Clear previous extract pattern files for this run directory naming space
    # (only our temp pattern; final names are rewritten below).
    for stale in output_dir.glob(f"frame_*.{image_ext.lstrip('.')}"):
        stale.unlink()

    cmd = _run_ffmpeg_extract(
        video_path,
        output_dir,
        interval_s=interval_s,
        width=width,
        height=height,
        image_ext=image_ext,
        max_duration_s=max_duration_s,
    )

    raw_frames = sorted(output_dir.glob(f"frame_*.{image_ext.lstrip('.')}"))
    expected = list(planned)
    count_mismatch = len(raw_frames) != len(expected)
    if count_mismatch:
        notes.append(
            f"count_mismatch: got {len(raw_frames)} files, planned {len(expected)}"
        )
        # ffmpeg fps can occasionally differ by ±1 on some containers; tolerate
        # and align to min length with a clear error if wildly off.
        if abs(len(raw_frames) - len(expected)) > 1:
            raise RuntimeError(
                f"frame count mismatch: got {len(raw_frames)} files, "
                f"expected ~{len(expected)} for duration={effective_duration:.3f}s "
                f"interval={interval_s}"
            )
        n = min(len(raw_frames), len(expected))
        if len(raw_frames) > n:
            notes.append(f"dropped_extra_raw_frames: {len(raw_frames) - n}")
        if len(expected) > n:
            unused_ts = expected[n:]
            notes.append(f"unused_planned_timestamps: {unused_ts}")
        raw_frames = raw_frames[:n]
        expected = expected[:n]

    records: list[FrameRecord] = []
    debug_rows: list[dict] = []
    for i, (raw, ts) in enumerate(zip(raw_frames, expected, strict=True)):
        final_name = frame_filename(video_id, i, ts, image_ext)
        final_path = output_dir / final_name
        if final_path.exists():
            final_path.unlink()

        raw_debug_path = ""
        if raw_debug_dir is not None:
            dbg_copy = raw_debug_dir / raw.name
            shutil.copy2(raw, dbg_copy)
            raw_debug_path = str(dbg_copy.resolve())

        raw.rename(final_path)
        frame_id = f"{video_id}:{i:05d}"
        records.append(
            FrameRecord(
                frame_id=frame_id,
                video_id=video_id,
                game=game,
                timestamp_s=ts,
                path=str(final_path.resolve()),
                width=width,
                height=height,
                source_video=str(video_path),
            )
        )
        debug_rows.append(
            {
                "index": i,
                "frame_id": frame_id,
                "planned_timestamp_s": ts,
                "raw_ffmpeg_name": raw.name,
                "final_name": final_name,
                "final_path": str(final_path.resolve()),
                "raw_debug_path": raw_debug_path,
                "status": "extracted",
            }
        )

    if write_manifest:
        write_frame_manifest(records, output_dir)

    if debug_dir is not None:
        _write_extract_debug(
            debug_dir=debug_dir,
            video_path=video_path,
            output_dir=output_dir,
            video_id=video_id,
            game=game,
            interval_s=interval_s,
            width=width,
            height=height,
            image_ext=image_ext,
            max_duration_s=max_duration_s,
            full_duration_s=full_duration,
            effective_duration_s=effective_duration,
            planned_timestamps_s=planned,
            ffmpeg_cmd=cmd,
            notes=notes,
            debug_rows=debug_rows,
            record_count=len(records),
        )

    return records


def _write_extract_debug(
    *,
    debug_dir: Path,
    video_path: Path,
    output_dir: Path,
    video_id: str,
    game: str,
    interval_s: float,
    width: int,
    height: int,
    image_ext: str,
    max_duration_s: float | None,
    full_duration_s: float,
    effective_duration_s: float,
    planned_timestamps_s: Sequence[float],
    ffmpeg_cmd: Sequence[str],
    notes: Sequence[str],
    debug_rows: Sequence[dict],
    record_count: int,
) -> None:
    payload = {
        "video_path": str(video_path),
        "output_dir": str(output_dir.resolve()),
        "video_id": video_id,
        "game": game,
        "interval_s": interval_s,
        "width": width,
        "height": height,
        "image_ext": image_ext,
        "max_duration_s": max_duration_s,
        "full_duration_s": full_duration_s,
        "effective_duration_s": effective_duration_s,
        "planned_count": len(planned_timestamps_s),
        "planned_timestamps_s": list(planned_timestamps_s),
        "extracted_count": record_count,
        "ffmpeg_cmd": list(ffmpeg_cmd),
        "notes": list(notes),
        "raw_debug_dir": str((debug_dir / "raw").resolve()),
    }
    (debug_dir / "extract_debug.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    csv_path = debug_dir / "extract_debug_frames.csv"
    fieldnames = [
        "index",
        "frame_id",
        "planned_timestamp_s",
        "raw_ffmpeg_name",
        "final_name",
        "final_path",
        "raw_debug_path",
        "status",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in debug_rows:
            writer.writerow(row)


def write_frame_manifest(records: Sequence[FrameRecord], output_dir: Path | str) -> tuple[Path, Path]:
    """Write CSV + JSON manifests; return their paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "frames_manifest.csv"
    json_path = output_dir / "frames_manifest.json"

    fieldnames = list(asdict(records[0]).keys()) if records else [
        "frame_id",
        "video_id",
        "game",
        "timestamp_s",
        "path",
        "width",
        "height",
        "source_video",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow(asdict(rec))

    with json_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, indent=2)

    return csv_path, json_path


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Extract gameplay frames with ffmpeg.")
    p.add_argument("video", type=Path, help="Path to input video")
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for frames + manifest",
    )
    p.add_argument("--game", required=True, help="Game label (e.g. Valorant)")
    p.add_argument("--video-id", default=None, help="Stable id (default: video stem)")
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S, help="Seconds between frames")
    p.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    p.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    p.add_argument("--ext", default=DEFAULT_IMAGE_EXT, help="Image extension (jpg/png)")
    p.add_argument(
        "--max-duration",
        type=float,
        default=None,
        help="Only decode the first N seconds (useful for smoke tests)",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Write extract_debug.json + per-frame CSV and keep raw ffmpeg "
        "outputs under output_dir/debug/raw/",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    records = extract_frames(
        args.video,
        args.output_dir,
        game=args.game,
        video_id=args.video_id,
        interval_s=args.interval,
        width=args.width,
        height=args.height,
        image_ext=args.ext,
        max_duration_s=args.max_duration,
        debug=args.debug,
    )
    suffix = " [debug]" if args.debug else ""
    print(f"extracted {len(records)} frames -> {args.output_dir}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
