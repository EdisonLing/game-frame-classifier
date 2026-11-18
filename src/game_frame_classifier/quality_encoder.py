"""Quality tiers via video CRF re-encode, then extract/downscale."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterable, Sequence

from game_frame_classifier.frame_extractor import (
    DEFAULT_HEIGHT,
    DEFAULT_INTERVAL_S,
    DEFAULT_WIDTH,
    FFmpegNotFoundError,
    FrameRecord,
    extract_frames,
    require_ffmpeg,
)


# Eval tiers (D04/D22): chosen so 256x144 stills still separate (see quality-encoder.md).
# Augmentation samples the medium→low band.
TIER_CRF: dict[str, int] = {
    "full": 0,
    "medium": 38,
    "low": 45,
}
AUGMENT_CRF_MIN = 32
AUGMENT_CRF_MAX = 45


@dataclass(frozen=True)
class QualityFrameRecord:
    """A frame extracted from a quality-tiered video source."""

    frame_id: str
    video_id: str
    game: str
    timestamp_s: float
    path: str
    width: int
    height: int
    source_video: str
    quality_tier: str
    crf: int
    source_frame_id: str
    source_path: str


def crf_for_tier(tier: str) -> int:
    """Map a named tier to CRF. Raises ValueError on unknown tier."""
    key = tier.strip().lower()
    if key not in TIER_CRF:
        known = ", ".join(sorted(TIER_CRF))
        raise ValueError(f"unknown quality tier {tier!r}; expected one of: {known}")
    return TIER_CRF[key]


def validate_crf(crf: int) -> int:
    if not isinstance(crf, int) or isinstance(crf, bool):
        raise TypeError(f"crf must be int, got {type(crf).__name__}")
    if crf < 0 or crf > 51:
        raise ValueError(f"crf must be in 0..51, got {crf}")
    return crf


def reencode_video_crf(
    src: Path | str,
    dest: Path | str,
    *,
    crf: int,
    preset: str = "veryfast",
    max_duration_s: float | None = None,
) -> Path:
    """
    Re-encode ``src`` to H.264 at ``crf`` (video only, no audio), or only its first
    ``max_duration_s`` seconds when given.

    This is the authentic quality path: compress the timeline, then callers
    extract and downscale. CRF 0 is rejected here — use the original file.
    """
    crf = validate_crf(crf)
    if crf == 0:
        raise ValueError("crf 0 means use the original video; do not re-encode")
    src = Path(src)
    dest = Path(dest)
    if not src.is_file():
        raise FileNotFoundError(f"video not found: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = require_ffmpeg()
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        *(["-t", f"{max_duration_s:.3f}"] if max_duration_s else []),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg video CRF encode failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {proc.stderr.strip()}"
        )
    return dest.resolve()


def _frame_to_quality(
    rec: FrameRecord,
    *,
    tier: str,
    crf: int,
    source_video: Path,
) -> QualityFrameRecord:
    tier_label = tier.strip().lower()
    return QualityFrameRecord(
        frame_id=f"{rec.frame_id}:{tier_label}",
        video_id=rec.video_id,
        game=rec.game,
        timestamp_s=rec.timestamp_s,
        path=rec.path,
        width=rec.width,
        height=rec.height,
        source_video=str(Path(source_video).resolve()),
        quality_tier=tier_label,
        crf=crf,
        source_frame_id=rec.frame_id,
        source_path=str(Path(source_video).resolve()),
    )


def write_quality_manifest(
    records: Sequence[QualityFrameRecord],
    output_dir: Path | str,
) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "frames_manifest.csv"
    json_path = output_dir / "frames_manifest.json"
    fieldnames = [f.name for f in fields(QualityFrameRecord)]

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow(asdict(rec))

    with json_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, indent=2)

    return csv_path, json_path


def encode_video_quality_tiers(
    video_path: Path | str,
    output_dir: Path | str,
    *,
    game: str,
    video_id: str | None = None,
    tiers: Sequence[str] = ("full", "medium", "low"),
    interval_s: float = DEFAULT_INTERVAL_S,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    max_duration_s: float | None = None,
    preset: str = "veryfast",
    keep_proxies: bool = False,
) -> dict[str, list[QualityFrameRecord]]:
    """
    Build full / medium / low frame sets from one source video.

    **full (CRF 0):** extract + downscale from the original video.
    **medium / low:** re-encode the *video* at CRF 38 / 45, then extract +
    downscale from that proxy (authentic low-bitrate look).

    Layout: ``output_dir/<tier>/`` images + manifests, plus
    ``quality_summary.json``. Proxy mp4s are deleted unless ``keep_proxies``.
    """
    video_path = Path(video_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not game.strip():
        raise ValueError("game label must be non-empty")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    video_id = video_id or video_path.stem
    resolved = [(t, crf_for_tier(t)) for t in tiers]
    by_tier: dict[str, list[QualityFrameRecord]] = {}
    proxy_dir = output_dir / "_proxies"
    if keep_proxies:
        proxy_dir.mkdir(parents=True, exist_ok=True)

    for tier, crf in resolved:
        tier_key = tier.strip().lower()
        tier_dir = output_dir / tier_key
        if tier_dir.exists():
            shutil.rmtree(tier_dir)
        tier_dir.mkdir(parents=True, exist_ok=True)

        tmp_proxy: Path | None = None
        try:
            if crf == 0:
                src_for_extract = video_path
            elif keep_proxies:
                src_for_extract = proxy_dir / f"{video_id}_{tier_key}_crf{crf}.mp4"
                reencode_video_crf(
                    video_path, src_for_extract, crf=crf, preset=preset
                )
            else:
                tmp = tempfile.NamedTemporaryFile(
                    prefix=f"gfc_q_{tier_key}_",
                    suffix=".mp4",
                    delete=False,
                )
                tmp.close()
                tmp_proxy = Path(tmp.name)
                reencode_video_crf(
                    video_path, tmp_proxy, crf=crf, preset=preset, max_duration_s=max_duration_s,
                )
                src_for_extract = tmp_proxy

            frames = extract_frames(
                src_for_extract,
                tier_dir,
                game=game,
                video_id=video_id if crf == 0 else f"{video_id}_{tier_key}",
                interval_s=interval_s,
                width=width,
                height=height,
                max_duration_s=max_duration_s,
                write_manifest=False,
            )
            qrecs = [
                _frame_to_quality(r, tier=tier_key, crf=crf, source_video=video_path)
                for r in frames
            ]
            write_quality_manifest(qrecs, tier_dir)
            by_tier[tier_key] = qrecs
        finally:
            if tmp_proxy is not None:
                tmp_proxy.unlink(missing_ok=True)

    summary = {
        "method": "video_crf_then_extract",
        "source_video": str(video_path),
        "tiers": {
            tier: {"crf": crf, "count": len(by_tier[tier.strip().lower()])}
            for tier, crf in resolved
        },
        "tier_crf_map": dict(TIER_CRF),
        "augment_crf_range": [AUGMENT_CRF_MIN, AUGMENT_CRF_MAX],
        "interval_s": interval_s,
        "width": width,
        "height": height,
        "keep_proxies": keep_proxies,
    }
    (output_dir / "quality_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return by_tier


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Build full/medium/low frame sets: re-encode video at CRF "
            "(medium/low), then extract 256×144 @ 1/5s from each."
        )
    )
    p.add_argument("video", type=Path, help="Source video (original / full quality)")
    p.add_argument("-o", "--output-dir", type=Path, required=True)
    p.add_argument("--game", required=True, help="Game label (e.g. Valorant)")
    p.add_argument("--video-id", default=None, help="Stable id (default: video stem)")
    p.add_argument(
        "--tiers",
        nargs="+",
        default=["full", "medium", "low"],
        help="Quality tiers to produce (default: full medium low)",
    )
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S)
    p.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    p.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    p.add_argument("--max-duration", type=float, default=None)
    p.add_argument(
        "--preset",
        default="veryfast",
        help="x264 preset for medium/low re-encode (default: veryfast)",
    )
    p.add_argument(
        "--keep-proxies",
        action="store_true",
        help="Keep re-encoded mp4s under output_dir/_proxies/",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    try:
        by_tier = encode_video_quality_tiers(
            args.video,
            args.output_dir,
            game=args.game,
            video_id=args.video_id,
            tiers=args.tiers,
            interval_s=args.interval,
            width=args.width,
            height=args.height,
            max_duration_s=args.max_duration,
            preset=args.preset,
            keep_proxies=args.keep_proxies,
        )
    except FFmpegNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    total = sum(len(v) for v in by_tier.values())
    print(
        f"quality tiers: {total} frames across {len(by_tier)} tiers "
        f"(video CRF → extract) -> {args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
