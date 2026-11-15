"""Unit tests for clip catalog pure logic (no ffmpeg required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from game_frame_classifier.clip_catalog import (
    KNOWN_GAMES,
    make_clip_id,
    scan_raw_tree,
    validate_game,
    write_clip_catalog,
)


def test_validate_game_accepts_known() -> None:
    for game in sorted(KNOWN_GAMES):
        assert validate_game(game) == game


def test_validate_game_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown game folder"):
        validate_game("Fortnite")


def test_make_clip_id_stable() -> None:
    a = make_clip_id("Valorant", "edison", "clip_01.mp4")
    b = make_clip_id("Valorant", "edison", "clip_01.mp4")
    assert a == b == "Valorant/edison/clip_01.mp4"


def test_empty_raw_returns_empty(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    assert scan_raw_tree(raw, probe=False) == []


def test_missing_raw_returns_empty(tmp_path: Path) -> None:
    assert scan_raw_tree(tmp_path / "nope", probe=False) == []


def test_unknown_game_folder_raises(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    bad = raw / "NotAGame" / "edison"
    bad.mkdir(parents=True)
    (bad / "clip.mp4").write_bytes(b"fake")
    with pytest.raises(ValueError, match="unknown game folder"):
        scan_raw_tree(raw, probe=False)


def test_ignores_loose_files_and_non_video(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    game = raw / "Valorant"
    source = game / "edison"
    source.mkdir(parents=True)

    (raw / "loose.mp4").write_bytes(b"x")
    (game / "also_loose.mp4").write_bytes(b"x")
    (source / "notes.txt").write_text("nope", encoding="utf-8")
    (source / "keep.mp4").write_bytes(b"video")

    records = scan_raw_tree(raw, probe=False)
    assert len(records) == 1
    assert records[0].clip_id == "Valorant/edison/keep.mp4"
    assert records[0].game == "Valorant"
    assert records[0].source == "edison"
    assert records[0].filename == "keep.mp4"
    assert Path(records[0].path).is_absolute()
    assert Path(records[0].path).name == "keep.mp4"


def test_clip_id_stable_across_rescans(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    clip = raw / "CS2" / "friend_a" / "demo.mkv"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"x")

    first = scan_raw_tree(raw, probe=False)
    second = scan_raw_tree(raw, probe=False)
    assert [r.clip_id for r in first] == [r.clip_id for r in second]
    assert first[0].clip_id == "CS2/friend_a/demo.mkv"


def test_write_clip_catalog_empty(tmp_path: Path) -> None:
    csv_path, json_path = write_clip_catalog([], tmp_path / "manifests")
    assert csv_path.is_file() and json_path.is_file()
    assert "clip_id" in csv_path.read_text(encoding="utf-8")
    assert json_path.read_text(encoding="utf-8").strip() == "[]"
