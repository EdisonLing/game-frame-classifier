"""Unit tests for YouTube channel listing (no network)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from game_frame_classifier.clip_fetch.channel import list_channel
from game_frame_classifier.clip_fetch.cli import main as cli_main
from game_frame_classifier.clip_fetch.users import load_users


def test_list_channel_skips_live_and_tags(tmp_path: Path):
    users_path = tmp_path / "medal_users.csv"

    def fake_list(_url: str) -> list[dict]:
        return [
            {
                "id": "abcdefghijk",
                "channel_id": "UCchannelfake1",
                "channel": "Fake Channel",
            },
            {
                "id": "liveclip0001",
                "channel_id": "UCchannelfake1",
                "channel": "Fake Channel",
                "is_live": True,
            },
        ]

    out = list_channel(
        "https://www.youtube.com/channel/UCchannelfake1",
        game="CS2",
        content_type="esports_vod",
        out=tmp_path / "links.txt",
        users_path=users_path,
        lister=fake_list,
        now=lambda: datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    lines = [
        ln for ln in out.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")
    ]
    assert lines == ["https://www.youtube.com/watch?v=abcdefghijk,CS2,esports_vod"]
    users = load_users(users_path)
    assert users["yt:UCchannelfake1"]["allowed"] == "yes"
    assert users["yt:UCchannelfake1"]["content_type"] == "esports_vod"


def test_list_channel_accepts_videos_tab_url(tmp_path: Path):
    users_path = tmp_path / "medal_users.csv"
    seen: list[str] = []

    def fake_list(url: str) -> list[dict]:
        seen.append(url)
        return [
            {
                "id": "abcdefghijk",
                "channel_id": "UCchannelfake1",
                "channel": "Fake Channel",
            }
        ]

    list_channel(
        "https://www.youtube.com/@example_channel/videos",
        out=tmp_path / "links.txt",
        users_path=users_path,
        lister=fake_list,
        now=lambda: datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    # Lister receives the URL as given; ytdlp_flat_list is what avoids doubling /videos.
    assert seen == ["https://www.youtube.com/@example_channel/videos"]


def test_cli_tag_uploader_exit_2_when_missing(tmp_path: Path):
    users = tmp_path / "users.csv"
    users.write_text(
        "uploader_id,uploader,source,allowed,first_seen,note,content_type\n"
        "yt:UCabc,Name,yt_name,yes,2026-01-01,,\n",
        encoding="utf-8",
    )
    code = cli_main(
        ["--tag-uploader", "missing_key", "--content-type", "gameplay", "--users", str(users)]
    )
    assert code == 2
