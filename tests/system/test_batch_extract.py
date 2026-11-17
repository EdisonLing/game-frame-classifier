"""System tests: catalog → batch extract on synthetic clips."""

from __future__ import annotations

import json
from pathlib import Path

from game_frame_classifier.batch_extract import (
    extract_catalog,
    extract_one_clip,
    rebuild_from_raw,
)
from game_frame_classifier.clip_catalog import build_catalog, load_clip_catalog
from tests.helpers.ffmpeg_fixtures import make_color_video, requires_ffmpeg


@requires_ffmpeg
def test_batch_extract_two_clips(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    make_color_video(
        raw / "Valorant" / "edison" / "a.mp4",
        duration_s=2.0,
        width=320,
        height=180,
        color="red",
    )
    make_color_video(
        raw / "Minecraft" / "edison" / "b.mp4",
        duration_s=2.0,
        width=320,
        height=180,
        color="green",
    )
    manifests = tmp_path / "manifests"
    build_catalog(raw, manifests)

    frames = tmp_path / "frames"
    results = extract_catalog(
        manifests / "clips.csv",
        frames,
        interval_s=1.0,
    )

    assert len(results) == 2
    assert all(r.status == "extracted" for r in results)
    assert sum(r.frame_count for r in results) >= 2

    a_manifest = frames / "Valorant" / "edison" / "a" / "frames_manifest.csv"
    b_manifest = frames / "Minecraft" / "edison" / "b" / "frames_manifest.csv"
    assert a_manifest.is_file()
    assert b_manifest.is_file()


@requires_ffmpeg
def test_batch_extract_skips_existing_unless_force(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    make_color_video(
        raw / "CS2" / "edison" / "only.mp4",
        duration_s=2.0,
        width=160,
        height=90,
    )
    manifests = tmp_path / "manifests"
    clips = build_catalog(raw, manifests)
    frames = tmp_path / "frames"

    first = extract_catalog(manifests / "clips.csv", frames, interval_s=1.0)
    assert first[0].status == "extracted"
    n1 = first[0].frame_count

    second = extract_catalog(manifests / "clips.csv", frames, interval_s=1.0)
    assert second[0].status == "skipped"

    third = extract_one_clip(clips[0], frames, interval_s=1.0, force=True)
    assert third.status == "extracted"
    assert third.frame_count == n1


@requires_ffmpeg
def test_batch_extract_game_filter_and_summary(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    make_color_video(raw / "Valorant" / "edison" / "v.mp4", duration_s=1.5)
    make_color_video(
        raw / "CS2" / "edison" / "c.mp4",
        duration_s=1.5,
        color="blue",
    )
    manifests = tmp_path / "manifests"
    build_catalog(raw, manifests)
    frames = tmp_path / "frames"

    results = extract_catalog(
        manifests / "clips.json",
        frames,
        interval_s=1.0,
        game="Valorant",
    )
    assert len(results) == 1
    assert results[0].clip_id.startswith("Valorant/")

    from game_frame_classifier.batch_extract import write_batch_summary

    summary = write_batch_summary(results, frames / "batch_extract_summary.json")
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["by_status"]["extracted"] == 1


@requires_ffmpeg
def test_clean_rebuild_drops_removed_source(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    make_color_video(raw / "Valorant" / "edison" / "keep.mp4", duration_s=1.5)
    gone = raw / "Valorant" / "edison" / "gone.mp4"
    make_color_video(gone, duration_s=1.5, color="blue")

    manifests = tmp_path / "manifests"
    frames = tmp_path / "frames"
    build_catalog(raw, manifests)
    first = extract_catalog(manifests / "clips.csv", frames, interval_s=1.0)
    assert len(first) == 2
    assert (frames / "Valorant" / "edison" / "gone").is_dir()

    gone.unlink()
    records, removed = rebuild_from_raw(raw, manifests, frames)
    assert len(records) == 1
    assert records[0].filename == "keep.mp4"
    assert any("gone" in p for p in removed)
    assert not (frames / "Valorant" / "edison" / "gone").exists()

    catalog = load_clip_catalog(manifests / "clips.csv")
    assert [c.filename for c in catalog] == ["keep.mp4"]

    results = extract_catalog(
        manifests / "clips.csv",
        frames,
        interval_s=1.0,
        force=True,
    )
    assert len(results) == 1
    assert results[0].status == "extracted"
