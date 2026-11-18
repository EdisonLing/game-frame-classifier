"""Unit tests for frame cleaner heuristics (synthetic images, no ffmpeg)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from game_frame_classifier.frame_cleaner import (
    FrameRecord,
    average_hash,
    clean_frames,
    clean_slots,
    hamming_distance,
    is_mostly_black,
    is_too_blurry,
    laplacian_variance,
)
from tests.helpers import clean_slots_fixtures as fx


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


def _slot_tree_black_blur(tmp_path: Path) -> tuple[Path, list[dict[str, str]], dict[str, dict[str, str]]]:
    data_root = tmp_path / "data"
    game, source, clip = "Valorant", "me", "caaaaaaaaaaaa"
    black = fx.write_slot_images(
        data_root,
        game=game,
        source=source,
        clip_key=clip,
        bucket=0,
        full=fx.solid_rgb((0, 0, 0)),
    )
    sharp = fx.write_slot_images(
        data_root,
        game=game,
        source=source,
        clip_key=clip,
        bucket=1,
        full=fx.sharp_pattern(),
    )
    soft = fx.write_slot_images(
        data_root,
        game=game,
        source=source,
        clip_key=clip,
        bucket=2,
        full=fx.blurry_gradient(),
    )
    slots = [black, sharp, soft]
    clips = {
        clip: fx.clip_index_row(
            clip_key=clip, game=game, source=source, recorded_start_utc="2026-01-01T00:00:00Z", slots=3
        )
    }
    return data_root, slots, clips


def test_slot_verdict_from_full_applies_to_both_tiers(tmp_path: Path) -> None:
    """Black/blur measured on full; keep/reject is one verdict for the slot."""
    data_root, slots, clips = _slot_tree_black_blur(tmp_path)
    # Deliberately make path_low a sharp image even when full is black.
    black_row = slots[0]
    fx.save_jpg(data_root / black_row["path_low"], fx.sharp_pattern())

    rows = clean_slots(slots, clips, data_root=data_root)
    by_id = {r["slot_id"]: r for r in rows}
    assert by_id[black_row["slot_id"]]["keep"] is False
    assert by_id[black_row["slot_id"]]["reject_reason"] == "black"
    sharp_id = slots[1]["slot_id"]
    soft_id = slots[2]["slot_id"]
    assert by_id[sharp_id]["keep"] is True
    assert by_id[soft_id]["keep"] is False
    assert by_id[soft_id]["reject_reason"] == "blur"
    # Both tier paths remain on the row regardless of verdict.
    for row in rows:
        assert (data_root / str(row["path_full"])).is_file()
        assert (data_root / str(row["path_low"])).is_file()


def test_slot_duplicate_across_two_clips_same_source(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    game, source = "CS2", "contributor_alex"
    early = "cearly0000000"
    late = "clate00000000"
    pattern = fx.sharp_pattern()
    slot_a = fx.write_slot_images(
        data_root, game=game, source=source, clip_key=early, bucket=3, full=pattern
    )
    slot_b = fx.write_slot_images(
        data_root, game=game, source=source, clip_key=late, bucket=1, full=pattern.copy()
    )
    clips = {
        early: fx.clip_index_row(
            clip_key=early, game=game, source=source, recorded_start_utc="2026-02-01T10:00:00Z"
        ),
        late: fx.clip_index_row(
            clip_key=late, game=game, source=source, recorded_start_utc="2026-02-01T11:00:00Z"
        ),
    }
    rows = clean_slots([slot_b, slot_a], clips, data_root=data_root)
    by_id = {r["slot_id"]: r for r in rows}
    assert by_id[slot_a["slot_id"]]["keep"] is True
    assert by_id[slot_b["slot_id"]]["keep"] is False
    assert by_id[slot_b["slot_id"]]["reject_reason"] == "duplicate"
    assert by_id[slot_b["slot_id"]]["dup_of"] == slot_a["slot_id"]


def test_slot_identical_frames_different_sources_both_kept(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    game = "Minecraft"
    pattern = fx.sharp_pattern()
    a = fx.write_slot_images(
        data_root, game=game, source="me", clip_key="caaaaaaaaaaaa", bucket=0, full=pattern
    )
    b = fx.write_slot_images(
        data_root,
        game=game,
        source="contributor_bob",
        clip_key="cbbbbbbbbbbbb",
        bucket=0,
        full=pattern.copy(),
    )
    clips = {
        "caaaaaaaaaaaa": fx.clip_index_row(
            clip_key="caaaaaaaaaaaa", game=game, source="me", recorded_start_utc="2026-03-01T00:00:00Z"
        ),
        "cbbbbbbbbbbbb": fx.clip_index_row(
            clip_key="cbbbbbbbbbbbb",
            game=game,
            source="contributor_bob",
            recorded_start_utc="2026-03-01T00:00:00Z",
        ),
    }
    rows = clean_slots([a, b], clips, data_root=data_root)
    assert all(r["keep"] is True for r in rows)
    assert all(r["reject_reason"] == "" for r in rows)


def test_slot_quarantine_manual_reason(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    game, source, clip = "Overwatch_2", "me", "cquarantine001"
    slot = fx.write_slot_images(
        data_root, game=game, source=source, clip_key=clip, bucket=5, full=fx.sharp_pattern()
    )
    clips = {
        clip: fx.clip_index_row(
            clip_key=clip, game=game, source=source, recorded_start_utc="2026-04-01T00:00:00Z"
        )
    }
    rows = clean_slots(
        [slot],
        clips,
        data_root=data_root,
        quarantine={slot["slot_id"]: "lobby"},
    )
    assert len(rows) == 1
    assert rows[0]["keep"] is False
    assert rows[0]["reject_reason"] == "manual:lobby"


def test_slot_visit_order_independent_of_input_row_order(tmp_path: Path) -> None:
    """Earlier recorded_start_utc wins even when that row is last in the CSV."""
    data_root = tmp_path / "data"
    game, source = "League_of_Legends", "me"
    early_clip = "cearlyclip000"
    late_clip = "clateclip0000"
    pattern = fx.sharp_pattern(step=9, bg=(30, 10, 60))
    early = fx.write_slot_images(
        data_root, game=game, source=source, clip_key=early_clip, bucket=9, full=pattern
    )
    late = fx.write_slot_images(
        data_root, game=game, source=source, clip_key=late_clip, bucket=0, full=pattern.copy()
    )
    clips = {
        early_clip: fx.clip_index_row(
            clip_key=early_clip,
            game=game,
            source=source,
            recorded_start_utc="2026-05-01T08:00:00Z",
        ),
        late_clip: fx.clip_index_row(
            clip_key=late_clip,
            game=game,
            source=source,
            recorded_start_utc="2026-05-01T09:00:00Z",
        ),
    }
    # Input order puts the later clip first.
    rows = clean_slots([late, early], clips, data_root=data_root)
    by_id = {r["slot_id"]: r for r in rows}
    assert by_id[early["slot_id"]]["keep"] is True
    assert by_id[late["slot_id"]]["reject_reason"] == "duplicate"
    assert by_id[late["slot_id"]]["dup_of"] == early["slot_id"]

    # Empty recorded_start_utc sorts after dated clips.
    undated_clip = "cundated00000"
    undated = fx.write_slot_images(
        data_root, game=game, source=source, clip_key=undated_clip, bucket=0, full=pattern.copy()
    )
    clips[undated_clip] = fx.clip_index_row(
        clip_key=undated_clip, game=game, source=source, recorded_start_utc=""
    )
    rows2 = clean_slots([undated, late, early], clips, data_root=data_root)
    by_id2 = {r["slot_id"]: r for r in rows2}
    assert by_id2[early["slot_id"]]["keep"] is True
    assert by_id2[undated["slot_id"]]["reject_reason"] == "duplicate"
    assert by_id2[undated["slot_id"]]["dup_of"] == early["slot_id"]


def test_slot_with_missing_low_image_is_rejected_and_quick_mode_slot_is_kept(tmp_path):
    data_root = tmp_path / "data"
    paired = fx.write_slot_images(
        data_root, game="Valorant", source="tester", clip_key="c000000000001", bucket=0,
        full=fx.sharp_pattern,
    )
    (data_root / paired["path_low"]).unlink()
    quick = fx.write_slot_images(
        data_root, game="Valorant", source="tester", clip_key="c000000000002", bucket=0,
        full=fx.sharp_pattern,
    )
    (data_root / quick["path_low"]).unlink()
    quick["path_low"] = ""
    clips: dict[str, dict[str, str]] = {}  # no recording times: visit order falls back to clip_key
    rows = {r["slot_id"]: r for r in clean_slots([paired, quick], clips, data_root=data_root)}
    assert rows[paired["slot_id"]]["keep"] is False
    assert rows[paired["slot_id"]]["reject_reason"] == "missing_file"
    assert rows[quick["slot_id"]]["reject_reason"] != "missing_file"
