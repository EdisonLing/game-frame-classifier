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
    read_link_files,
    read_links,
)
from game_frame_classifier.clip_fetch.users import (
    decide,
    load_users,
    proposed_source,
    validate_source,
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
    incoming = tmp_path / "incoming"
    url = "https://medal.tv/games/valorant/clips/AbCdEf123"
    sleeps: list[float] = []

    summary = run(
        [url],
        incoming,
        source_override="tester",
        downloader=_fake_downloader(),
        pause_s=3.0,
        sleep=sleeps.append,
        now=lambda: datetime(2025, 1, 1),
    )
    assert summary.exit_code == 0
    assert summary.by_status["ok"] == 1
    assert summary.by_game["Valorant"] == 1
    assert sleeps == []  # no pause after a single download

    log_path = incoming / "fetch_log.csv"
    with open(log_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert rows[0]["game"] == "Valorant"
    assert rows[0]["source"] == "tester"
    assert rows[0]["file"].startswith("tester/valorant__")
    assert (incoming / rows[0]["file"]).is_file()

    with open(incoming / "hints.csv", encoding="utf-8", newline="") as f:
        hints = list(csv.DictReader(f))
    assert hints == [{"file": rows[0]["file"], "game": "Valorant", "other_name": ""}]

    # Rerun skips finished link
    summary2 = run(
        [url],
        incoming,
        source_override="tester",
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
        incoming,
        source_override="tester",
        downloader=multi_dl,
        pause_s=0,
        limit=1,
        sleep=lambda _s: None,
    )
    assert summary3.by_status["ok"] == 1
    assert (incoming / "hints.csv").is_file()


def test_run_failed_link_exit_1(tmp_path: Path):
    def boom(url: str, out_dir: Path, temp_name: str) -> dict:
        raise RuntimeError(r"fail at C:\Users\someone\clips\x.mp4")

    incoming = tmp_path / "incoming"
    summary = run(
        ["https://medal.tv/games/valorant/clips/Fail001"],
        incoming,
        source_override="tester",
        downloader=boom,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 1
    assert summary.by_status["failed"] == 1
    with open(incoming / "fetch_log.csv", encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["status"] == "failed"
    assert "<path>" in row["error"]
    assert "C:\\Users" not in row["error"]


def test_run_rate_limited_exit_3(tmp_path: Path):
    def limited(url: str, out_dir: Path, temp_name: str) -> dict:
        raise RateLimited("HTTP Error 429: Too Many Requests")

    incoming = tmp_path / "incoming"
    summary = run(
        ["https://medal.tv/games/valorant/clips/Rate001"],
        incoming,
        source_override="tester",
        downloader=limited,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 3
    assert summary.rate_limited is True
    with open(incoming / "fetch_log.csv", encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["status"] == "rate_limited"


def test_run_old_medal_form_failed(tmp_path: Path):
    incoming = tmp_path / "incoming"
    summary = run(
        ["https://medal.tv/clips/OldForm01"],
        incoming,
        source_override="tester",
        downloader=_fake_downloader(),
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 1
    with open(incoming / "fetch_log.csv", encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["status"] == "failed"
    assert row["error"] == OLD_MEDAL_ERROR


def test_run_refuses_non_medal_links(tmp_path: Path):
    calls = []

    def downloader(*args, **kwargs):
        calls.append(args)
        raise AssertionError("must not download")

    incoming = tmp_path / "incoming"
    summary = run(
        ["https://www.youtube.com/watch?v=AbCdEf12345", "https://example.com/v/1"],
        incoming,
        source_override="tester",
        downloader=downloader,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 1 and calls == []
    with open(incoming / "fetch_log.csv", encoding="utf-8", newline="") as f:
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
        tmp_path / "incoming",
        source_override="tester",
        downloader=_fake_downloader(),
        pause_s=2.5,
        sleep=sleeps.append,
    )
    assert sleeps == [2.5]


# --- 1.1: multi-file links, skip, users, auto, override ---------------------


def test_read_link_files_folder_and_cross_file_dedupe(tmp_path: Path):
    folder = tmp_path / "links"
    folder.mkdir()
    (folder / "b.txt").write_text(
        "https://medal.tv/games/valorant/clips/bbb\n",
        encoding="utf-8",
    )
    (folder / "a.txt").write_text(
        "https://medal.tv/games/valorant/clips/aaa\n"
        "https://medal.tv/games/valorant/clips/bbb\n",
        encoding="utf-8",
    )
    extra = tmp_path / "extra.txt"
    extra.write_text(
        "https://medal.tv/games/cs2/clips/ccc\n"
        "https://medal.tv/games/valorant/clips/aaa\n",
        encoding="utf-8",
    )
    assert read_link_files([folder, extra]) == [
        "https://medal.tv/games/valorant/clips/aaa",
        "https://medal.tv/games/valorant/clips/bbb",
        "https://medal.tv/games/cs2/clips/ccc",
    ]


def test_ok_without_file_is_skipped_unless_refetch_missing(tmp_path: Path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    clip_id = "GoneClip01"
    url = f"https://medal.tv/games/valorant/clips/{clip_id}"
    # Seed an ok row whose file is gone.
    log = incoming / "fetch_log.csv"
    log.write_text(
        "utc,url,site,clip_id,slug,game,other_name,status,file,bytes,sha256,"
        "upload_time,time_source,width,height,fps,format_id,error,source,uploader_id,uploader\n"
        f"2026-01-01T00:00:00Z,{url},medal,{clip_id},valorant,Valorant,,ok,"
        f"tester/valorant__2026-01-01__00-00-00__{clip_id}.mp4,,,,,,,,,,tester,,\n",
        encoding="utf-8",
    )
    calls: list[str] = []

    def dl(u: str, out_dir: Path, temp_name: str) -> dict:
        calls.append(u)
        (out_dir / temp_name).write_bytes(b"x")
        return {"timestamp": 1_700_000_000, "id": clip_id, "title": "t"}

    summary = run(
        [url],
        incoming,
        source_override="tester",
        downloader=dl,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.by_status["skipped"] == 1
    assert calls == []

    # File still missing → refetch-missing downloads again.
    summary2 = run(
        [url],
        incoming,
        source_override="tester",
        refetch_missing=True,
        downloader=dl,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary2.by_status["ok"] == 1
    assert len(calls) == 1

    # File now under _archive → refetch-missing skips.
    archived = (
        incoming
        / "_archive"
        / "tester"
        / f"valorant__2026-01-01__00-00-00__{clip_id}.mp4"
    )
    archived.parent.mkdir(parents=True)
    # Move the downloaded file into archive (any matching __id.mp4 counts).
    for path in (incoming / "tester").glob(f"*__{clip_id}.mp4"):
        path.replace(archived)
        break
    calls.clear()
    summary3 = run(
        [url],
        incoming,
        source_override="tester",
        refetch_missing=True,
        downloader=dl,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary3.by_status["skipped"] == 1
    assert calls == []


def test_users_decide_y_n_typed_and_invalid(tmp_path: Path):
    assert proposed_source("Uploader A!") == "friend_uploader_a"
    assert validate_source("friend_custom") == "friend_custom"
    assert validate_source("contributor_x") == ""
    assert validate_source("_bad") == ""

    answers = iter(["y", "n", "!!!", "friend_shared", "contributor_no", "y"])
    decided = decide(
        [
            ("id_1", "uploader_a", 2),
            ("id_2", "uploader_b", 1),
            ("id_3", "uploader_c", 1),
            ("id_4", "uploader_d", 1),
        ],
        ask=lambda _p: next(answers),
    )
    assert decided["id_1"]["allowed"] == "yes" and decided["id_1"]["source"] == "friend_uploader_a"
    assert decided["id_2"]["allowed"] == "no"
    assert decided["id_3"]["allowed"] == "yes" and decided["id_3"]["source"] == "friend_shared"
    assert decided["id_4"]["allowed"] == "yes" and decided["id_4"]["source"] == "friend_uploader_d"

    pending = decide([("id_5", "uploader_e", 1)], ask=None)
    assert pending["id_5"]["allowed"] == ""


def test_auto_mode_mixed_uploaders(tmp_path: Path):
    incoming = tmp_path / "incoming"
    users_path = tmp_path / "medal_users.csv"
    users_path.write_text(
        "uploader_id,uploader,source,allowed,first_seen,note\n"
        "id_111,uploader_a,friend_a,yes,2026-01-01,\n"
        "id_222,uploader_b,friend_b,no,2026-01-01,\n",
        encoding="utf-8",
    )
    links = [
        "https://medal.tv/games/valorant/clips/clip_a1",
        "https://medal.tv/games/valorant/clips/clip_a2",
        "https://medal.tv/games/cs2/clips/clip_b1",
        "https://medal.tv/games/minecraft/clips/clip_c1",
    ]
    meta_map = {
        links[0]: {"uploader_id": "id_111", "uploader": "uploader_a"},
        links[1]: {"uploader_id": "id_111", "uploader": "uploader_a"},
        links[2]: {"uploader_id": "id_222", "uploader": "uploader_b"},
        links[3]: {"uploader_id": "id_333", "uploader": "uploader_c"},
    }

    def fake_meta(url: str) -> dict:
        return meta_map[url]

    def fake_dl(url: str, out_dir: Path, temp_name: str) -> dict:
        (out_dir / temp_name).write_bytes(b"clip")
        return {"timestamp": 1_700_000_000, "id": "x", "title": "t", **meta_map[url]}

    summary = run(
        links,
        incoming,
        users_path=users_path,
        ask=None,
        metadata=fake_meta,
        downloader=fake_dl,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 4
    assert summary.by_status["ok"] == 2
    assert summary.by_status["not_allowed"] == 1
    assert summary.by_status["pending_permission"] == 1
    assert (incoming / "friend_a").is_dir()
    assert list((incoming / "friend_a").glob("*.mp4"))
    assert not (incoming / "friend_b").exists()
    assert "id_333" in summary.pending
    users = load_users(users_path)
    assert users["id_333"]["allowed"] == ""
    assert users["id_111"]["source"] == "friend_a"  # unchanged
    with open(incoming / "fetch_log.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert {"source", "uploader_id", "uploader"} <= set(rows[0].keys())
    assert (incoming / "hints.csv").is_file()


def test_source_override_skips_metadata_and_prompts(tmp_path: Path):
    incoming = tmp_path / "incoming"
    meta_calls: list[str] = []

    def fake_meta(url: str) -> dict:
        meta_calls.append(url)
        raise AssertionError("no metadata pass in --source mode")

    def fake_dl(url: str, out_dir: Path, temp_name: str) -> dict:
        (out_dir / temp_name).write_bytes(b"x")
        return {
            "timestamp": 1_700_000_000,
            "id": "Ov1",
            "title": "t",
            "uploader_id": "id_999",
            "uploader": "uploader_z",
        }

    summary = run(
        ["https://medal.tv/games/valorant/clips/OvClip1"],
        incoming,
        source_override="friend_alex",
        ask=lambda _p: (_ for _ in ()).throw(AssertionError("no ask")),
        metadata=fake_meta,
        downloader=fake_dl,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert meta_calls == []
    assert summary.exit_code == 0
    with open(incoming / "fetch_log.csv", encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["source"] == "friend_alex"
    assert row["uploader_id"] == "id_999"
    assert row["uploader"] == "uploader_z"


def test_two_uploaders_one_source(tmp_path: Path):
    incoming = tmp_path / "incoming"
    users_path = tmp_path / "users.csv"
    answers = iter(["friend_shared", "friend_shared"])

    def fake_meta(url: str) -> dict:
        if "A1" in url:
            return {"uploader_id": "id_a", "uploader": "name_a"}
        return {"uploader_id": "id_b", "uploader": "name_b"}

    def fake_dl(url: str, out_dir: Path, temp_name: str) -> dict:
        (out_dir / temp_name).write_bytes(b"x")
        return {"timestamp": 1_700_000_000, "id": "x", "title": "t"}

    summary = run(
        [
            "https://medal.tv/games/valorant/clips/A1aaa",
            "https://medal.tv/games/valorant/clips/B1bbb",
        ],
        incoming,
        users_path=users_path,
        ask=lambda _p: next(answers),
        metadata=fake_meta,
        downloader=fake_dl,
        pause_s=0,
        sleep=lambda _s: None,
    )
    assert summary.exit_code == 0
    assert summary.by_source["friend_shared"] == 2
    assert len(list((incoming / "friend_shared").glob("*.mp4"))) == 2
    users = load_users(users_path)
    assert users["id_a"]["source"] == users["id_b"]["source"] == "friend_shared"
