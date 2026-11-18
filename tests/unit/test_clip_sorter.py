"""Unit tests for the clip sorter (scan, suggestions, decisions, apply, source kind)."""

from __future__ import annotations

import json
from pathlib import Path

from game_frame_classifier.clip_sorter.apply import plan, run, write_report
from game_frame_classifier.clip_sorter.scan import Clip, read_hints, scan, suggest
from game_frame_classifier.clip_sorter.store import append, first_undecided, other_names, replay
from game_frame_classifier.dataset_splitter import _source_kind
from game_frame_classifier.derive_frames import source_kind
from game_frame_classifier.sourcing.ffbin import find_tools
from game_frame_classifier.sourcing.hashing import sha256_file
from game_frame_classifier.sourcing.recipe import load_recipe
from tests.helpers.ffmpeg_fixtures import make_testsrc_video, requires_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "config" / "recipe.json"


def _clip(
    tmp: Path,
    name: str,
    *,
    problem: str = "",
    suggestion: str = "",
    other_name: str = "",
    origin: str = "",
    duration_s: float | None = 12.0,
) -> Clip:
    path = tmp / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 64)
    return Clip(
        rel_path=name.replace("\\", "/"),
        path=path,
        size=64,
        quick_id=name.replace("/", "_")[:16].ljust(16, "0"),
        duration_s=duration_s,
        width=640,
        height=360,
        problem=problem,
        suggestion=suggestion,
        other_name=other_name,
        suggestion_origin=origin,
    )


# --- suggestions ---


def test_suggest_hints_win(tmp_path):
    hints = {"a/clip.mp4": ("Valorant", "")}
    game, other, origin = suggest("a/clip.mp4", hints)
    assert (game, other, origin) == ("Valorant", "", "hints")


def test_suggest_medal_filename():
    game, other, origin = suggest("Valorant__2026-01-01__12-00-00.mp4", {})
    assert game == "Valorant" and other == "" and origin == "medal_filename"


def test_suggest_medal_other():
    game, other, origin = suggest("Apex_Legends__2026-01-01__12-00-00.mp4", {})
    assert game == "Other" and other == "mixed_other" and origin == "medal_filename"


def test_suggest_single_path_hint():
    game, other, origin = suggest("clips/minecraft/run1.mp4", {})
    assert game == "Minecraft" and origin == "path_hint"


def test_suggest_ambiguous_none():
    game, other, origin = suggest("valorant_and_minecraft.mp4", {})
    assert game == "" and origin == ""


def test_read_hints(tmp_path):
    path = tmp_path / "hints.csv"
    path.write_text("file,game,other_name\nsub/a.mp4,CS2,\n", encoding="utf-8")
    assert read_hints(path) == {"sub/a.mp4": ("CS2", "")}


# --- scan ---


@requires_ffmpeg
def test_scan_recursive_ignores_archive_and_lists_short(tmp_path):
    folder = tmp_path / "inbox"
    make_testsrc_video(folder / "ok.mp4", duration_s=3.0)
    make_testsrc_video(folder / "nested" / "ok2.mp4", duration_s=3.0)
    make_testsrc_video(folder / "_archive" / "gone.mp4", duration_s=3.0)
    make_testsrc_video(folder / "short.mp4", duration_s=0.4)
    (folder / "note.txt").write_text("no", encoding="utf-8")
    tools = find_tools()
    recipe = load_recipe(RECIPE)
    clips = scan(folder, recipe, tools, {})
    rels = [c.rel_path for c in clips]
    assert "ok.mp4" in rels
    assert "nested/ok2.mp4" in rels
    assert all("_archive" not in c.rel_path for c in clips)
    assert "note.txt" not in rels
    short = next(c for c in clips if c.rel_path == "short.mp4")
    assert short.problem.startswith("too_short:")


# --- decisions / store ---


def test_replay_label_change_undo_skip(tmp_path):
    session = tmp_path / "sess"
    c1 = "qid_aaaaaaaa"
    append(session, c1, "a.mp4", "label", game="Valorant")
    append(session, c1, "a.mp4", "label", game="CS2")
    state = replay(session)
    assert state[c1]["game"] == "CS2"
    append(session, c1, "a.mp4", "undo")
    state = replay(session)
    assert c1 not in state
    append(session, c1, "a.mp4", "skip")
    state = replay(session)
    assert state[c1]["decision"] == "skip"
    clips = [
        Clip("a.mp4", tmp_path / "a.mp4", 1, c1, 1.0, 1, 1, "", "", "", ""),
        Clip("b.mp4", tmp_path / "b.mp4", 1, "qid_bbbbbbbb", 1.0, 1, 1, "", "", "", ""),
    ]
    assert first_undecided(clips, state) == 0  # skip = undecided
    append(session, c1, "a.mp4", "disabled")
    state = replay(session)
    assert first_undecided(clips, state) == 1


def test_other_names(tmp_path):
    session = tmp_path / "sess"
    append(session, "a", "a.mp4", "label", game="Other", other_name="Apex_Legends")
    append(session, "b", "b.mp4", "label", game="Other", other_name="desktop")
    append(session, "c", "c.mp4", "label", game="Valorant")
    assert other_names(replay(session)) == ["Apex_Legends", "desktop"]


