"""End-to-end Frame Export Kit runs on synthetic clips inside a temporary tool folder."""

import json
import shutil
import zipfile
from pathlib import Path

from game_frame_classifier.frame_export import cli, paths
from game_frame_classifier.frame_export import run as run_mod
from game_frame_classifier.sourcing.packzip import validate_pack_zip
from tests.helpers.ffmpeg_fixtures import make_testsrc_video, requires_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
USER = {
    "schema": "gfc.user/1",
    "contributor_id": "00000000-0000-4000-8000-000000000001",
    "handle": "tester",
    "consent_data_use": True,
    "consent_public_examples": False,
    "consent_utc": "2026-01-01T00:00:00Z",
    "last_game": "",
    "frame_mode_override": None,
}


def make_home(tmp_path, monkeypatch, with_user=True):
    home = tmp_path / "tool"
    (home / "config").mkdir(parents=True)
    shutil.copyfile(ROOT / "config" / "recipe.json", home / "config" / "recipe.json")
    if with_user:
        (home / "config" / "user.json").write_text(json.dumps(USER), encoding="utf-8")
    monkeypatch.setattr(paths, "app_home", lambda: home)
    return home


def snapshot(folder):
    return {
        p.relative_to(folder).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in folder.rglob("*") if p.is_file()
    }


def outside(tmp_path, home):
    return {p for p in tmp_path.rglob("*") if p != home and home not in p.parents and "scratch" not in p.parts}


def pack_table(zip_path, name):
    with zipfile.ZipFile(zip_path) as zf:
        root = zf.namelist()[0].split("/")[0]
        return json.loads(zf.read(f"{root}/{name}"))


@requires_ffmpeg
def test_full_run_then_rerun(tmp_path, monkeypatch):
    home = make_home(tmp_path, monkeypatch)
    clips = tmp_path / "clips" / "VALORANT"
    make_testsrc_video(clips / "VALORANT 2026.11.02 - 21.14.08.mp4", duration_s=12)
    make_testsrc_video(clips / "session2" / "клип ü 2026-11-03 20-00-00.mp4", duration_s=7)
    shutil.copyfile(clips / "VALORANT 2026.11.02 - 21.14.08.mp4", clips / "zz_copy.mp4")
    make_testsrc_video(clips / "short.mp4", duration_s=0.5)
    (clips / "corrupt.mp4").write_bytes(b"\x00" * 4096)
    (clips / "notes.txt").write_text("hi", encoding="utf-8")
    (clips / "steam_rec").mkdir()
    (clips / "steam_rec" / "session.mpd").write_text("<MPD/>", encoding="utf-8")
    (clips / "steam_rec" / "chunk.m4s").write_bytes(b"\x00")
    before_clips = snapshot(clips)
    before_outside = outside(tmp_path, home)

    assert cli.main([str(clips), "--yes", "--game", "Valorant", "--no-open"]) == 0

    zips = sorted((home / "output").glob("GFC_Valorant_tester_*.zip"))
    assert len(zips) == 1
    (manifest,) = validate_pack_zip(zips[0], tmp_path / "scratch")
    assert manifest["input"]["clips_ok"] == 2
    assert manifest["output"]["slots"] == 5
    assert manifest["output"]["images"] == 10
    assert manifest["contributor"]["handle"] == "tester"
    assert manifest["ffmpeg"]["build"] in ("path", "env")
    rows = {r["original_relpath"]: r for r in pack_table(zips[0], "clips.json")}
    original = rows["VALORANT 2026.11.02 - 21.14.08.mp4"]
    assert original["status"] == "ok"
    assert original["recorded_start_source"] == "filename"
    assert original["aliases"] == ["zz_copy.mp4"]
    assert original["label_hint"] == "Valorant" and original["label_hint_conflict"] is False
    assert rows["session2/клип ü 2026-11-03 20-00-00.mp4"]["status"] == "ok"
    assert (rows["zz_copy.mp4"]["status"], rows["zz_copy.mp4"]["status_detail"]) == ("skipped", "duplicate_in_run")
    assert rows["short.mp4"]["status_detail"] == "too_short"
    assert rows["corrupt.mp4"]["status_detail"] == "unreadable"
    assert rows["notes.txt"]["status_detail"] == "not_video"
    assert rows["steam_rec"]["status_detail"] == "steam_recording"
    frames = pack_table(zips[0], "frames.json")
    assert len(frames) == 10 and all(f["rel_path"].isascii() for f in frames)

    assert snapshot(clips) == before_clips
    assert outside(tmp_path, home) == before_outside
    assert len(json.loads((home / "config" / "history.json").read_text(encoding="utf-8"))) == 2
    assert not any((home / "output" / "_work").iterdir())

    assert cli.main([str(clips), "--yes", "--game", "Valorant", "--no-open"]) == 0
    assert len(list((home / "output").glob("GFC_*.zip"))) == 1


