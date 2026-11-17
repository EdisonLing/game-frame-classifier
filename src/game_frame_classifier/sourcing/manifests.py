"""Clip and frame table columns and CSV + JSON writers (Frame Export Kit spec §6.3, §6.4)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

CLIP_COLUMNS = (
    "clip_key", "clip_sha256", "quick_id", "status", "status_detail",
    "original_filename", "original_relpath", "aliases", "file_bytes",
    "file_mtime_utc", "file_mtime_local", "file_created_utc", "container_creation_utc",
    "filename_datetime_local", "recorded_start_utc", "recorded_start_source",
    "duration_s", "start_time_s", "container", "video_codec", "profile", "pix_fmt",
    "bit_depth", "bitrate_bps", "encoder_tag", "width", "height", "sar", "rotation",
    "avg_fps", "r_fps", "nominal_fps", "vfr", "color_range", "color_space",
    "color_transfer", "color_primaries", "hdr", "tonemapped", "even_cropped",
    "audio_streams", "label_hint", "label_hint_conflict", "expected_slots", "slots",
    "unpaired_dropped", "max_align_err_s", "x264_core", "low_encoder", "gpu_fallback", "wall_s",
)
FRAME_COLUMNS = (
    "image_id", "slot_id", "clip_key", "tier", "crf", "encoder", "encoder_rc", "bucket",
    "target_time_s", "pts_time_s", "rel_path", "width", "height", "bytes", "sha256",
)


def blank_clip_row() -> dict[str, Any]:
    row: dict[str, Any] = {column: "" for column in CLIP_COLUMNS}
    row["aliases"] = []
    return row


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "|".join(str(v) for v in value)
    return value


def write_json(obj: Any, path: Path) -> None:
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_table(rows: list[dict[str, Any]], columns: Iterable[str], csv_path: Path, json_path: Path) -> None:
    columns = list(columns)
    allowed = set(columns)
    for row in rows:
        extra = set(row) - allowed
        if extra:
            raise ValueError(f"unexpected columns: {sorted(extra)}")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: _csv_value(row.get(c, "")) for c in columns})
    write_json([{c: row.get(c, "") for c in columns} for row in rows], json_path)
