"""Unit tests for batch extract path helpers and catalog load wiring."""

from __future__ import annotations

from pathlib import Path

from game_frame_classifier.batch_extract import (
    ClipExtractResult,
    already_extracted,
    clear_batch_frame_outputs,
    clip_frames_dir,
    write_batch_summary,
)
from game_frame_classifier.clip_catalog import ClipRecord, load_clip_catalog, write_clip_catalog


def _clip(**kwargs) -> ClipRecord:
    base = dict(
        clip_id="Valorant/tester/smoke.mp4",
        path=r"C:\fake\Valorant\tester\smoke.mp4",
        game="Valorant",
        source="tester",
        filename="smoke.mp4",
        duration_s=10.0,
        width=640,
        height=360,
    )
    base.update(kwargs)
    return ClipRecord(**base)


def test_clip_frames_dir_mirrors_game_source_stem(tmp_path: Path) -> None:
    out = clip_frames_dir(tmp_path / "frames", _clip())
    assert out == tmp_path / "frames" / "Valorant" / "tester" / "smoke"


def test_already_extracted_requires_manifest(tmp_path: Path) -> None:
    d = tmp_path / "clip"
    d.mkdir()
    assert not already_extracted(d)
    (d / "frames_manifest.csv").write_text("frame_id\n", encoding="utf-8")
    assert already_extracted(d)


def test_load_clip_catalog_roundtrip(tmp_path: Path) -> None:
    records = [
        _clip(),
        _clip(
            clip_id="CS2/friend/a.mkv",
            path="/tmp/a.mkv",
            game="CS2",
            source="friend",
            filename="a.mkv",
            duration_s=3.5,
            width=320,
            height=180,
        ),
    ]
    write_clip_catalog(records, tmp_path)
    loaded_csv = load_clip_catalog(tmp_path / "clips.csv")
    loaded_json = load_clip_catalog(tmp_path / "clips.json")
    assert [r.clip_id for r in loaded_csv] == [r.clip_id for r in records]
    assert [r.clip_id for r in loaded_json] == [r.clip_id for r in records]
    assert loaded_csv[1].duration_s == 3.5
    assert loaded_csv[1].width == 320


def test_write_batch_summary(tmp_path: Path) -> None:
    results = [
        ClipExtractResult("a", "extracted", "/out/a", frame_count=4),
        ClipExtractResult("b", "skipped", "/out/b", detail="exists"),
        ClipExtractResult("c", "error", "/out/c", detail="boom"),
    ]
    path = write_batch_summary(results, tmp_path / "batch_extract_summary.json")
    data = path.read_text(encoding="utf-8")
    assert "extracted" in data
    assert '"clip_count": 3' in data
    assert '"total_frames_extracted": 4' in data


def test_clear_batch_frame_outputs_removes_clips_and_orphans(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    keep = frames / "Valorant" / "tester" / "keep"
    orphan = frames / "Valorant" / "tester" / "gone"
    smoke = frames / "valorant_smoke"  # not a known-game batch path
    keep.mkdir(parents=True)
    orphan.mkdir(parents=True)
    smoke.mkdir(parents=True)
    (keep / "frames_manifest.csv").write_text("x\n", encoding="utf-8")
    (orphan / "frames_manifest.csv").write_text("x\n", encoding="utf-8")
    (frames / "batch_extract_summary.json").write_text("{}", encoding="utf-8")

    removed = clear_batch_frame_outputs(
        frames,
        [_clip(filename="keep.mp4", clip_id="Valorant/tester/keep.mp4")],
    )
    assert not keep.exists()
    assert not orphan.exists()
    assert smoke.exists()  # left alone
    assert not (frames / "batch_extract_summary.json").exists()
    assert any("keep" in p or "gone" in p for p in removed)
