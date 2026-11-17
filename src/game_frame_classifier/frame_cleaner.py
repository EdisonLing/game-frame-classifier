"""Filter extracted gameplay frames: black / blur / perceptual-hash dedupe.

Manifest mode cleans one extractor ``frames_manifest`` (kept images + reject log).
Slot mode (``--slots``) cleans the training-pipeline slot index: one verdict per
slot from the ``full`` image, near-dupe removal within ``(game, source)``, and an
optional quarantine list. Spec: ``docs/roadmap/tools/frame-cleaner.md``.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from PIL import Image, ImageFilter, ImageStat

SLOTS_CSV_COLUMNS = (
    "slot_id",
    "clip_key",
    "game",
    "source",
    "bucket",
    "target_time_s",
    "path_full",
    "path_low",
)
SLOTS_CLEAN_EXTRA_COLUMNS = (
    "keep",
    "reject_reason",
    "dup_of",
    "luma_mean",
    "luma_std",
    "edge_var",
    "ahash",
)
SLOTS_CLEAN_COLUMNS = SLOTS_CSV_COLUMNS + SLOTS_CLEAN_EXTRA_COLUMNS


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


def _ahash_hex(value: int, hash_size: int = DEFAULT_PHASH_SIZE) -> str:
    bits = hash_size * hash_size
    width = (bits + 3) // 4
    return f"{value:0{width}x}"


def _utc_sort_key(recorded_start_utc: str) -> tuple[int, str]:
    """Empty / missing timestamps sort last; otherwise lexicographic UTC."""
    text = (recorded_start_utc or "").strip()
    if not text:
        return (1, "")
    return (0, text)


def load_slots_csv(path: Path | str) -> list[dict[str, str]]:
    """Load ``slots.csv`` rows as string dicts."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"slots table not found: {path}")
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    missing = [c for c in SLOTS_CSV_COLUMNS if c not in (rows[0] if rows else SLOTS_CSV_COLUMNS)]
    if rows and missing:
        raise ValueError(f"slots.csv missing columns: {missing}")
    return [{k: str(row.get(k, "")) for k in SLOTS_CSV_COLUMNS} for row in rows]


