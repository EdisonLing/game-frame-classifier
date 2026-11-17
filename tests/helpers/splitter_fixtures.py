"""Synthetic manifest builders for dataset-splitter tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def write_split_config(path: Path, **overrides: object) -> Path:
    """Write a default test split policy and return its path."""
    config = {
        "schema": "gfc.split/1", "split_id": "v1", "seed": 360,
        "targets": {"train": 0.70, "val": 0.15, "test_session": 0.15},
        "session_gap_min": 30, "holdout_sources": {}, "max_source_share": 1.0,
        "test_design": "",
    }
    config.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def write_split_inputs(data_root: Path, clips: list[dict[str, object]], *, slots_per_clip: int = 2) -> None:
    """Write compatible clips_index and slots_clean test tables."""
    manifest_dir = data_root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    clip_columns = (
        "clip_key", "game", "source", "source_kind", "public_examples_ok",
        "recorded_start_utc", "recorded_start_source", "duration_s",
    )
    with (manifest_dir / "clips_index.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=clip_columns)
        writer.writeheader()
        for index, clip in enumerate(clips):
            row = {
                "clip_key": f"c{index:012x}", "game": "Valorant", "source": "source_a",
                "source_kind": "personal", "public_examples_ok": "true",
                "recorded_start_utc": "", "recorded_start_source": "",
                "duration_s": "60",
            }
            row.update(clip)
            writer.writerow(row)
            clip["clip_key"] = row["clip_key"]
    slot_columns = ("slot_id", "clip_key", "bucket", "target_time_s", "path_full", "path_low", "keep")
    with (manifest_dir / "slots_clean.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=slot_columns)
        writer.writeheader()
        for clip in clips:
            for bucket in range(slots_per_clip):
                key = str(clip["clip_key"])
                writer.writerow({
                    "slot_id": f"{key}:b{bucket:06d}", "clip_key": key, "bucket": bucket,
                    "target_time_s": bucket * 5, "path_full": f"frames/{key}/full.jpg",
                    "path_low": f"frames/{key}/low.jpg", "keep": "true",
                })
