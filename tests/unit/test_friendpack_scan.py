"""Discovery and fingerprinting (friend-pack spec §5.1)."""

import json
from pathlib import Path

from game_frame_classifier.friendpack.scan import discover, fingerprint
from game_frame_classifier.sourcing.hashing import quick_id
from game_frame_classifier.sourcing.recipe import recipe_from_dict

ROOT = Path(__file__).resolve().parents[2]
RECIPE = recipe_from_dict(json.loads((ROOT / "config" / "recipe.json").read_text(encoding="utf-8")))


def touch(path, data=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_discover_classifies_and_skips_tool_folder(tmp_path):
    root = tmp_path / "clips"
    touch(root / "a.mp4")
    touch(root / "notes.TXT")
    touch(root / "sub" / "c.MKV")
    touch(root / "steam" / "session.mpd")
    touch(root / "steam" / "chunk.m4s")
    touch(root / "tool" / "inside.mp4")
    items = discover(root, RECIPE, exclude=root / "tool")
    got = {it.relpath: (it.status, it.detail) for it in items}
    assert got == {
        "a.mp4": ("eligible", ""),
        "notes.TXT": ("skipped", "not_video"),
        "steam": ("skipped", "steam_recording"),
        "sub/c.MKV": ("eligible", ""),
    }
    assert [it.relpath for it in items] == sorted(got, key=str.lower)


def test_fingerprint_marks_duplicates_and_sent_clips(tmp_path):
    root = tmp_path / "clips"
    touch(root / "a.mp4", b"same")
    touch(root / "z.mp4", b"same")
    touch(root / "sent.mp4", b"old")
    history = {quick_id(root / "sent.mp4"): {"game": "CS2"}}
    items = discover(root, RECIPE, exclude=tmp_path / "tool")
    fingerprint(items, history, include_packed=False)
    by = {it.relpath: it for it in items}
    assert by["z.mp4"].detail == "duplicate_in_run"
    assert by["a.mp4"].aliases == ["z.mp4"]
    assert by["sent.mp4"].detail == "already_packed"
    assert by["sent.mp4"].packed_game == "CS2"


def test_include_packed_keeps_sent_clip(tmp_path):
    root = tmp_path / "clips"
    touch(root / "sent.mp4", b"old")
    history = {quick_id(root / "sent.mp4"): {"game": "CS2"}}
    items = discover(root, RECIPE, exclude=tmp_path / "tool")
    fingerprint(items, history, include_packed=True)
    assert items[0].status == "eligible" and items[0].packed_game == "CS2"
