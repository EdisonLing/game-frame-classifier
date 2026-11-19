"""Unit tests for gfc-make-sources helpers and write contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_frame_classifier.make_sources import (
    CLIP_COLUMNS,
    MIXED_SKIP_DETAIL,
    MakeSourcesError,
    apply_rebuilds,
    build_clip_row,
    check_source_name,
    is_mixed_content_type,
    main,
    sanitize_text,
    unique_run_id,
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
    monkeypatch.setenv("USERNAME", "TestUser")
    monkeypatch.setenv("COMPUTERNAME", "DESKTOPXYZ")
    text = f"failed under {tmp_path / 'clip.mp4'} for TestUser on DESKTOPXYZ"
    out = sanitize_text(text, tmp_path)
    assert str(tmp_path.resolve()) not in out
    assert "TestUser" not in out
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
    assert set(CLIP_COLUMNS) <= set(clip)
    assert clip.get("content_type", "") == ""
    assert clip.get("content_type_origin", "") == ""
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


@requires_ffmpeg
def test_other_clip_uses_other_layout_and_metadata(tmp_path):
    data_root, source_dir = data_tree(
        tmp_path, game="_other/Apex_Legends", source="tester",
    )
    make_raw_clip(source_dir, "clip.mp4", duration_s=6.0)
    assert main([
        "--data-root", str(data_root),
        "--recipe", str(RECIPE),
        "--game", "Other",
        "--cpu",
    ]) == 0
    clip_dirs = list(
        (data_root / "frame_sources" / "_other" / "Apex_Legends" / "tester").glob("c*")
    )
    assert len(clip_dirs) == 1
    clip = json.loads((clip_dirs[0] / "clip.json").read_text(encoding="utf-8"))
    assert clip["game"] == "Other"
    assert clip["other_name"] == "Apex_Legends"


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


def test_rebuild_removes_valid_other_clip_folder(tmp_path):
    fs_root = tmp_path / "frame_sources"
    clip = fs_root / "_other" / "Apex_Legends" / "tester" / "c000000000001"
    clip.mkdir(parents=True)
    index = {
        "a" * 64: {
            "clip_key": "c000000000001",
            "rel_dir": "_other/Apex_Legends/tester/c000000000001",
        },
    }
    assert apply_rebuilds(fs_root, index, ["c000000000001"]) == ["c000000000001"]
    assert not clip.exists()
    assert index == {}


def test_unique_run_id_never_reuses_a_run_record(tmp_path):
    fs_root = tmp_path / "frame_sources"
    assert unique_run_id(fs_root, "20261117-101500") == "20261117-101500"
    (fs_root / "_personal" / "20261117-101500").mkdir(parents=True)
    assert unique_run_id(fs_root, "20261117-101500") == "20261117-101500-2"
    (fs_root / "_personal" / "20261117-101500-2").mkdir()
    assert unique_run_id(fs_root, "20261117-101500") == "20261117-101500-3"


def _pending(sha: str, duration_s: float, day: int):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    start = datetime(2026, 1, day, 12, tzinfo=timezone.utc)
    return (Path(f"{sha}.mp4"), SimpleNamespace(duration_s=duration_s), SimpleNamespace(start=start), sha, "c" + sha)


def test_footage_budget_is_cumulative_and_spread_across_days():
    from game_frame_classifier.make_sources import apply_footage_budget

    pending = [_pending("a1", 600, 1), _pending("a2", 600, 1), _pending("b1", 600, 2), _pending("c1", 600, 3)]
    assert apply_footage_budget(pending, None, 0) == (pending, [])
    selected, over = apply_footage_budget(pending, 1800, 0)
    assert sorted(item[3] for item in selected) == ["a1", "b1", "c1"]
    assert [item[3] for item in over] == ["a2"]
    # Same budget after those were extracted: nothing more; a higher budget tops up.
    assert apply_footage_budget([pending[1]], 1800, 1800) == ([], [pending[1]])
    assert apply_footage_budget([pending[1]], 2400, 1800)[0] == [pending[1]]


def test_footage_budget_first_run_takes_shortest_but_top_up_never_overshoots():
    from game_frame_classifier.make_sources import apply_footage_budget

    long_clip = [_pending("x", 900, 1)]
    assert apply_footage_budget(long_clip, 600, 0)[0] == long_clip
    assert apply_footage_budget(long_clip, 600, 300) == ([], long_clip)

def test_write_clip_json_includes_content_type(tmp_path):
    from game_frame_classifier.make_sources import read_content_types, write_clip_json
    from game_frame_classifier.sourcing.manifests import blank_clip_row

    source_dir = tmp_path / "raw" / "Valorant" / "yt_example"
    source_dir.mkdir(parents=True)
    (source_dir / "content_types.csv").write_text(
        "file,content_type,content_type_origin\n"
        "clip.mp4,gameplay,video\n",
        encoding="utf-8",
    )
    assert read_content_types(source_dir)["clip.mp4"] == ("gameplay", "video")
    dest = tmp_path / "fs" / "clip"
    dest.mkdir(parents=True)
    row = blank_clip_row()
    write_clip_json(
        dest, row, game="Valorant", content_type="gameplay", content_type_origin="video"
    )
    payload = json.loads((dest / "clip.json").read_text(encoding="utf-8"))
    assert payload["content_type"] == "gameplay"
    assert payload["content_type_origin"] == "video"


def test_is_mixed_content_type():
    assert is_mixed_content_type("mixed")
    assert is_mixed_content_type(" mixed ")
    assert not is_mixed_content_type("gameplay")
    assert not is_mixed_content_type("esports_vod")
    assert not is_mixed_content_type("streamer_overlay")
    assert not is_mixed_content_type("Mixed")
    assert not is_mixed_content_type("")


def _clips_by_relpath(data_root: Path) -> dict[str, dict]:
    personal = list((data_root / "frame_sources" / "_personal").glob("*/clips.json"))
    assert len(personal) == 1
    rows = json.loads(personal[0].read_text(encoding="utf-8"))
    return {r["original_relpath"]: r for r in rows}


@requires_ffmpeg
def test_skip_mixed_content_type_does_not_extract(tmp_path):
    data_root, source_dir = data_tree(tmp_path)
    make_raw_clip(source_dir, "ok.mp4", duration_s=6.0)
    make_raw_clip(source_dir, "mixed.mp4", duration_s=6.0)
    (source_dir / "content_types.csv").write_text(
        "file,content_type,content_type_origin\n"
        "mixed.mp4,mixed,sorter\n"
        "ok.mp4,gameplay,video\n",
        encoding="utf-8",
    )
    assert main(["--data-root", str(data_root), "--recipe", str(RECIPE), "--cpu"]) == 0
    assert (source_dir / "mixed.mp4").is_file()
    clip_dirs = list((data_root / "frame_sources" / "Valorant" / "tester").glob("c*"))
    assert len(clip_dirs) == 1
    ok_clip = json.loads((clip_dirs[0] / "clip.json").read_text(encoding="utf-8"))
    assert ok_clip["content_type"] == "gameplay"
    by_name = _clips_by_relpath(data_root)
    assert by_name["mixed.mp4"]["status"] == "skipped"
    assert by_name["mixed.mp4"]["status_detail"] == MIXED_SKIP_DETAIL
    assert by_name["ok.mp4"]["status"] == "ok"
    index = json.loads(
        (data_root / "frame_sources" / "_index" / "by_sha256.json").read_text(encoding="utf-8")
    )
    assert len(index) == 1
    manifest = json.loads(
        next((data_root / "frame_sources" / "_personal").glob("*/run_manifest.json")).read_text(
            encoding="utf-8"
        )
    )
    assert manifest["input"]["clips_ok"] == 1


@requires_ffmpeg
def test_mixed_only_source_extracts_nothing(tmp_path):
    data_root, source_dir = data_tree(tmp_path)
    make_raw_clip(source_dir, "mixed.mp4", duration_s=6.0)
    (source_dir / "content_types.csv").write_text(
        "file,content_type,content_type_origin\n"
        "mixed.mp4,mixed,channel\n",
        encoding="utf-8",
    )
    assert main(["--data-root", str(data_root), "--recipe", str(RECIPE), "--cpu"]) == 0
    assert not (data_root / "frame_sources" / "Valorant" / "tester").exists()
    by_name = _clips_by_relpath(data_root)
    assert by_name["mixed.mp4"]["status_detail"] == MIXED_SKIP_DETAIL
    manifest = json.loads(
        next((data_root / "frame_sources" / "_personal").glob("*/run_manifest.json")).read_text(
            encoding="utf-8"
        )
    )
    assert manifest["input"]["clips_ok"] == 0
    index_path = data_root / "frame_sources" / "_index" / "by_sha256.json"
    if index_path.is_file():
        assert json.loads(index_path.read_text(encoding="utf-8")) == {}


@requires_ffmpeg
def test_mixed_skip_is_not_over_budget(tmp_path):
    """Mixed must be skipped before budget selection, never counted as over_budget."""
    data_root, source_dir = data_tree(tmp_path)
    make_raw_clip(source_dir, "ok.mp4", duration_s=20.0)
    make_raw_clip(source_dir, "mixed.mp4", duration_s=20.0)
    (source_dir / "content_types.csv").write_text(
        "file,content_type,content_type_origin\n"
        "mixed.mp4,mixed,sorter\n",
        encoding="utf-8",
    )
    # Enough for one ~20 s clip only.
    assert main([
        "--data-root", str(data_root),
        "--recipe", str(RECIPE),
        "--cpu",
        "--budget-hours", str(25 / 3600),
    ]) == 0
    by_name = _clips_by_relpath(data_root)
    assert by_name["mixed.mp4"]["status_detail"] == MIXED_SKIP_DETAIL
    assert by_name["ok.mp4"]["status"] == "ok"
    clip_dirs = list((data_root / "frame_sources" / "Valorant" / "tester").glob("c*"))
    assert len(clip_dirs) == 1


@pytest.mark.parametrize("content_type", ["", "gameplay", "esports_vod", "streamer_overlay"])
@requires_ffmpeg
def test_non_mixed_content_types_still_extract(tmp_path, content_type):
    data_root, source_dir = data_tree(tmp_path)
    make_raw_clip(source_dir, "clip.mp4", duration_s=6.0)
    if content_type:
        (source_dir / "content_types.csv").write_text(
            "file,content_type,content_type_origin\n"
            f"clip.mp4,{content_type},video\n",
            encoding="utf-8",
        )
    assert main(["--data-root", str(data_root), "--recipe", str(RECIPE), "--cpu"]) == 0
    clip_dirs = list((data_root / "frame_sources" / "Valorant" / "tester").glob("c*"))
    assert len(clip_dirs) == 1
    clip = json.loads((clip_dirs[0] / "clip.json").read_text(encoding="utf-8"))
    assert clip["status"] == "ok"
    assert clip.get("content_type", "") == content_type
