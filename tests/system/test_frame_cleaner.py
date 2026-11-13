"""System tests: cleaner on synthetic manifests + optional personal extract output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

from game_frame_classifier.frame_cleaner import (
    FrameRecord,
    clean_manifest,
    load_frame_manifest,
    write_frame_manifest,
)


def _write_jpg(path: Path, builder) -> Path:
    im = builder()
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=95)
    return path


def _sharp(step: int = 8, bg=(20, 20, 40), line=(240, 240, 240)) -> Image.Image:
    size = (256, 144)
    im = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(im)
    for x in range(0, size[0], step):
        draw.line([(x, 0), (x, size[1])], fill=line, width=2)
    for y in range(0, size[1], step * 2):
        draw.line([(0, y), (size[0], y)], fill=(200, 40, 40), width=2)
    return im


def _black() -> Image.Image:
    return Image.new("RGB", (256, 144), (0, 0, 0))


def _blur() -> Image.Image:
    im = Image.new("RGB", (256, 144), (80, 80, 80))
    return im.filter(ImageFilter.GaussianBlur(radius=10))


def test_clean_manifest_end_to_end(tmp_path: Path) -> None:
    frames = tmp_path / "raw"
    keep1 = _write_jpg(frames / "keep1.jpg", _sharp)
    black = _write_jpg(frames / "black.jpg", _black)
    blur = _write_jpg(frames / "blur.jpg", _blur)
    dup = _write_jpg(frames / "dup.jpg", _sharp)
    keep2 = _write_jpg(
        frames / "keep2.jpg",
        lambda: _sharp(step=13, bg=(10, 50, 90), line=(0, 255, 180)),
    )

    records = [
        FrameRecord("k1", "v", "Minecraft", 0.0, str(keep1), 256, 144, "v.mp4"),
        FrameRecord("blk", "v", "Minecraft", 5.0, str(black), 256, 144, "v.mp4"),
        FrameRecord("blr", "v", "Minecraft", 10.0, str(blur), 256, 144, "v.mp4"),
        FrameRecord("dup", "v", "Minecraft", 15.0, str(dup), 256, 144, "v.mp4"),
        FrameRecord("k2", "v", "Minecraft", 20.0, str(keep2), 256, 144, "v.mp4"),
    ]
    manifest_dir = tmp_path / "in"
    write_frame_manifest(records, manifest_dir)

    out = tmp_path / "cleaned"
    result = clean_manifest(manifest_dir / "frames_manifest.csv", out)

    assert [r.frame_id for r in result.kept] == ["k1", "k2"]
    assert {r.reason for r in result.rejected} == {"black", "blur", "duplicate"}

    kept_manifest = load_frame_manifest(out / "frames_manifest.json")
    assert len(kept_manifest) == 2
    assert (out / "rejects.csv").is_file()
    summary = json.loads((out / "clean_summary.json").read_text(encoding="utf-8"))
    assert summary["kept_count"] == 2
    assert summary["rejected_count"] == 3
    assert summary["rejects_by_reason"]["black"] == 1
    assert (out / "kept" / "keep1.jpg").is_file()


def test_clean_manifest_debug_mode(tmp_path: Path) -> None:
    frames = tmp_path / "raw"
    keep1 = _write_jpg(frames / "keep1.jpg", _sharp)
    black = _write_jpg(frames / "black.jpg", _black)
    dup = _write_jpg(frames / "dup.jpg", _sharp)
    records = [
        FrameRecord("k1", "v", "Valorant", 0.0, str(keep1), 256, 144, "v.mp4"),
        FrameRecord("blk", "v", "Valorant", 5.0, str(black), 256, 144, "v.mp4"),
        FrameRecord("dup", "v", "Valorant", 10.0, str(dup), 256, 144, "v.mp4"),
    ]
    manifest_dir = tmp_path / "in"
    write_frame_manifest(records, manifest_dir)
    out = tmp_path / "cleaned_dbg"
    result = clean_manifest(manifest_dir / "frames_manifest.csv", out, debug=True)

    assert (out / "rejected" / "black").is_dir()
    assert (out / "rejected" / "duplicate").is_dir()
    dup_rej = next(r for r in result.rejected if r.reason == "duplicate")
    assert dup_rej.matched_frame_id == "k1"
    assert Path(dup_rej.debug_path).is_file()
    summary = json.loads((out / "clean_summary.json").read_text(encoding="utf-8"))
    assert summary["debug"] is True


@pytest.mark.personal
def test_clean_personal_valorant_smoke_dir() -> None:
    """
    If extractor smoke output exists, cleaner should keep most real gameplay frames.
    """
    root = Path(__file__).resolve().parents[2]
    manifest = root / "data" / "frames" / "valorant_smoke" / "frames_manifest.csv"
    if not manifest.is_file():
        pytest.skip("data/frames/valorant_smoke not present — run extractor smoke first")

    out = root / "data" / "frames" / "valorant_smoke_cleaned"
    # Write under repo data/ so user can inspect; still gitignored via data/frames/
    result = clean_manifest(manifest, out)
    assert len(result.kept) >= 1
    # Smoke set is short distinct gameplay — expect few or no rejects
    assert len(result.kept) + len(result.rejected) == 4
    assert (out / "frames_manifest.csv").is_file()
    assert (out / "clean_summary.json").is_file()
