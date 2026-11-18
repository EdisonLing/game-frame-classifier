"""Unit tests for gfc-fetch-clips (no network, no yt-dlp)."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest

from game_frame_classifier.clip_fetch import download as download_mod
from game_frame_classifier.clip_fetch.cli import main as cli_main
from game_frame_classifier.clip_fetch.download import RateLimited, run
from game_frame_classifier.clip_fetch.links import (
    OLD_MEDAL_ERROR,
    UNSUPPORTED_SITE_ERROR,
    game_for_slug,
    parse_link,
    read_links,
)
from game_frame_classifier.clip_fetch.naming import clip_file_name
from game_frame_classifier.sourcing.timeinfo import parse_filename_time


# --- links -----------------------------------------------------------------


@pytest.mark.parametrize(
    "url,site,clip_id,slug",
    [
        (
            "https://medal.tv/games/valorant/clips/AbCdEf123",
            "medal",
            "AbCdEf123",
            "valorant",
        ),
        (
            "https://www.medal.tv/games/valorant/clips/AbCdEf123/?x=1",
            "medal",
            "AbCdEf123",
            "valorant",
        ),
        (
            "https://medal.tv/clips/AbCdEf123",
            "medal",
            "AbCdEf123",
            "",
        ),
        (
            "https://example.com/watch?v=xyz",
            "other",
            "",
            "",
        ),
    ],
)
def test_parse_link(url, site, clip_id, slug):
    info = parse_link(url)
    assert info.site == site
    assert info.clip_id == clip_id
    assert info.slug == slug


def test_read_links_blank_hash_duplicates(tmp_path: Path):
    path = tmp_path / "links.txt"
    path.write_text(
        "\n".join(
            [
                "# comment",
                "",
                "https://medal.tv/games/valorant/clips/Aaa111",
                "https://medal.tv/games/cs2/clips/Bbb222",
                "https://medal.tv/games/valorant/clips/Aaa111",
                "  ",
                "# another",
                "https://medal.tv/games/minecraft/clips/Ccc333",
            ]
        ),
        encoding="utf-8",
    )
    assert read_links(path) == [
        "https://medal.tv/games/valorant/clips/Aaa111",
        "https://medal.tv/games/cs2/clips/Bbb222",
        "https://medal.tv/games/minecraft/clips/Ccc333",
    ]


def test_read_links_strips_utf8_bom(tmp_path: Path):
    path = tmp_path / "bom.txt"
    path.write_bytes(
        b"\xef\xbb\xbf# comment\nhttps://medal.tv/games/valorant/clips/BomClip1\n"
    )
    assert read_links(path) == ["https://medal.tv/games/valorant/clips/BomClip1"]


# --- game ------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug,game,other",
    [
        ("valorant", "Valorant", ""),
        ("league-of-legends", "League_of_Legends", ""),
        ("counter-strike-2", "CS2", ""),
        ("cs2", "CS2", ""),
        ("counter-strike-global-offensive", "CS2", ""),
        ("csgo", "CS2", ""),
        ("counter-strike", "CS2", ""),
        ("minecraft", "Minecraft", ""),
        ("overwatch-2", "Overwatch_2", ""),
        ("overwatch", "Overwatch_2", ""),
        ("marvel-rivals", "Marvel_Rivals", ""),
    ],
)
def test_game_for_slug_table(slug, game, other):
    assert game_for_slug(slug) == (game, other)


def test_game_for_slug_label_hints_fallback():
    # not in table, but label_hints finds exactly one game
    assert game_for_slug("some-valorant-cup") == ("Valorant", "")


def test_game_for_slug_unknown_other():
    game, other = game_for_slug("apex-legends")
    assert game == "Other"
    assert other == "apex_legends"


def test_game_for_slug_empty():
    assert game_for_slug("") == ("", "")


# --- naming ----------------------------------------------------------------


def test_clip_file_name_timestamp_roundtrip():
    from game_frame_classifier.clip_fetch.links import LinkInfo

    info = LinkInfo(
        url="https://medal.tv/games/valorant/clips/AbCdEf123",
        site="medal",
        clip_id="AbCdEf123",
        slug="valorant",
    )
    upload = datetime(2024, 6, 15, 14, 30, 45)
    name, used, source = clip_file_name(info, upload, None, datetime(2025, 1, 1))
    assert source == "timestamp"
    assert name == "valorant__2024-06-15__14-30-45__AbCdEf123.mp4"
    assert used == upload
    parsed = parse_filename_time(name)
    assert parsed is not None
    assert parsed.value == upload
    assert parsed.has_time is True


def test_clip_file_name_upload_date_only():
    from game_frame_classifier.clip_fetch.links import LinkInfo

    info = LinkInfo(url="u", site="medal", clip_id="X1", slug="cs2")
    name, used, source = clip_file_name(info, None, "20240102", datetime(2025, 1, 1))
    assert source == "upload_date"
    assert name == "cs2__2024-01-02__00-00-00__X1.mp4"
    assert used == datetime(2024, 1, 2)


def test_clip_file_name_neither_uses_now():
    from game_frame_classifier.clip_fetch.links import LinkInfo

    info = LinkInfo(url="u", site="other", clip_id="Z9", slug="")
    now = datetime(2025, 3, 4, 5, 6, 7)
    name, used, source = clip_file_name(info, None, None, now)
    assert source == "download"
    assert used == now
    assert name == "other__2025-03-04__05-06-07__Z9.mp4"


# --- run with fake downloader ----------------------------------------------


def _fake_downloader(timestamp: int = 1_718_467_845):
    """Write a few bytes to out_dir/temp_name; return yt-dlp-like info."""

    def downloader(url: str, out_dir: Path, temp_name: str) -> dict:
        path = Path(out_dir) / temp_name
        path.write_bytes(b"fake-clip")
        return {
            "timestamp": timestamp,
            "id": "AbCdEf123",
            "title": "clip \U0001f3ae",
            "width": 1280,
            "height": 720,
            "fps": 60,
            "format_id": "http-source",
        }

    return downloader


def test_run_logs_hints_skip_and_limit(tmp_path: Path):
    source_dir = tmp_path / "incoming"
    url = "https://medal.tv/games/valorant/clips/AbCdEf123"
    sleeps: list[float] = []

    summary = run(
        [url],
        source_dir,
        downloader=_fake_downloader(),
        pause_s=3.0,
        sleep=sleeps.append,
        now=lambda: datetime(2025, 1, 1),
    )
    assert summary.exit_code == 0
    assert summary.by_status["ok"] == 1
    assert summary.by_game["Valorant"] == 1
    assert sleeps == []  # no pause after a single download

    log_path = source_dir / "fetch_log.csv"
    with open(log_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert rows[0]["game"] == "Valorant"
    assert rows[0]["file"].startswith("valorant__")
    assert (source_dir / rows[0]["file"]).is_file()

    with open(source_dir / "hints.csv", encoding="utf-8", newline="") as f:
        hints = list(csv.DictReader(f))
    assert hints == [{"file": rows[0]["file"], "game": "Valorant", "other_name": ""}]

    # Rerun skips finished link
    summary2 = run(
        [url],
        source_dir,
        downloader=_fake_downloader(),
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary2.by_status["skipped"] == 1
    assert summary2.exit_code == 0

    # limit stops after N new downloads
    url2 = "https://medal.tv/games/cs2/clips/CsClip99"
    url3 = "https://medal.tv/games/minecraft/clips/McClip01"

    def multi_dl(url: str, out_dir: Path, temp_name: str) -> dict:
        path = Path(out_dir) / temp_name
        path.write_bytes(b"x")
        return {"timestamp": 1_700_000_000, "id": temp_name, "title": "t"}

    summary3 = run(
        [url2, url3],
        source_dir,
        downloader=multi_dl,
        pause_s=0,
        limit=1,
        sleep=lambda _s: None,
    )
    assert summary3.by_status["ok"] == 1
    assert (source_dir / "hints.csv").is_file()


def test_run_failed_link_exit_1(tmp_path: Path):
    def boom(url: str, out_dir: Path, temp_name: str) -> dict:
        raise RuntimeError(r"fail at C:\Users\someone\clips\x.mp4")

    summary = run(
        ["https://medal.tv/games/valorant/clips/Fail001"],
        tmp_path / "src",
        downloader=boom,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 1
    assert summary.by_status["failed"] == 1
    with open(tmp_path / "src" / "fetch_log.csv", encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["status"] == "failed"
    assert "<path>" in row["error"]
    assert "C:\\Users" not in row["error"]


def test_run_rate_limited_exit_3(tmp_path: Path):
    def limited(url: str, out_dir: Path, temp_name: str) -> dict:
        raise RateLimited("HTTP Error 429: Too Many Requests")

    summary = run(
        ["https://medal.tv/games/valorant/clips/Rate001"],
        tmp_path / "src",
        downloader=limited,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 3
    assert summary.rate_limited is True
    with open(tmp_path / "src" / "fetch_log.csv", encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["status"] == "rate_limited"


def test_run_old_medal_form_failed(tmp_path: Path):
    summary = run(
        ["https://medal.tv/clips/OldForm01"],
        tmp_path / "src",
        downloader=_fake_downloader(),
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 1
    with open(tmp_path / "src" / "fetch_log.csv", encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["status"] == "failed"
    assert row["error"] == OLD_MEDAL_ERROR


def test_run_refuses_non_medal_links(tmp_path: Path):
    calls = []

    def downloader(*args, **kwargs):
        calls.append(args)
        raise AssertionError("must not download")

    summary = run(
        ["https://www.youtube.com/watch?v=AbCdEf12345", "https://example.com/v/1"],
        tmp_path / "src",
        downloader=downloader,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 1 and calls == []
    with open(tmp_path / "src" / "fetch_log.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert {row["error"] for row in rows} == {UNSUPPORTED_SITE_ERROR}


def test_dry_run_no_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    called = []

    def should_not_run(*_a, **_k):
        called.append(1)
        raise AssertionError("downloader must not run in dry-run")

    links = tmp_path / "links.txt"
    links.write_text(
        "https://medal.tv/games/valorant/clips/DryRun01\n",
        encoding="utf-8",
    )
    data_root = tmp_path / "data"
    monkeypatch.setattr(download_mod, "ytdlp_download", should_not_run)
    code = cli_main(
        [
            str(links),
            "--source",
            "friend_alex",
            "--data-root",
            str(data_root),
            "--dry-run",
        ]
    )
    assert code == 0
    assert called == []
    # dry-run may create the source dir via run(), but no media / no log of downloads required
    out = data_root / "incoming_clips" / "friend_alex"
    assert not (out / "fetch_log.csv").exists() or not list(out.glob("*.mp4"))


def test_cli_missing_ytdlp_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    links = tmp_path / "links.txt"
    links.write_text("https://medal.tv/games/valorant/clips/X\n", encoding="utf-8")

    import importlib.util as iu

    real_find = iu.find_spec

    def fake_find(name, *a, **k):
        if name == "yt_dlp":
            return None
        return real_find(name, *a, **k)

    monkeypatch.setattr(iu, "find_spec", fake_find)
    code = cli_main([str(links), "--source", "tester", "--data-root", str(tmp_path / "data")])
    assert code == 2


def test_cli_dry_run_works_without_ytdlp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    links = tmp_path / "links.txt"
    links.write_text(
        "https://medal.tv/games/league-of-legends/clips/LolClip1\n",
        encoding="utf-8",
    )

    import importlib.util as iu

    real_find = iu.find_spec

    def fake_find(name, *a, **k):
        if name == "yt_dlp":
            return None
        return real_find(name, *a, **k)

    monkeypatch.setattr(iu, "find_spec", fake_find)
    code = cli_main(
        [
            str(links),
            "--source",
            "friend_alex",
            "--data-root",
            str(tmp_path / "data"),
            "--dry-run",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "League_of_Legends" in out or "league-of-legends" in out


def test_cli_rejects_contributor_prefix(tmp_path: Path):
    links = tmp_path / "links.txt"
    links.write_text("https://medal.tv/games/valorant/clips/X\n", encoding="utf-8")
    code = cli_main(
        [str(links), "--source", "contributor_bob", "--data-root", str(tmp_path / "data"), "--dry-run"]
    )
    assert code == 2


def test_run_pause_between_downloads(tmp_path: Path):
    sleeps: list[float] = []
    urls = [
        "https://medal.tv/games/valorant/clips/P1aaa",
        "https://medal.tv/games/valorant/clips/P2bbb",
    ]
    run(
        urls,
        tmp_path / "src",
        downloader=_fake_downloader(),
        pause_s=2.5,
        sleep=sleeps.append,
    )
    assert sleeps == [2.5]
