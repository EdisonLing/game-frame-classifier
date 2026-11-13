"""Unit tests for frame cleaner heuristics (synthetic images, no ffmpeg)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from game_frame_classifier.frame_cleaner import (
    FrameRecord,
    average_hash,
    clean_frames,
    hamming_distance,
    is_mostly_black,
    is_too_blurry,
    laplacian_variance,
)


def _solid(path: Path, color: tuple[int, int, int], size=(256, 144)) -> Path:
    Image.new("RGB", size, color).save(path, quality=95)
    return path


def _sharp_pattern(
    path: Path,
    size=(256, 144),
    bg=(20, 20, 20),
    line_a=(240, 240, 240),
    line_b=(200, 40, 40),
    step: int = 8,
) -> Path:
    im = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(im)
    for x in range(0, size[0], step):
        draw.line([(x, 0), (x, size[1])], fill=line_a, width=2)
    for y in range(0, size[1], step):
        draw.line([(0, y), (size[0], y)], fill=line_b, width=2)
    im.save(path, quality=95)
    return path


def _blurry(path: Path, size=(256, 144)) -> Path:
    """Soft gradient — very low edge energy."""
    im = Image.new("RGB", size)
    pixels = im.load()
    assert pixels is not None
    for y in range(size[1]):
        for x in range(size[0]):
            v = int(40 + 80 * (x / max(size[0] - 1, 1)))
            pixels[x, y] = (v, v, v)
    im = im.filter(ImageFilter.GaussianBlur(radius=8))
    im.save(path, quality=95)
    return path


def _rec(path: Path, frame_id: str = "f0") -> FrameRecord:
    return FrameRecord(
        frame_id=frame_id,
        video_id="vid",
        game="Valorant",
        timestamp_s=0.0,
        path=str(path),
        width=256,
        height=144,
        source_video="vid.mp4",
    )


def test_is_mostly_black_true_and_false(tmp_path: Path) -> None:
    black = Image.open(_solid(tmp_path / "black.jpg", (0, 0, 0)))
    red = Image.open(_solid(tmp_path / "red.jpg", (200, 30, 30)))
    assert is_mostly_black(black) is True
    assert is_mostly_black(red) is False


def test_blurry_vs_sharp(tmp_path: Path) -> None:
    sharp = Image.open(_sharp_pattern(tmp_path / "sharp.jpg"))
    soft = Image.open(_blurry(tmp_path / "soft.jpg"))
    assert laplacian_variance(sharp) > laplacian_variance(soft)
    assert is_too_blurry(soft) is True
    assert is_too_blurry(sharp) is False


def test_average_hash_near_duplicates(tmp_path: Path) -> None:
    a = Image.open(_sharp_pattern(tmp_path / "a.jpg"))
    b_path = tmp_path / "b.jpg"
    # Identical content → distance 0
    a.save(b_path, quality=95)
    b = Image.open(b_path)
    other = Image.open(_solid(tmp_path / "other.jpg", (0, 180, 0)))

    ha, hb, ho = average_hash(a), average_hash(b), average_hash(other)
    assert hamming_distance(ha, hb) <= 2
    assert hamming_distance(ha, ho) > 6


def test_clean_frames_drops_black_blur_and_dupes(tmp_path: Path) -> None:
    paths = {
        "keep1": _sharp_pattern(tmp_path / "keep1.jpg"),
        "black": _solid(tmp_path / "black.jpg", (0, 0, 0)),
        "blur": _blurry(tmp_path / "blur.jpg"),
        "dup": _sharp_pattern(tmp_path / "dup.jpg"),  # near-identical to keep1
        "keep2": _sharp_pattern(
            tmp_path / "keep2.jpg",
            bg=(10, 40, 80),
            line_a=(0, 255, 180),
            line_b=(255, 200, 0),
            step=11,
        ),
    }

    records = [
        _rec(paths["keep1"], "k1"),
        _rec(paths["black"], "blk"),
        _rec(paths["blur"], "blr"),
        _rec(paths["dup"], "dup"),
        _rec(paths["keep2"], "k2"),
    ]
    result = clean_frames(records)
    kept_ids = [r.frame_id for r in result.kept]
    reasons = {r.frame_id: r.reason for r in result.rejected}

    assert kept_ids == ["k1", "k2"]
    assert reasons["blk"] == "black"
    assert reasons["blr"] == "blur"
    assert reasons["dup"] == "duplicate"
    assert all(r.detail for r in result.rejected)


def test_clean_frames_copy_kept(tmp_path: Path) -> None:
    src = _sharp_pattern(tmp_path / "src.jpg")
    dest = tmp_path / "out_kept"
    result = clean_frames([_rec(src, "k1")], copy_kept_to=dest)
    assert len(result.kept) == 1
    assert Path(result.kept[0].path).is_file()
    assert Path(result.kept[0].path).parent == dest.resolve()


def test_clean_frames_debug_keeps_rejects_and_match_id(tmp_path: Path) -> None:
    keep = _sharp_pattern(tmp_path / "keep.jpg")
    black = _solid(tmp_path / "black.jpg", (0, 0, 0))
    dup = _sharp_pattern(tmp_path / "dup.jpg")
    debug_root = tmp_path / "rejected"

    result = clean_frames(
        [_rec(keep, "k1"), _rec(black, "blk"), _rec(dup, "dup")],
        debug_rejects_to=debug_root,
    )
    by_id = {r.frame_id: r for r in result.rejected}
    assert by_id["blk"].reason == "black"
    assert by_id["blk"].metric_name == "luma_mean_std"
    assert Path(by_id["blk"].debug_path).is_file()
    assert "black" in by_id["blk"].debug_path

    assert by_id["dup"].reason == "duplicate"
    assert by_id["dup"].matched_frame_id == "k1"
    assert by_id["dup"].hamming_distance != ""
    assert Path(by_id["dup"].debug_path).is_file()
    assert "dup_of_k1" in Path(by_id["dup"].debug_path).name
