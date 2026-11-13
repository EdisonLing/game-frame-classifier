"""Filter extracted gameplay frames: black / blur / perceptual-hash dedupe."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageFilter, ImageStat


# Tuned for 256×144 JPEG gameplay frames; override via CLI / API.
DEFAULT_BLACK_MEAN_MAX = 8.0  # mean luma 0–255
DEFAULT_BLACK_STD_MAX = 4.0
# FIND_EDGES variance: synthetic blur ~150, real Valorant HUD frames ~2k+.
DEFAULT_BLUR_VARIANCE_MIN = 400.0
DEFAULT_PHASH_SIZE = 8  # → 64-bit hash
DEFAULT_PHASH_MAX_DISTANCE = 6  # Hamming; near-duplicates within this drop


@dataclass(frozen=True)
class FrameRecord:
    """One frame row (matches extractor manifest columns)."""

    frame_id: str
    video_id: str
    game: str
    timestamp_s: float
    path: str
    width: int
    height: int
    source_video: str


@dataclass(frozen=True)
class RejectRecord:
    """Why a frame was dropped (rich enough for debug audits)."""

    frame_id: str
    path: str
    game: str
    reason: str
    detail: str
    # Structured extras (empty string when N/A so CSV stays simple)
    matched_frame_id: str = ""
    matched_path: str = ""
    hamming_distance: str = ""
    metric_name: str = ""
    metric_value: str = ""
    debug_path: str = ""


@dataclass(frozen=True)
class CleanResult:
    kept: list[FrameRecord]
    rejected: list[RejectRecord]


def load_frame_manifest(path: Path | str) -> list[FrameRecord]:
    """Load frames_manifest.csv or .json produced by the extractor."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"manifest not found: {path}")

    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [_record_from_mapping(row) for row in raw]

    if path.suffix.lower() != ".csv":
        raise ValueError(f"unsupported manifest type: {path.suffix}")

    with path.open(encoding="utf-8", newline="") as f:
        return [_record_from_mapping(row) for row in csv.DictReader(f)]


def _record_from_mapping(row: dict) -> FrameRecord:
    return FrameRecord(
        frame_id=str(row["frame_id"]),
        video_id=str(row["video_id"]),
        game=str(row["game"]),
        timestamp_s=float(row["timestamp_s"]),
        path=str(row["path"]),
        width=int(row["width"]),
        height=int(row["height"]),
        source_video=str(row["source_video"]),
    )


def write_frame_manifest(records: Sequence[FrameRecord], output_dir: Path | str) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "frames_manifest.csv"
    json_path = output_dir / "frames_manifest.json"
    fieldnames = [f.name for f in fields(FrameRecord)]

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow(asdict(rec))

    with json_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, indent=2)

    return csv_path, json_path


def write_reject_log(rejects: Sequence[RejectRecord], output_dir: Path | str) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "rejects.csv"
    json_path = output_dir / "rejects.json"
    fieldnames = [f.name for f in fields(RejectRecord)]

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in rejects:
            writer.writerow(asdict(rec))

    with json_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in rejects], f, indent=2)

    return csv_path, json_path