@requires_ffmpeg
def test_budget_spreads_days_and_compact_mode(tmp_path, monkeypatch):
    home = make_home(tmp_path, monkeypatch)
    clips = tmp_path / "clips"
    for day in (1, 2, 3):
        make_testsrc_video(clips / f"m 2026-10-0{day} 10-00-00.mp4", duration_s=50, width=320, height=180)
    args = [str(clips), "--yes", "--game", "CS2", "--no-open", "--compact", "--budget-hours", "0.034"]

    assert cli.main(args) == 0
    (first,) = sorted((home / "output").glob("GFC_CS2_tester_*.zip"))
    (manifest,) = validate_pack_zip(first, tmp_path / "scratch")
    assert manifest["input"]["footage_budget_min"] == 2
    assert manifest["input"]["over_budget_clips"] == 1
    assert manifest["output"]["frame_mode"] == "compact"
    assert {(f["width"], f["height"]) for f in pack_table(first, "frames.json")} == {(256, 144)}
    sent = {r["original_relpath"] for r in pack_table(first, "clips.json") if r["status"] == "ok"}
    assert sent == {"m 2026-10-01 10-00-00.mp4", "m 2026-10-02 10-00-00.mp4"}

    assert cli.main(args) == 0
    zips = sorted((home / "output").glob("GFC_CS2_tester_*.zip"))
    assert len(zips) == 2
    second = next(z for z in zips if z != first)
    sent2 = {r["original_relpath"] for r in pack_table(second, "clips.json") if r["status"] == "ok"}
    assert sent2 == {"m 2026-10-03 10-00-00.mp4"}


@requires_ffmpeg
def test_resume_after_interrupt(tmp_path, monkeypatch):
    home = make_home(tmp_path, monkeypatch)
    clips = tmp_path / "clips"
    for day in (1, 2, 3):
        make_testsrc_video(clips / f"m 2026-10-0{day} 10-00-00.mp4", duration_s=6, width=320, height=180)
    real = run_mod.extract_clip
    calls = []

    def interrupt_second(*args, **kwargs):
        calls.append(args[1].name)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(run_mod, "extract_clip", interrupt_second)
    args = [str(clips), "--yes", "--game", "Minecraft", "--no-open"]
    assert cli.main(args) == 130
    assert len(list((home / "output" / "_work").glob("*/done/*.json"))) == 1
    assert not list((home / "output").glob("*.zip"))

    calls.clear()

    def record(*args, **kwargs):
        calls.append(args[1].name)
        return real(*args, **kwargs)

    monkeypatch.setattr(run_mod, "extract_clip", record)
    assert cli.main(args) == 0
    assert len(calls) == 2
    (zip_path,) = (home / "output").glob("GFC_Minecraft_tester_*.zip")
    (manifest,) = validate_pack_zip(zip_path, tmp_path / "scratch")
    assert manifest["input"]["clips_ok"] == 3


@requires_ffmpeg
def test_first_run_prompts(tmp_path, monkeypatch):
    home = make_home(tmp_path, monkeypatch, with_user=False)
    clips = tmp_path / "Overwatch clips"
    make_testsrc_video(clips / "x.mp4", duration_s=6, width=320, height=180)
    answers = iter(["Alex Smith", "", "", str(clips), "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert cli.main(["--no-open"]) == 0

    user = json.loads((home / "config" / "user.json").read_text(encoding="utf-8"))
    assert user["handle"] == "alex_smith"
    assert user["consent_public_examples"] is True
    assert user["last_game"] == "Overwatch_2"
    assert len(list((home / "output").glob("GFC_Overwatch_2_alex_smith_*.zip"))) == 1
    assert next(answers, None) is None


@requires_ffmpeg
def test_output_folder_gets_only_the_zip(tmp_path, monkeypatch):
    home = make_home(tmp_path, monkeypatch)
    clips = tmp_path / "clips"
    make_testsrc_video(clips / "m 2026-10-01 10-00-00.mp4", duration_s=6, width=320, height=180)
    sent = tmp_path / "sent"
    sent.mkdir()
    before_outside = outside(tmp_path, home)

    assert cli.main([str(clips), "--yes", "--game", "CS2", "--no-open", "--output", str(sent)]) == 0

    (zip_path,) = sent.iterdir()
    assert zip_path.name.startswith("GFC_CS2_tester_") and zip_path.suffix == ".zip"
    assert outside(tmp_path, home) - before_outside == {zip_path}
    assert not list((home / "output").glob("*.zip"))
    (manifest,) = validate_pack_zip(zip_path, tmp_path / "scratch")
    assert manifest["input"]["clips_ok"] == 1


def test_output_must_already_exist(tmp_path, monkeypatch):
    make_home(tmp_path, monkeypatch)
    clips = tmp_path / "clips"
    clips.mkdir()
    missing = tmp_path / "missing"

    assert cli.main([str(clips), "--yes", "--game", "CS2", "--no-open", "--output", str(missing)]) == 2
    assert not missing.exists()
    assert cli.main([str(clips), "--yes", "--game", "CS2", "--no-zip", "--output", str(tmp_path)]) == 2
