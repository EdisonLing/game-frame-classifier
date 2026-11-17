"""System tests: cleaner on synthetic manifests + optional personal extract output."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

from game_frame_classifier.frame_cleaner import (
    FrameRecord,
    clean_manifest,
    clean_slots_table,
    load_frame_manifest,
    main,
    write_frame_manifest,
)
from tests.helpers import clean_slots_fixtures as fx


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


def _build_slot_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """Derived tree with keep / black / blur / cross-clip dup / other-source twin."""
    data_root = tmp_path / "data"
    manifests = data_root / "manifests"
    game = "Valorant"
    source_a = "me"
    source_b = "contributor_alex"
    clip_early = "cearly0000000"
    clip_late = "clate00000000"
    clip_other = "cother0000000"

    keep = fx.write_slot_images(
        data_root,
        game=game,
        source=source_a,
        clip_key=clip_early,
        bucket=0,
        full=fx.sharp_pattern(),
    )
    black = fx.write_slot_images(
        data_root,
        game=game,
        source=source_a,
        clip_key=clip_early,
        bucket=1,
        full=fx.solid_rgb((0, 0, 0)),
    )
    blur = fx.write_slot_images(
        data_root,
        game=game,
        source=source_a,
        clip_key=clip_early,
        bucket=2,
        full=fx.blurry_gradient(),
    )
    dup = fx.write_slot_images(
        data_root,
        game=game,
        source=source_a,
        clip_key=clip_late,
        bucket=0,
        full=fx.sharp_pattern(),
    )
    other = fx.write_slot_images(
        data_root,
        game=game,
        source=source_b,
        clip_key=clip_other,
        bucket=0,
        full=fx.sharp_pattern(),
    )
    # Scramble input row order.
    slots = [dup, blur, other, black, keep]
    fx.write_slots_csv(manifests / "slots.csv", slots)
    fx.write_clips_index(
        manifests / "clips_index.csv",
        [
            fx.clip_index_row(
                clip_key=clip_early,
                game=game,
                source=source_a,
                recorded_start_utc="2026-06-01T10:00:00Z",
                slots=3,
            ),
            fx.clip_index_row(
                clip_key=clip_late,
                game=game,
                source=source_a,
                recorded_start_utc="2026-06-01T11:00:00Z",
                slots=1,
            ),
            fx.clip_index_row(
                clip_key=clip_other,
                game=game,
                source=source_b,
                recorded_start_utc="2026-06-01T10:00:00Z",
                slots=1,
            ),
        ],
    )
    expected = {
        keep["slot_id"]: "keep",
        black["slot_id"]: "black",
        blur["slot_id"]: "blur",
        dup["slot_id"]: "duplicate",
        other["slot_id"]: "keep",
    }
    return data_root, manifests / "slots.csv", expected


def test_clean_slots_table_end_to_end(tmp_path: Path) -> None:
    data_root, slots_csv, expected = _build_slot_fixture(tmp_path)
    rows = clean_slots_table(slots_csv, data_root=data_root)
    by_id = {str(r["slot_id"]): r for r in rows}
    assert set(by_id) == set(expected)
    for slot_id, want in expected.items():
        if want == "keep":
            assert by_id[slot_id]["keep"] is True
            assert by_id[slot_id]["reject_reason"] == ""
            assert (data_root / str(by_id[slot_id]["path_full"])).is_file()
            assert (data_root / str(by_id[slot_id]["path_low"])).is_file()
        else:
            assert by_id[slot_id]["keep"] is False
            assert by_id[slot_id]["reject_reason"] == want

    manifests = slots_csv.parent
    assert (manifests / "slots_clean.csv").is_file()
    assert (manifests / "slots_clean.json").is_file()
    summary = json.loads((manifests / "clean_summary.json").read_text(encoding="utf-8"))
    assert summary["mode"] == "slots"
    assert summary["kept_count"] == 2
    assert summary["rejected_count"] == 3
    assert summary["rejects_by_reason"]["black"] == 1
    assert summary["rejects_by_reason"]["blur"] == 1
    assert summary["rejects_by_reason"]["duplicate"] == 1

    with (manifests / "slots_clean.csv").open(encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert csv_rows[0]["keep"] in {"true", "false"}
    assert all(r["ahash"] == "" or len(r["ahash"]) == 16 for r in csv_rows)


def test_clean_slots_rerun_byte_identical(tmp_path: Path) -> None:
    data_root, slots_csv, _ = _build_slot_fixture(tmp_path)
    clean_slots_table(slots_csv, data_root=data_root)
    manifests = slots_csv.parent
    first_csv = (manifests / "slots_clean.csv").read_bytes()
    first_json = (manifests / "slots_clean.json").read_bytes()
    first_summary = (manifests / "clean_summary.json").read_bytes()

    clean_slots_table(slots_csv, data_root=data_root)
    assert (manifests / "slots_clean.csv").read_bytes() == first_csv
    assert (manifests / "slots_clean.json").read_bytes() == first_json
    assert (manifests / "clean_summary.json").read_bytes() == first_summary


def test_clean_slots_does_not_modify_frames_without_debug(tmp_path: Path) -> None:
    data_root, slots_csv, _ = _build_slot_fixture(tmp_path)
    frames_root = data_root / "frames"
    before = {
        p.relative_to(frames_root): (p.stat().st_mtime_ns, p.read_bytes())
        for p in frames_root.rglob("*")
        if p.is_file()
    }
    clean_slots_table(slots_csv, data_root=data_root, debug=False)
    after_paths = {p.relative_to(frames_root) for p in frames_root.rglob("*") if p.is_file()}
    assert after_paths == set(before)
    for rel, (mtime_ns, content) in before.items():
        path = frames_root / rel
        assert path.stat().st_mtime_ns == mtime_ns
        assert path.read_bytes() == content
    assert not (frames_root / "_rejected").exists()


def test_clean_slots_debug_writes_rejected_contact_sheet(tmp_path: Path) -> None:
    data_root, slots_csv, _ = _build_slot_fixture(tmp_path)
    clean_slots_table(slots_csv, data_root=data_root, debug=True)
    rejected = data_root / "frames" / "_rejected"
    assert (rejected / "black").is_dir()
    assert (rejected / "blur").is_dir()
    assert (rejected / "duplicate").is_dir()
    assert any((rejected / "black").iterdir())


def test_clean_slots_cli(tmp_path: Path) -> None:
    data_root, slots_csv, expected = _build_slot_fixture(tmp_path)
    code = main(["--slots", str(slots_csv), "--data-root", str(data_root)])
    assert code == 0
    with (slots_csv.parent / "slots_clean.csv").open(encoding="utf-8", newline="") as f:
        rows = {r["slot_id"]: r for r in csv.DictReader(f)}
    for slot_id, want in expected.items():
        if want == "keep":
            assert rows[slot_id]["keep"] == "true"
        else:
            assert rows[slot_id]["keep"] == "false"
            assert rows[slot_id]["reject_reason"] == want
