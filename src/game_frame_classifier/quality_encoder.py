"""Re-encode frames at controlled quality tiers (ffmpeg CRF)."""

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

from game_frame_classifier.frame_cleaner import FrameRecord, load_frame_manifest
from game_frame_classifier.frame_extractor import FFmpegNotFoundError, require_ffmpeg


# Eval tiers from the proposal. Augmentation may sample CRF in [28, 40].
TIER_CRF: dict[str, int] = {
    "full": 0,
    "medium": 28,
    "low": 38,
}
AUGMENT_CRF_MIN = 28
AUGMENT_CRF_MAX = 40


@dataclass(frozen=True)
class QualityFrameRecord:
    """A frame copy tagged with quality tier / CRF."""

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


def degrade_frame_ffmpeg(
    src: Path | str,
    dest: Path | str,
    *,
    crf: int,
) -> Path:
    """
    Degrade a still frame via an ffmpeg H.264 CRF round-trip.

    CRF 0 copies the source bytes (lossless path for the ``full`` tier).
    Higher CRF → stronger compression after decode back to JPEG.
    """
    crf = validate_crf(crf)
    src = Path(src)
    dest = Path(dest)
    if not src.is_file():
        raise FileNotFoundError(f"frame not found: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    if crf == 0:
        shutil.copy2(src, dest)
        return dest.resolve()

    ffmpeg = require_ffmpeg()
    with tempfile.TemporaryDirectory(prefix="gfc_qenc_") as tmp:
        tmp_mp4 = Path(tmp) / "degraded.mp4"
        # Still → short CFR clip at CRF, then extract one JPEG.
        enc = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            str(tmp_mp4),
        ]
        proc = subprocess.run(enc, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                "ffmpeg CRF encode failed\n"
                f"cmd: {' '.join(enc)}\n"
                f"stderr: {proc.stderr.strip()}"
            )

        dec = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(tmp_mp4),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(dest),
        ]
        proc = subprocess.run(dec, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                "ffmpeg decode-to-jpeg failed\n"
                f"cmd: {' '.join(dec)}\n"
                f"stderr: {proc.stderr.strip()}"
            )

    return dest.resolve()


def _safe_stem(frame_id: str) -> str:
    return frame_id.replace(":", "_").replace("/", "_").replace("\\", "_")


def encode_frame_record(
    rec: FrameRecord,
    output_dir: Path | str,
    *,
    tier: str | None = None,
    crf: int | None = None,
) -> QualityFrameRecord:
    """
    Write one degraded copy of ``rec`` under ``output_dir``.

    Provide ``tier`` (full/medium/low) and/or explicit ``crf``. If both are
    given, ``crf`` wins for the encode but ``tier`` is still stored as the label
    (use tier=None with only crf for augmentation samples).
    """
    if crf is None and tier is None:
        raise ValueError("provide tier and/or crf")
    if crf is None:
        assert tier is not None
        crf = crf_for_tier(tier)
        tier_label = tier.strip().lower()
    else:
        crf = validate_crf(crf)
        tier_label = tier.strip().lower() if tier else f"crf{crf}"

    output_dir = Path(output_dir)
    src = Path(rec.path)
    dest = output_dir / f"{_safe_stem(rec.frame_id)}_{tier_label}_crf{crf}{src.suffix.lower() or '.jpg'}"
    out_path = degrade_frame_ffmpeg(src, dest, crf=crf)
    return QualityFrameRecord(
        frame_id=f"{rec.frame_id}:{tier_label}",
        video_id=rec.video_id,
        game=rec.game,
        timestamp_s=rec.timestamp_s,
        path=str(out_path),
        width=rec.width,
        height=rec.height,
        source_video=rec.source_video,
        quality_tier=tier_label,
        crf=crf,
        source_frame_id=rec.frame_id,
        source_path=str(src.resolve()),
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


def encode_manifest(
    manifest_path: Path | str,
    output_dir: Path | str,
    *,
    tiers: Sequence[str] = ("full", "medium", "low"),
) -> dict[str, list[QualityFrameRecord]]:
    """
    Encode every frame in a manifest into each requested quality tier.

    Layout: ``output_dir/<tier>/`` with images + per-tier manifests, plus
    ``quality_summary.json`` at the root.
    """
    records = load_frame_manifest(manifest_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Validate tiers up front
    resolved = [(t, crf_for_tier(t)) for t in tiers]
    by_tier: dict[str, list[QualityFrameRecord]] = {}

    for tier, _crf in resolved:
        tier_dir = output_dir / tier
        tier_dir.mkdir(parents=True, exist_ok=True)
        encoded: list[QualityFrameRecord] = []
        for rec in records:
            encoded.append(encode_frame_record(rec, tier_dir, tier=tier))
        write_quality_manifest(encoded, tier_dir)
        by_tier[tier] = encoded

    summary = {
        "input_count": len(records),
        "tiers": {tier: {"crf": crf, "count": len(by_tier[tier])} for tier, crf in resolved},
        "tier_crf_map": dict(TIER_CRF),
        "augment_crf_range": [AUGMENT_CRF_MIN, AUGMENT_CRF_MAX],
    }
    (output_dir / "quality_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return by_tier


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Re-encode gameplay frames at full/medium/low CRF tiers."
    )
    p.add_argument("manifest", type=Path, help="frames_manifest.csv or .json")
    p.add_argument("-o", "--output-dir", type=Path, required=True)
    p.add_argument(
        "--tiers",
        nargs="+",
        default=["full", "medium", "low"],
        help="Quality tiers to produce (default: full medium low)",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    try:
        by_tier = encode_manifest(args.manifest, args.output_dir, tiers=args.tiers)
    except FFmpegNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    total = sum(len(v) for v in by_tier.values())
    print(
        f"encoded {total} frame-copies across {len(by_tier)} tiers "
        f"-> {args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