# --- apply ---


@requires_ffmpeg
def test_apply_label_trash_disabled_dry_run(tmp_path):
    folder = tmp_path / "inbox"
    data_root = tmp_path / "data"
    session = data_root / "sorting" / "t"
    v_ok = make_testsrc_video(folder / "val.mp4", duration_s=2.0)
    v_other = make_testsrc_video(folder / "other.mp4", duration_s=2.0)
    v_trash = make_testsrc_video(folder / "junk.mp4", duration_s=2.0)
    v_dis = make_testsrc_video(folder / "maybe.mp4", duration_s=2.0)
    tools = find_tools()
    recipe = load_recipe(RECIPE)
    clips = scan(folder, recipe, tools, {})
    by_rel = {c.rel_path: c for c in clips}

    append(session, by_rel["val.mp4"].quick_id, "val.mp4", "label", game="Valorant")
    append(
        session,
        by_rel["other.mp4"].quick_id,
        "other.mp4",
        "label",
        game="Other",
        other_name="Apex_Legends",
    )
    append(session, by_rel["junk.mp4"].quick_id, "junk.mp4", "trash")
    append(session, by_rel["maybe.mp4"].quick_id, "maybe.mp4", "disabled")

    actions = plan(session, folder, clips, "tester", data_root)
    dry = run(actions, dry_run=True)
    assert dry["counts"]["copied"] == 2
    assert dry["counts"]["trashed"] == 1
    assert not (data_root / "raw").exists()
    assert v_trash.is_file()

    report = run(actions, dry_run=False)
    write_report(session, report)
    dest_v = data_root / "raw" / "Valorant" / "tester" / "val.mp4"
    dest_o = data_root / "raw" / "_other" / "Apex_Legends" / "tester" / "other.mp4"
    assert dest_v.is_file() and sha256_file(dest_v) == sha256_file(v_ok)
    assert dest_o.is_file()
    assert (folder / "_archive" / "junk.mp4").is_file()
    assert not v_trash.exists()
    assert v_dis.is_file()
    assert (session / "apply_report.json").is_file()
    assert (session / "apply_report.csv").is_file()

    # already_copied (re-scan so trashed file is gone from the clip list)
    clips2 = [c for c in scan(folder, recipe, tools, {}) if c.rel_path != "junk.mp4"]
    actions2 = plan(session, folder, clips2, "tester", data_root)
    assert any(a.result == "already_copied" for a in actions2)
    r2 = run(actions2, dry_run=False)
    assert r2["counts"]["already_copied"] >= 1


@requires_ffmpeg
def test_apply_already_in_pipeline_and_conflict(tmp_path):
    folder = tmp_path / "inbox"
    data_root = tmp_path / "data"
    session = data_root / "sorting" / "t"
    make_testsrc_video(folder / "a.mp4", duration_s=2.0)
    make_testsrc_video(folder / "b.mp4", duration_s=2.0)
    tools = find_tools()
    recipe = load_recipe(RECIPE)
    clips = scan(folder, recipe, tools, {})
    by_rel = {c.rel_path: c for c in clips}

    idx = data_root / "frame_sources" / "_index" / "by_sha256.json"
    idx.parent.mkdir(parents=True)
    digest_a = sha256_file(by_rel["a.mp4"].path)
    idx.write_text(json.dumps({digest_a: {"clip_key": "c" + digest_a[:12]}}), encoding="utf-8")

    # conflict: different file already at destination
    dest_b = data_root / "raw" / "CS2" / "tester" / "b.mp4"
    dest_b.parent.mkdir(parents=True)
    dest_b.write_bytes(b"different-content")

    append(session, by_rel["a.mp4"].quick_id, "a.mp4", "label", game="Valorant")
    append(session, by_rel["b.mp4"].quick_id, "b.mp4", "label", game="CS2")
    actions = plan(session, folder, clips, "tester", data_root)
    by_path = {a.rel_path: a for a in actions}
    assert by_path["a.mp4"].result == "already_in_pipeline"
    assert by_path["b.mp4"].result == "conflict"
    report = run(actions, dry_run=False)
    assert report["counts"]["already_in_pipeline"] == 1
    assert report["counts"]["conflict"] == 1
    assert dest_b.read_bytes() == b"different-content"


@requires_ffmpeg
def test_apply_trash_no_overwrite(tmp_path):
    folder = tmp_path / "inbox"
    data_root = tmp_path / "data"
    session = data_root / "sorting" / "t"
    make_testsrc_video(folder / "dup.mp4", duration_s=2.0)
    arch = folder / "_archive" / "dup.mp4"
    arch.parent.mkdir(parents=True)
    arch.write_bytes(b"existing")
    tools = find_tools()
    recipe = load_recipe(RECIPE)
    clips = scan(folder, recipe, tools, {})
    c = clips[0]
    append(session, c.quick_id, c.rel_path, "trash")
    actions = plan(session, folder, clips, "tester", data_root)
    run(actions, dry_run=False)
    assert arch.read_bytes() == b"existing"
    assert (folder / "_archive" / "dup_1.mp4").is_file()


def test_friend_source_kind():
    assert source_kind("friend_alex") == "contributor"
    assert _source_kind("friend_alex") == "contributor"
    assert source_kind("tester") == "personal"
