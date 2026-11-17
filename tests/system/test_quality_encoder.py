"""System tests: video CRF → extract quality tiers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from game_frame_classifier.quality_encoder import (
    encode_video_quality_tiers,
    reencode_video_crf,
)
from tests.helpers.ffmpeg_fixtures import make_color_video, requires_ffmpeg


@requires_ffmpeg
def test_reencode_video_crf_writes_file(tmp_path: Path) -> None:
    src = make_color_video(
        tmp_path / "src.mp4", duration_s=1.0, width=320, height=180, fps=30
    )
    dest = tmp_path / "out.mp4"
    out = reencode_video_crf(src, dest, crf=28)
    assert out.is_file()
    assert out.stat().st_size > 0


@requires_ffmpeg
def test_encode_video_quality_tiers(tmp_path: Path) -> None:
    src = make_color_video(
        tmp_path / "src.mp4",
        duration_s=2.0,
        width=640,
        height=360,
        fps=30,
        color="red",
    )
    out = tmp_path / "quality"
    by_tier = encode_video_quality_tiers(
        src,
        out,
        game="Valorant",
        video_id="src",
        tiers=("full", "medium", "low"),
        interval_s=1.0,
    )
    assert set(by_tier) == {"full", "medium", "low"}
    assert all(len(v) >= 1 for v in by_tier.values())
    assert by_tier["medium"][0].crf == 38
    assert by_tier["low"][0].quality_tier == "low"
    assert (out / "medium" / "frames_manifest.csv").is_file()
    summary = json.loads((out / "quality_summary.json").read_text(encoding="utf-8"))
    assert summary["method"] == "video_crf_then_extract"
    assert summary["tiers"]["low"]["crf"] == 45

    with Image.open(by_tier["full"][0].path) as im:
        assert im.size == (256, 144)


@requires_ffmpeg
def test_encode_video_rejects_bad_tier(tmp_path: Path) -> None:
    src = make_color_video(tmp_path / "src.mp4", duration_s=1.0)
    with pytest.raises(ValueError, match="unknown quality tier"):
        encode_video_quality_tiers(
            src,
            tmp_path / "out",
            game="CS2",
            tiers=("full", "nope"),
        )


@pytest.mark.personal
@requires_ffmpeg
def test_encode_personal_clip_slice_if_present() -> None:
    root = Path(__file__).resolve().parents[2]
    raw = root / "data" / "raw"
    videos = sorted(raw.rglob("*.mp4")) if raw.is_dir() else []
    if not videos:
        pytest.skip("no data/raw videos")
    out = root / "data" / "frames" / "personal_quality_smoke"
    by_tier = encode_video_quality_tiers(
        videos[0],
        out,
        game="Valorant",
        tiers=("full", "medium", "low"),
        max_duration_s=15.0,
        interval_s=5.0,
    )
    assert len(by_tier["full"]) >= 1
    assert (out / "quality_summary.json").is_file()
