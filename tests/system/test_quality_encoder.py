"""System tests: ffmpeg CRF round-trip on synthetic / optional personal frames."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from game_frame_classifier.frame_cleaner import FrameRecord, write_frame_manifest
from game_frame_classifier.quality_encoder import (
    degrade_frame_ffmpeg,
    encode_manifest,
)
from tests.helpers.ffmpeg_fixtures import requires_ffmpeg


def _sharp_frame(path: Path) -> Path:
    im = Image.new("RGB", (256, 144), (20, 30, 50))
    draw = ImageDraw.Draw(im)
    for x in range(0, 256, 8):
        draw.line([(x, 0), (x, 144)], fill=(240, 200, 40), width=2)
    for y in range(0, 144, 8):
        draw.line([(0, y), (256, y)], fill=(40, 180, 255), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=95)
    return path


@requires_ffmpeg
def test_degrade_low_smaller_than_full(tmp_path: Path) -> None:
    src = _sharp_frame(tmp_path / "src.jpg")
    full = degrade_frame_ffmpeg(src, tmp_path / "full.jpg", crf=0)
    low = degrade_frame_ffmpeg(src, tmp_path / "low.jpg", crf=38)
    assert full.is_file() and low.is_file()
    # CRF 0 is a byte copy; low should usually be smaller after re-encode.
    assert low.stat().st_size < full.stat().st_size
    with Image.open(low) as im:
        assert im.size == (256, 144)


@requires_ffmpeg
def test_encode_manifest_tiers(tmp_path: Path) -> None:
    src = _sharp_frame(tmp_path / "raw" / "f0.jpg")
    records = [
        FrameRecord("vid:00000", "vid", "Valorant", 0.0, str(src), 256, 144, "vid.mp4"),
    ]
    write_frame_manifest(records, tmp_path / "in")
    out = tmp_path / "quality"
    by_tier = encode_manifest(
        tmp_path / "in" / "frames_manifest.csv",
        out,
        tiers=("full", "medium", "low"),
    )
    assert set(by_tier) == {"full", "medium", "low"}
    assert all(len(v) == 1 for v in by_tier.values())
    assert by_tier["medium"][0].crf == 28
    assert by_tier["low"][0].quality_tier == "low"
    assert (out / "medium" / "frames_manifest.csv").is_file()
    summary = json.loads((out / "quality_summary.json").read_text(encoding="utf-8"))
    assert summary["input_count"] == 1
    assert summary["tiers"]["low"]["crf"] == 38


@requires_ffmpeg
def test_encode_manifest_rejects_bad_tier(tmp_path: Path) -> None:
    src = _sharp_frame(tmp_path / "raw" / "f0.jpg")
    write_frame_manifest(
        [FrameRecord("vid:00000", "vid", "CS2", 0.0, str(src), 256, 144, "vid.mp4")],
        tmp_path / "in",
    )
    with pytest.raises(ValueError, match="unknown quality tier"):
        encode_manifest(
            tmp_path / "in" / "frames_manifest.csv",
            tmp_path / "out",
            tiers=("full", "nope"),
        )


@pytest.mark.personal
@requires_ffmpeg
def test_encode_personal_valorant_smoke_if_present() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = root / "data" / "frames" / "valorant_smoke" / "frames_manifest.csv"
    if not manifest.is_file():
        pytest.skip("valorant_smoke extract not present")
    out = root / "data" / "frames" / "valorant_smoke_quality"
    by_tier = encode_manifest(manifest, out, tiers=("full", "medium", "low"))
    assert len(by_tier["low"]) == 4
    assert (out / "quality_summary.json").is_file()