def load_clips_index(path: Path | str) -> dict[str, dict[str, str]]:
    """Load ``clips_index.csv`` keyed by ``clip_key``."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"clips_index not found: {path}")
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    by_key: dict[str, dict[str, str]] = {}
    for row in rows:
        key = str(row.get("clip_key", ""))
        if not key:
            raise ValueError("clips_index row missing clip_key")
        by_key[key] = {k: str(v) for k, v in row.items()}
    return by_key


def load_quarantine(path: Path | str) -> dict[str, str]:
    """Load optional ``quarantine.csv`` → ``slot_id`` to reason."""
    path = Path(path)
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, str] = {}
    for row in rows:
        slot_id = str(row.get("slot_id", "")).strip()
        if not slot_id:
            continue
        reason = str(row.get("reason", "")).strip() or "quarantine"
        out[slot_id] = reason
    return out


def _slot_visit_key(
    row: Mapping[str, str],
    clips: Mapping[str, Mapping[str, str]],
) -> tuple[tuple[int, str], str, int]:
    clip = clips.get(row["clip_key"], {})
    utc = str(clip.get("recorded_start_utc", ""))
    try:
        bucket = int(row["bucket"])
    except ValueError:
        bucket = 0
    return (_utc_sort_key(utc), row["clip_key"], bucket)


def _format_metric(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _count_nested(rows: Sequence[Mapping[str, object]], key: str) -> dict[str, dict[str, int]]:
    """Per-key counts of keep/reject and reject reasons."""
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        group = str(row[key])
        bucket = out.setdefault(group, {"kept": 0, "rejected": 0})
        if row["keep"] is True or row["keep"] == "true":
            bucket["kept"] += 1
        else:
            bucket["rejected"] += 1
            reason = str(row.get("reject_reason") or "unknown")
            bucket[reason] = bucket.get(reason, 0) + 1
    return out


def clean_slots(
    slots: Sequence[Mapping[str, str]],
    clips: Mapping[str, Mapping[str, str]],
    *,
    data_root: Path | str,
    quarantine: Mapping[str, str] | None = None,
    black_mean_max: float = DEFAULT_BLACK_MEAN_MAX,
    black_std_max: float = DEFAULT_BLACK_STD_MAX,
    blur_variance_min: float = DEFAULT_BLUR_VARIANCE_MIN,
    phash_size: int = DEFAULT_PHASH_SIZE,
    phash_max_distance: int = DEFAULT_PHASH_MAX_DISTANCE,
    debug_rejects_to: Path | str | None = None,
    skip_missing: bool = True,
) -> list[dict[str, object]]:
    """
    Clean slots: one verdict from the ``full`` image; dedupe within ``(game, source)``.

    Visit order per source: ``recorded_start_utc`` (empty last), ``clip_key``, ``bucket``.
    Quarantined slots reject as ``manual:<reason>`` and never enter the kept hash set.
    """
    data_root = Path(data_root)
    quarantine = dict(quarantine or {})
    debug_root = Path(debug_rejects_to) if debug_rejects_to else None
    if debug_root is not None:
        debug_root.mkdir(parents=True, exist_ok=True)

    # Dedupe state is per (game, source); visit order is independent of input order.
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for raw in slots:
        row = {k: str(raw.get(k, "")) for k in SLOTS_CSV_COLUMNS}
        groups.setdefault((row["game"], row["source"]), []).append(row)

    results_by_id: dict[str, dict[str, object]] = {}

    for (_game, _source), group_rows in sorted(groups.items()):
        ordered = sorted(group_rows, key=lambda r: _slot_visit_key(r, clips))
        kept_hashes: list[int] = []
        kept_ids: list[str] = []

        for row in ordered:
            slot_id = row["slot_id"]
            full_rel = row["path_full"]
            full_path = data_root / full_rel
            luma_mean: float | None = None
            luma_std: float | None = None
            edge_var: float | None = None
            ahash_value: int | None = None
            reject_reason = ""
            dup_of = ""
            keep = True

            if slot_id in quarantine:
                keep = False
                reject_reason = f"manual:{quarantine[slot_id]}"

            if not full_path.is_file():
                if not skip_missing and slot_id not in quarantine:
                    raise FileNotFoundError(f"frame not found: {full_path}")
                if keep:
                    keep = False
                    reject_reason = "missing_file"
            else:
                with Image.open(full_path) as im:
                    im.load()
                    image = im.convert("RGB")
                    luma_mean, luma_std = luma_stats(image)
                    edge_var = laplacian_variance(image)
                    ahash_value = average_hash(image, phash_size)

                if keep:
                    assert luma_mean is not None and luma_std is not None
                    if luma_mean <= black_mean_max and luma_std <= black_std_max:
                        keep = False
                        reject_reason = "black"
                    elif edge_var is not None and edge_var < blur_variance_min:
                        keep = False
                        reject_reason = "blur"
                    else:
                        assert ahash_value is not None
                        match_idx = None
                        for i, prev_h in enumerate(kept_hashes):
                            dist = hamming_distance(ahash_value, prev_h)
                            if dist <= phash_max_distance:
                                match_idx = i
                                break
                        if match_idx is not None:
                            keep = False
                            reject_reason = "duplicate"
                            dup_of = kept_ids[match_idx]

            if keep and ahash_value is not None:
                kept_hashes.append(ahash_value)
                kept_ids.append(slot_id)

            if not keep and debug_root is not None and full_path.is_file():
                reason_dir = reject_reason.split(":", 1)[0] if reject_reason else "rejected"
                # Keep manual reasons under manual/ for a readable contact sheet.
                if reject_reason.startswith("manual:"):
                    reason_dir = "manual"
                _copy_reject_debug(
                    full_path,
                    debug_root,
                    reason=reason_dir,
                    frame_id=slot_id,
                    matched_frame_id=dup_of,
                )

            results_by_id[slot_id] = {
                **row,
                "keep": keep,
                "reject_reason": reject_reason,
                "dup_of": dup_of,
                "luma_mean": _format_metric(luma_mean),
                "luma_std": _format_metric(luma_std),
                "edge_var": _format_metric(edge_var),
                "ahash": _ahash_hex(ahash_value, phash_size) if ahash_value is not None else "",
            }

    # Deterministic table order (matches derive-frames: game, source, clip_key, bucket).
    ordered_ids = [
        r["slot_id"]
        for _, group_rows in sorted(groups.items())
        for r in sorted(
            group_rows,
            key=lambda row: (row["clip_key"], int(row["bucket"]) if row["bucket"].isdigit() else 0),
        )
    ]
    return [results_by_id[sid] for sid in ordered_ids]


def write_slots_clean(
    rows: Sequence[Mapping[str, object]],
    output_dir: Path | str,
) -> tuple[Path, Path]:
    """Write ``slots_clean.csv`` and ``slots_clean.json`` under ``output_dir``."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "slots_clean.csv"
    json_path = output_dir / "slots_clean.json"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(SLOTS_CLEAN_COLUMNS))
        writer.writeheader()
        for row in rows:
            csv_row = {k: row.get(k, "") for k in SLOTS_CLEAN_COLUMNS}
            keep = row.get("keep")
            csv_row["keep"] = "true" if keep is True or keep == "true" else "false"
            writer.writerow(csv_row)

    json_rows: list[dict[str, object]] = []
    for row in rows:
        item = {k: row.get(k, "") for k in SLOTS_CLEAN_COLUMNS}
        keep = row.get("keep")
        item["keep"] = keep is True or keep == "true"
        json_rows.append(item)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(json_rows, f, indent=2)

    return csv_path, json_path


