"""Unit tests for gfc-make-sources helpers and write contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_frame_classifier.make_sources import (
    CLIP_COLUMNS,
    MakeSourcesError,
    apply_rebuilds,
    build_clip_row,
    check_source_name,
    main,
    sanitize_text,
)
from game_frame_classifier.sourcing.hashing import sha256_file
from game_frame_classifier.sourcing.manifests import blank_clip_row
from tests.helpers.make_sources_fixtures import RECIPE, data_tree, make_raw_clip, requires_ffmpeg, seed_index


def test_contributor_source_refused():
    with pytest.raises(MakeSourcesError, match="reserved"):
        check_source_name("contributor_alex")
    with pytest.raises(MakeSourcesError, match="reserved"):
        check_source_name("Contributor-Alex")
    assert check_source_name("Tester") == "tester"
    assert check_source_name("my-clips") == "my_clips"


def test_sanitize_strips_absolute_and_user(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "EdisonLocal")
    monkeypatch.setenv("COMPUTERNAME", "DESKTOPXYZ")
    text = f"failed under {tmp_path / 'clip.mp4'} for EdisonLocal on DESKTOPXYZ"
    out = sanitize_text(text, tmp_path)
    assert str(tmp_path.resolve()) not in out
    assert "EdisonLocal" not in out
    assert "DESKTOPXYZ" not in out


def test_blank_clip_row_has_every_column():
    row = blank_clip_row()
    assert set(row) >= set(CLIP_COLUMNS)


@requires_ffmpeg
def test_skip_when_sha_already_indexed(tmp_path):
    data_root, source_dir = data_tree(tmp_path)
    video = make_raw_clip(source_dir, "a.mp4", duration_s=6.0)
    sha = sha256_file(video)
    clip_key = "c" + sha[:12]
    fs = data_root / "frame_sources"
    seed_index(fs, {
        sha: {
            "clip_key": clip_key,
            "pack_id": "pack-from-friend",
            "game": "Valorant",
            "source": "contributor_alex",
            "rel_dir": f"Valorant/contributor_alex/{clip_key}",
        },
    })
    before = json.loads((fs / "_index" / "by_sha256.json").read_text(encoding="utf-8"))
    assert main(["--data-root", str(data_root), "--recipe", str(RECIPE)]) == 0
    after = json.loads((fs / "_index" / "by_sha256.json").read_text(encoding="utf-8"))
    assert after == before
    assert not (fs / "Valorant" / "tester").exists()
    personal = list((fs / "_personal").glob("*/run_manifest.json"))
    assert len(personal) == 1
    manifest = json.loads(personal[0].read_text(encoding="utf-8"))
    assert manifest["input"]["clips_skipped_existing"] == 1
    assert manifest["input"]["clips_ok"] == 0


@requires_ffmpeg
def test_clip_json_has_every_column_and_no_absolute_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "PathLeakUser")
    data_root, source_dir = data_tree(tmp_path)
    make_raw_clip(source_dir, "clip.mp4", duration_s=6.0)
    assert main(["--data-root", str(data_root), "--recipe", str(RECIPE)]) == 0
    clip_dirs = list((data_root / "frame_sources" / "Valorant" / "tester").glob("c*"))
    assert len(clip_dirs) == 1
    clip = json.loads((clip_dirs[0] / "clip.json").read_text(encoding="utf-8"))
    assert set(clip) == set(CLIP_COLUMNS)
    assert clip["status"] == "ok"
    assert clip["original_relpath"] == "clip.mp4"
    blob = json.dumps(clip)
    assert str(data_root.resolve()) not in blob
    assert "PathLeakUser" not in blob
    assert ":\\" not in blob.replace("crf", "")
    for path in (data_root / "frame_sources").rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert str(tmp_path.resolve()) not in text
        assert "PathLeakUser" not in text


def test_build_clip_row_columns(tmp_path):
    path = tmp_path / "x.mp4"
    path.write_bytes(b"not-a-real-video")
    row = build_clip_row(
        path=path,
        source_root=tmp_path,
        game="Valorant",
        info=None,
        times=None,
        sha="a" * 64,
        clip_key="c" + ("a" * 12),
        status="skipped",
        status_detail="unreadable",
        result=None,
        wall_s=None,
    )
    assert set(row) == set(CLIP_COLUMNS)
    assert row["original_relpath"] == "x.mp4"


@pytest.mark.parametrize("rel_dir", ["", ".", "Valorant", "Valorant/tester", "../outside/x/c123", "../x/c123", "Valorant/tester/c1/extra"])
def test_rebuild_refuses_invalid_rel_dir(tmp_path, rel_dir):
    fs_root = tmp_path / "frame_sources"
    keep = fs_root / "Valorant" / "tester" / "c000000000001"
    keep.mkdir(parents=True)
    index = {"a" * 64: {"clip_key": "c000000000001", "rel_dir": rel_dir}}
    with pytest.raises(MakeSourcesError):
        apply_rebuilds(fs_root, index, ["c000000000001"])
    assert keep.is_dir()
    assert "a" * 64 in index


def test_rebuild_removes_valid_clip_folder(tmp_path):
    fs_root = tmp_path / "frame_sources"
    clip = fs_root / "Valorant" / "tester" / "c000000000001"
    clip.mkdir(parents=True)
    index = {"a" * 64: {"clip_key": "c000000000001", "rel_dir": "Valorant/tester/c000000000001"}}
    assert apply_rebuilds(fs_root, index, ["c000000000001"]) == ["c000000000001"]
    assert not clip.exists()
    assert index == {}
