"""System: auto sources through fetch (fakes) then sorter apply plan."""

from __future__ import annotations

from pathlib import Path

from game_frame_classifier.clip_fetch.download import run as fetch_run
from game_frame_classifier.clip_sorter.apply import plan, run as apply_run
from game_frame_classifier.clip_sorter.scan import read_hints, scan
from game_frame_classifier.clip_sorter.store import append
from game_frame_classifier.sourcing.ffbin import find_tools
from game_frame_classifier.sourcing.recipe import load_recipe
from tests.helpers.ffmpeg_fixtures import make_testsrc_video, requires_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "config" / "recipe.json"


def test_fetch_mixed_then_sort_apply(tmp_path: Path):
    data_root = tmp_path / "data"
    incoming = data_root / "incoming_clips"
    users_path = data_root / "clip_links" / "medal_users.csv"
    users_path.parent.mkdir(parents=True)
    users_path.write_text(
        "uploader_id,uploader,source,allowed,first_seen,note\n"
        "id_111,uploader_a,friend_a,yes,2026-01-01,\n"
        "id_222,uploader_b,friend_b,no,2026-01-01,\n",
        encoding="utf-8",
    )
    links = [
        "https://medal.tv/games/valorant/clips/abc123",
        "https://medal.tv/games/valorant/clips/abc124",
        "https://medal.tv/games/cs2/clips/def456",
        "https://medal.tv/games/minecraft/clips/ghi789",
    ]
    meta_map = {
        links[0]: {"uploader_id": "id_111", "uploader": "uploader_a"},
        links[1]: {"uploader_id": "id_111", "uploader": "uploader_a"},
        links[2]: {"uploader_id": "id_222", "uploader": "uploader_b"},
        links[3]: {"uploader_id": "id_333", "uploader": "uploader_c"},
    }

    def fake_meta(url: str) -> dict:
        return dict(meta_map[url])

    def fake_dl(url: str, out_dir: Path, temp_name: str) -> dict:
        (out_dir / temp_name).write_bytes(b"clip-bytes")
        return {"timestamp": 1_700_000_000, "id": "x", "title": "t", **meta_map[url]}

    summary = fetch_run(
        links,
        incoming,
        users_path=users_path,
        ask=None,
        metadata=fake_meta,
        downloader=fake_dl,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 0
    assert summary.by_status["ok"] == 3
    assert summary.by_status["not_allowed"] == 1
    assert (incoming / "friend_a").is_dir()
    assert (incoming / "friend_uploader_c").is_dir()
    assert not (incoming / "friend_b").exists()
    assert (incoming / "fetch_log.csv").is_file()
    assert (incoming / "hints.csv").is_file()

    # Rerun after "sorting" one file into _archive: nothing new downloaded.
    archived = next((incoming / "friend_a").glob("*.mp4"))
    dest = incoming / "_archive" / "friend_a" / archived.name
    dest.parent.mkdir(parents=True)
    archived.replace(dest)
    summary2 = fetch_run(
        links,
        incoming,
        users_path=users_path,
        ask=None,
        metadata=fake_meta,
        downloader=fake_dl,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary2.by_status["skipped"] >= 2
    assert summary2.by_status.get("ok", 0) == 0


@requires_ffmpeg
def test_sorter_apply_from_incoming_folders(tmp_path: Path):
    data_root = tmp_path / "data"
    incoming = data_root / "incoming_clips"
    session = data_root / "sorting" / "incoming_clips_auto"
    make_testsrc_video(incoming / "friend_a" / "clip_a.mp4", duration_s=2.5)
    make_testsrc_video(incoming / "friend_c" / "clip_c.mp4", duration_s=2.5)
    (incoming / "hints.csv").write_text(
        "file,game,other_name\n"
        "friend_a/clip_a.mp4,Valorant,\n"
        "friend_c/clip_c.mp4,CS2,\n",
        encoding="utf-8",
    )
    tools = find_tools()
    recipe = load_recipe(RECIPE)
    hints = read_hints(incoming / "hints.csv")
    clips = scan(incoming, recipe, tools, hints)
    assert {c.source for c in clips} == {"friend_a", "friend_c"}
    for clip in clips:
        game = "Valorant" if clip.source == "friend_a" else "CS2"
        append(session, clip.quick_id, clip.rel_path, "label", game=game)
    actions = plan(session, incoming, clips, "", data_root)
    report = apply_run(actions, dry_run=False)
    assert report["counts"]["copied"] == 2
    assert (data_root / "raw" / "Valorant" / "friend_a" / "clip_a.mp4").is_file()
    assert (data_root / "raw" / "CS2" / "friend_c" / "clip_c.mp4").is_file()
    # No doubled source folder.
    assert not (data_root / "raw" / "Valorant" / "friend_a" / "friend_a").exists()
