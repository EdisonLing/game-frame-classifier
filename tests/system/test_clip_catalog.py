"""System tests: real ffprobe + synthetic videos under a fake raw tree."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from game_frame_classifier.clip_catalog import build_catalog, scan_raw_tree
from tests.helpers.ffmpeg_fixtures import make_color_video, requires_ffmpeg


@requires_ffmpeg
def test_catalog_synthetic_tree(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    video_path = raw / "Valorant" / "edison" / "smoke.mp4"
    make_color_video(video_path, duration_s=2.0, width=320, height=180, color="red")

    out = tmp_path / "manifests"
    records = build_catalog(raw, out)

    assert len(records) == 1
    rec = records[0]
    assert rec.clip_id == "Valorant/edison/smoke.mp4"
    assert rec.game == "Valorant"
    assert rec.source == "edison"
    assert rec.filename == "smoke.mp4"
    assert Path(rec.path) == video_path.resolve()
    assert Path(rec.path).is_file()
    assert abs(rec.duration_s - 2.0) < 0.15
    assert rec.width == 320
    assert rec.height == 180

    csv_path = out / "clips.csv"
    json_path = out / "clips.json"
    assert csv_path.is_file() and json_path.is_file()

    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["clip_id"] == "Valorant/edison/smoke.mp4"
    assert rows[0]["game"] == "Valorant"
    assert int(rows[0]["width"]) == 320

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["filename"] == "smoke.mp4"


@requires_ffmpeg
def test_catalog_rerun_same_clip_ids(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    make_color_video(
        raw / "Minecraft" / "edison" / "a.mp4",
        duration_s=1.0,
        width=160,
        height=90,
    )
    make_color_video(
        raw / "Minecraft" / "friend_b" / "b.mp4",
        duration_s=1.0,
        width=160,
        height=90,
        color="blue",
    )

    first = scan_raw_tree(raw)
    second = scan_raw_tree(raw)
    assert [r.clip_id for r in first] == [r.clip_id for r in second]
    assert {r.clip_id for r in first} == {
        "Minecraft/edison/a.mp4",
        "Minecraft/friend_b/b.mp4",
    }


@requires_ffmpeg
def test_catalog_unreadable_video_raises(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    bad = raw / "CS2" / "edison" / "broken.mp4"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not a real video")

    import pytest

    with pytest.raises(RuntimeError, match="ffprobe failed|no video stream|incomplete"):
        scan_raw_tree(raw)
