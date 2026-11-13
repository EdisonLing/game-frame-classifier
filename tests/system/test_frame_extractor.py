"""System tests: real ffmpeg + synthetic videos; optional personal clip."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from game_frame_classifier.frame_extractor import (
    extract_frames,
    planned_timestamps,
    probe_duration_s,
)
from tests.helpers.ffmpeg_fixtures import make_color_video, requires_ffmpeg, trim_video_copy


@requires_ffmpeg
def test_extract_synthetic_15s_every_5s(tmp_path: Path) -> None:
    video = make_color_video(tmp_path / "synth_15s.mp4", duration_s=15.0, color="blue")
    out = tmp_path / "frames"
    records = extract_frames(
        video,
        out,
        game="Minecraft",
        video_id="synth15",
        interval_s=5.0,
        width=256,
        height=144,
    )

    expected_ts = planned_timestamps(probe_duration_s(video), 5.0)
    assert len(expected_ts) == 3
    assert len(records) == 3
    assert [r.timestamp_s for r in records] == expected_ts
    assert all(r.game == "Minecraft" for r in records)
    assert all(r.video_id == "synth15" for r in records)
    assert all(r.width == 256 and r.height == 144 for r in records)

    for rec in records:
        path = Path(rec.path)
        assert path.is_file()
        with Image.open(path) as im:
            assert im.size == (256, 144)

    csv_path = out / "frames_manifest.csv"
    json_path = out / "frames_manifest.json"
    assert csv_path.is_file() and json_path.is_file()

    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert rows[0]["game"] == "Minecraft"

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data) == 3
    assert data[1]["timestamp_s"] == 5.0


@requires_ffmpeg
def test_extract_respects_max_duration(tmp_path: Path) -> None:
    video = make_color_video(tmp_path / "synth_30s.mp4", duration_s=30.0, color="green")
    out = tmp_path / "frames"
    records = extract_frames(
        video,
        out,
        game="CS2",
        video_id="cap10",
        interval_s=5.0,
        max_duration_s=10.0,
    )
    # duration window 10s → timestamps 0, 5
    assert [r.timestamp_s for r in records] == [0.0, 5.0]
    assert len(records) == 2


@requires_ffmpeg
def test_extract_missing_video_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        extract_frames(tmp_path / "nope.mp4", tmp_path / "out", game="Valorant")


@requires_ffmpeg
def test_extract_debug_keeps_raw_and_report(tmp_path: Path) -> None:
    video = make_color_video(tmp_path / "synth_15s.mp4", duration_s=15.0, color="purple")
    out = tmp_path / "frames_dbg"
    records = extract_frames(
        video,
        out,
        game="Valorant",
        video_id="dbg",
        interval_s=5.0,
        debug=True,
    )
    assert len(records) == 3
    dbg = out / "debug"
    assert (dbg / "extract_debug.json").is_file()
    assert (dbg / "extract_debug_frames.csv").is_file()
    raw_copies = list((dbg / "raw").glob("frame_*.jpg"))
    assert len(raw_copies) == 3
    payload = json.loads((dbg / "extract_debug.json").read_text(encoding="utf-8"))
    assert payload["planned_count"] == 3
    assert payload["extracted_count"] == 3
    assert payload["ffmpeg_cmd"]
    assert payload["planned_timestamps_s"] == [0.0, 5.0, 10.0]


@requires_ffmpeg
@pytest.mark.personal
def test_extract_personal_valorant_smoke(personal_video_path: Path, tmp_path: Path) -> None:
    """
    Local smoke on the dropped Valorant replay.

    Not required for CI: skipped automatically when the file is absent.
    Caps decode at 20s so a large local MP4 stays fast and scalable.
    Full-clip extraction is a manual/CLI step, not a unit of CI time.
    """
    out = tmp_path / "valorant_frames"
    smoke_s = 20.0
    # Stream-copy a short prefix so we never decode the full ~700MB drop in CI/smoke.
    clipped = trim_video_copy(
        personal_video_path,
        tmp_path / "valorant_smoke_20s.mp4",
        duration_s=smoke_s,
    )
    expected = planned_timestamps(min(smoke_s, probe_duration_s(clipped)), 5.0)

    records = extract_frames(
        clipped,
        out,
        game="Valorant",
        video_id="valorant_replay_smoke",
        interval_s=5.0,
        width=256,
        height=144,
    )

    assert abs(len(records) - len(expected)) <= 1
    assert len(records) >= 3
    assert [r.timestamp_s for r in records] == expected[: len(records)]
    assert all(r.game == "Valorant" for r in records)

    for rec in records:
        with Image.open(rec.path) as im:
            assert im.size == (256, 144)

    assert (out / "frames_manifest.csv").is_file()