def reject_counts_by_reason(rejects: Sequence[RejectRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rejects:
        counts[r.reason] = counts.get(r.reason, 0) + 1
    return counts


def reject_counts_by_game(rejects: Sequence[RejectRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rejects:
        counts[r.game] = counts.get(r.game, 0) + 1
    return counts


def _to_luma(image: Image.Image) -> Image.Image:
    return image.convert("L")


def luma_stats(image: Image.Image) -> tuple[float, float]:
    gray = _to_luma(image)
    stat = ImageStat.Stat(gray)
    mean = float(stat.mean[0])
    std = float(stat.stddev[0]) if stat.stddev else 0.0
    return mean, std


def is_mostly_black(
    image: Image.Image,
    *,
    mean_max: float = DEFAULT_BLACK_MEAN_MAX,
    std_max: float = DEFAULT_BLACK_STD_MAX,
) -> bool:
    """True if frame is near-black (low mean and low variance)."""
    mean, std = luma_stats(image)
    return mean <= mean_max and std <= std_max


def laplacian_variance(image: Image.Image) -> float:
    """
    Focus measure: variance of a Laplacian-like high-pass.

    Uses Pillow's FIND_EDGES kernel as a practical stand-in (no numpy required).
    Lower variance ⇒ blurrier / flatter.
    """
    gray = _to_luma(image)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    stat = ImageStat.Stat(edges)
    std = float(stat.stddev[0]) if stat.stddev else 0.0
    return std * std


def is_too_blurry(
    image: Image.Image,
    *,
    min_variance: float = DEFAULT_BLUR_VARIANCE_MIN,
) -> bool:
    return laplacian_variance(image) < min_variance


def average_hash(image: Image.Image, hash_size: int = DEFAULT_PHASH_SIZE) -> int:
    """
    aHash: resize to hash_size×hash_size, threshold by mean.

    Packed into an int (hash_size^2 bits). Called ``phash`` in the API for
    roadmap naming; aHash is enough for near-duplicate gameplay frames.
    """
    if hash_size < 2:
        raise ValueError(f"hash_size must be >= 2, got {hash_size}")
    gray = _to_luma(image).resize((hash_size, hash_size), Image.Resampling.BILINEAR)
    pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    value = 0
    for bit, pix in enumerate(pixels):
        if pix >= mean:
            value |= 1 << bit
    return value


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _safe_name(frame_id: str) -> str:
    return frame_id.replace(":", "_").replace("/", "_").replace("\\", "_")


def _copy_reject_debug(
    src: Path,
    debug_root: Path,
    *,
    reason: str,
    frame_id: str,
    matched_frame_id: str = "",
) -> Path:
    """
    Copy a rejected frame under rejected/<reason>/ for visual audit.

    Duplicate filenames include the matched kept frame id.
    """
    dest_dir = debug_root / reason
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(frame_id)
    if matched_frame_id:
        stem = f"{stem}__dup_of_{_safe_name(matched_frame_id)}"
    dest = dest_dir / f"{stem}{src.suffix.lower() or '.jpg'}"
    shutil.copy2(src, dest)
    return dest.resolve()


def clean_frames(
    records: Sequence[FrameRecord],
    *,
    black_mean_max: float = DEFAULT_BLACK_MEAN_MAX,
    black_std_max: float = DEFAULT_BLACK_STD_MAX,
    blur_variance_min: float = DEFAULT_BLUR_VARIANCE_MIN,
    phash_size: int = DEFAULT_PHASH_SIZE,
    phash_max_distance: int = DEFAULT_PHASH_MAX_DISTANCE,
    copy_kept_to: Path | str | None = None,
    debug_rejects_to: Path | str | None = None,
    skip_missing: bool = False,
) -> CleanResult:
    """
    Filter frames in order. Dedupe is within the kept set so far (first wins).

    When ``debug_rejects_to`` is set, rejected images are copied under that
    directory (grouped by reason) and ``RejectRecord.debug_path`` is filled.
    Duplicates record ``matched_frame_id`` / ``matched_path`` of the kept twin.

    Non-game / lobby detector is intentionally **not** implemented yet (D11 open).
    Menus/HUDs are kept.
    """
    kept: list[FrameRecord] = []
    rejected: list[RejectRecord] = []
    kept_hashes: list[int] = []
    kept_meta: list[tuple[str, str]] = []  # (frame_id, path) parallel to kept_hashes

    dest_root: Path | None = Path(copy_kept_to) if copy_kept_to else None
    debug_root: Path | None = Path(debug_rejects_to) if debug_rejects_to else None
    if dest_root is not None:
        dest_root.mkdir(parents=True, exist_ok=True)
    if debug_root is not None:
        debug_root.mkdir(parents=True, exist_ok=True)

    def _reject(
        rec: FrameRecord,
        *,
        reason: str,
        detail: str,
        src: Path | None = None,
        matched_frame_id: str = "",
        matched_path: str = "",
        hamming: int | None = None,
        metric_name: str = "",
        metric_value: str = "",
    ) -> None:
        debug_path = ""
        if debug_root is not None and src is not None and src.is_file():
            debug_path = str(
                _copy_reject_debug(
                    src,
                    debug_root,
                    reason=reason,
                    frame_id=rec.frame_id,
                    matched_frame_id=matched_frame_id,
                )
            )
        rejected.append(
            RejectRecord(
                frame_id=rec.frame_id,
                path=rec.path,
                game=rec.game,
                reason=reason,
                detail=detail,
                matched_frame_id=matched_frame_id,
                matched_path=matched_path,
                hamming_distance="" if hamming is None else str(hamming),
                metric_name=metric_name,
                metric_value=metric_value,
                debug_path=debug_path,
            )
        )

    for rec in records:
        src = Path(rec.path)
        if not src.is_file():
            if skip_missing:
                _reject(rec, reason="missing_file", detail="path does not exist")
                continue
            raise FileNotFoundError(f"frame not found: {src}")

        with Image.open(src) as im:
            im.load()
            image = im.convert("RGB")

            mean, std = luma_stats(image)
            if mean <= black_mean_max and std <= black_std_max:
                _reject(
                    rec,
                    reason="black",
                    detail=f"luma mean={mean:.2f} std={std:.2f} "
                    f"(thresholds mean<={black_mean_max}, std<={black_std_max})",
                    src=src,
                    metric_name="luma_mean_std",
                    metric_value=f"{mean:.4f},{std:.4f}",
                )
                continue

            var = laplacian_variance(image)
            if var < blur_variance_min:
                _reject(
                    rec,
                    reason="blur",
                    detail=f"laplacian_variance={var:.3f} < {blur_variance_min}",
                    src=src,
                    metric_name="laplacian_variance",
                    metric_value=f"{var:.6f}",
                )
                continue

            h = average_hash(image, phash_size)
            match_idx = None
            match_dist = None
            for i, prev_h in enumerate(kept_hashes):
                dist = hamming_distance(h, prev_h)
                if dist <= phash_max_distance:
                    match_idx = i
                    match_dist = dist
                    break
            if match_idx is not None:
                matched_id, matched_path = kept_meta[match_idx]
                assert match_dist is not None
                _reject(
                    rec,
                    reason="duplicate",
                    detail=(
                        f"near-duplicate of {matched_id} "
                        f"(hamming={match_dist} <= {phash_max_distance})"
                    ),
                    src=src,
                    matched_frame_id=matched_id,
                    matched_path=matched_path,
                    hamming=match_dist,
                    metric_name="hamming",
                    metric_value=str(match_dist),
                )
                continue

            out_rec = rec
            out_path = rec.path
            if dest_root is not None:
                dest = dest_root / src.name
                shutil.copy2(src, dest)
                out_path = str(dest.resolve())
                out_rec = FrameRecord(
                    frame_id=rec.frame_id,
                    video_id=rec.video_id,
                    game=rec.game,
                    timestamp_s=rec.timestamp_s,
                    path=out_path,
                    width=rec.width,
                    height=rec.height,
                    source_video=rec.source_video,
                )

            kept.append(out_rec)
            kept_hashes.append(h)
            kept_meta.append((rec.frame_id, out_path))

    return CleanResult(kept=kept, rejected=rejected)


def clean_manifest(
    manifest_path: Path | str,
    output_dir: Path | str,
    *,
    copy_kept: bool = True,
    debug: bool = False,
    debug_rejects_to: Path | str | None = None,
    **clean_kwargs,
) -> CleanResult:
    """
    Load manifest, clean, write kept manifest + reject log under output_dir.

    ``debug=True`` copies rejected frames to ``output_dir/rejected/<reason>/``
    (or ``debug_rejects_to`` if given) and fills match/metric fields on each reject.
    """
    records = load_frame_manifest(manifest_path)
    output_dir = Path(output_dir)
    copy_to = output_dir / "kept" if copy_kept else None
    if debug_rejects_to is not None:
        debug_to: Path | None = Path(debug_rejects_to)
    elif debug:
        debug_to = output_dir / "rejected"
    else:
        debug_to = None

    result = clean_frames(
        records,
        copy_kept_to=copy_to,
        debug_rejects_to=debug_to,
        **clean_kwargs,
    )
    write_frame_manifest(result.kept, output_dir)
    write_reject_log(result.rejected, output_dir)
    summary = {
        "input_count": len(records),
        "kept_count": len(result.kept),
        "rejected_count": len(result.rejected),
        "rejects_by_reason": reject_counts_by_reason(result.rejected),
        "rejects_by_game": reject_counts_by_game(result.rejected),
        "debug": debug_to is not None,
        "debug_rejects_dir": str(debug_to) if debug_to else "",
    }
    (output_dir / "clean_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Clean extracted gameplay frames.")
    p.add_argument("manifest", type=Path, help="frames_manifest.csv or .json")
    p.add_argument("-o", "--output-dir", type=Path, required=True)
    p.add_argument("--no-copy", action="store_true", help="Do not copy kept images")
    p.add_argument(
        "--debug",
        action="store_true",
        help="Keep rejected frames under output_dir/rejected/<reason>/ and "
        "record matched frame / metrics in rejects.csv",
    )
    p.add_argument("--black-mean-max", type=float, default=DEFAULT_BLACK_MEAN_MAX)
    p.add_argument("--black-std-max", type=float, default=DEFAULT_BLACK_STD_MAX)
    p.add_argument("--blur-variance-min", type=float, default=DEFAULT_BLUR_VARIANCE_MIN)
    p.add_argument("--phash-size", type=int, default=DEFAULT_PHASH_SIZE)
    p.add_argument("--phash-max-distance", type=int, default=DEFAULT_PHASH_MAX_DISTANCE)
    p.add_argument(
        "--skip-missing",
        action="store_true",
        help="Reject missing files instead of raising",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    result = clean_manifest(
        args.manifest,
        args.output_dir,
        copy_kept=not args.no_copy,
        debug=args.debug,
        black_mean_max=args.black_mean_max,
        black_std_max=args.black_std_max,
        blur_variance_min=args.blur_variance_min,
        phash_size=args.phash_size,
        phash_max_distance=args.phash_max_distance,
        skip_missing=args.skip_missing,
    )
    print(
        f"kept {len(result.kept)} / rejected {len(result.rejected)} "
        f"-> {args.output_dir}"
        + (" [debug]" if args.debug else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