def write_slots_clean_summary(
    rows: Sequence[Mapping[str, object]],
    output_dir: Path | str,
    *,
    thresholds: Mapping[str, float | int],
    debug: bool = False,
    debug_rejects_dir: str = "",
) -> Path:
    """Write ``clean_summary.json`` for a slot-mode run."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    kept = sum(1 for r in rows if r.get("keep") is True or r.get("keep") == "true")
    rejected = len(rows) - kept
    by_reason: dict[str, int] = {}
    for r in rows:
        if r.get("keep") is True or r.get("keep") == "true":
            continue
        reason = str(r.get("reject_reason") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1

    summary = {
        "mode": "slots",
        "input_count": len(rows),
        "kept_count": kept,
        "rejected_count": rejected,
        "rejects_by_reason": by_reason,
        "by_game": _count_nested(rows, "game"),
        "by_source": _count_nested(rows, "source"),
        "thresholds": dict(thresholds),
        "debug": debug,
        "debug_rejects_dir": debug_rejects_dir,
    }
    path = output_dir / "clean_summary.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path


def clean_slots_table(
    slots_path: Path | str,
    *,
    data_root: Path | str | None = None,
    clips_index_path: Path | str | None = None,
    quarantine_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    debug: bool = False,
    black_mean_max: float = DEFAULT_BLACK_MEAN_MAX,
    black_std_max: float = DEFAULT_BLACK_STD_MAX,
    blur_variance_min: float = DEFAULT_BLUR_VARIANCE_MIN,
    phash_size: int = DEFAULT_PHASH_SIZE,
    phash_max_distance: int = DEFAULT_PHASH_MAX_DISTANCE,
    skip_missing: bool = True,
) -> list[dict[str, object]]:
    """
    Load slot + clip tables, clean, write ``slots_clean`` + summary.

    Paths inside ``slots.csv`` are relative to ``data_root`` (default: parent of
    the manifests directory that holds ``slots.csv``).
    """
    slots_path = Path(slots_path)
    manifests_dir = slots_path.parent
    if data_root is None:
        # slots.csv lives at <data_root>/manifests/slots.csv
        data_root = manifests_dir.parent if manifests_dir.name == "manifests" else Path("data")
    else:
        data_root = Path(data_root)
    if clips_index_path is None:
        clips_index_path = manifests_dir / "clips_index.csv"
    if quarantine_path is None:
        quarantine_path = manifests_dir / "quarantine.csv"
    if output_dir is None:
        output_dir = manifests_dir
    output_dir = Path(output_dir)

    slots = load_slots_csv(slots_path)
    clips = load_clips_index(clips_index_path)
    quarantine = load_quarantine(quarantine_path)

    debug_to = data_root / "frames" / "_rejected" if debug else None
    rows = clean_slots(
        slots,
        clips,
        data_root=data_root,
        quarantine=quarantine,
        black_mean_max=black_mean_max,
        black_std_max=black_std_max,
        blur_variance_min=blur_variance_min,
        phash_size=phash_size,
        phash_max_distance=phash_max_distance,
        debug_rejects_to=debug_to,
        skip_missing=skip_missing,
    )
    write_slots_clean(rows, output_dir)
    write_slots_clean_summary(
        rows,
        output_dir,
        thresholds={
            "black_mean_max": black_mean_max,
            "black_std_max": black_std_max,
            "blur_variance_min": blur_variance_min,
            "phash_size": phash_size,
            "phash_max_distance": phash_max_distance,
        },
        debug=debug_to is not None,
        debug_rejects_dir=str(debug_to) if debug_to else "",
    )
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Clean extracted gameplay frames (manifest or slot mode)."
    )
    p.add_argument(
        "manifest",
        type=Path,
        nargs="?",
        default=None,
        help="frames_manifest.csv or .json (manifest mode)",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="output directory for manifest mode",
    )
    p.add_argument(
        "--slots",
        type=Path,
        default=None,
        help="slots.csv path (slot mode; writes slots_clean next to it)",
    )
    p.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="data root for resolving relative frame paths (slot mode; "
        "default: parent of the manifests directory)",
    )
    p.add_argument("--no-copy", action="store_true", help="Do not copy kept images (manifest mode)")
    p.add_argument(
        "--debug",
        action="store_true",
        help="Copy rejected frames for visual audit "
        "(manifest: output_dir/rejected/; slots: data/frames/_rejected/)",
    )
    p.add_argument("--black-mean-max", type=float, default=DEFAULT_BLACK_MEAN_MAX)
    p.add_argument("--black-std-max", type=float, default=DEFAULT_BLACK_STD_MAX)
    p.add_argument("--blur-variance-min", type=float, default=DEFAULT_BLUR_VARIANCE_MIN)
    p.add_argument("--phash-size", type=int, default=DEFAULT_PHASH_SIZE)
    p.add_argument("--phash-max-distance", type=int, default=DEFAULT_PHASH_MAX_DISTANCE)
    p.add_argument(
        "--skip-missing",
        action="store_true",
        help="Reject missing files instead of raising (manifest mode; "
        "slot mode always rejects missing as missing_file)",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)

    if args.slots is not None:
        if args.manifest is not None or args.output_dir is not None:
            print("slot mode uses --slots only; do not pass manifest or -o", flush=True)
            return 2
        rows = clean_slots_table(
            args.slots,
            data_root=args.data_root,
            debug=args.debug,
            black_mean_max=args.black_mean_max,
            black_std_max=args.black_std_max,
            blur_variance_min=args.blur_variance_min,
            phash_size=args.phash_size,
            phash_max_distance=args.phash_max_distance,
        )
        kept = sum(1 for r in rows if r["keep"] is True)
        out_dir = Path(args.slots).parent
        print(
            f"kept {kept} / rejected {len(rows) - kept} "
            f"-> {out_dir / 'slots_clean.csv'}"
            + (" [debug]" if args.debug else "")
        )
        return 0

    if args.manifest is None or args.output_dir is None:
        print("manifest mode requires MANIFEST and -o/--output-dir", flush=True)
        return 2

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
