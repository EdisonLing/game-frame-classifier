"""Unit tests for channel sampling (no network)."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from game_frame_classifier.clip_fetch.cli import main as cli_main
from game_frame_classifier.clip_fetch.download import LOG_COLUMNS
from game_frame_classifier.clip_fetch.sample import (
    apply_preview_selection,
    fill_to_budget,
    held_videos,
    is_channel_url,
    plan_sample,
    recency_weights,
    run_sample,
    SampleCandidate,
    weighted_order,
)


def _cand(vid: str, dur: float, rank: int = 0, title: str = "") -> SampleCandidate:
    return SampleCandidate(
        video_id=vid,
        url=f"https://www.youtube.com/watch?v={vid}",
        title=title or vid,
        duration_s=dur,
        rank=rank,
    )


def _entries(n: int, *, duration_s: float = 600.0) -> list[dict]:
    out = []
    for i in range(n):
        vid = f"vid{i:04d}xxxxx"[:11]
        out.append(
            {
                "id": vid,
                "title": f"Video {i}",
                "duration": duration_s,
                "channel_id": "UCchannelfake1",
                "channel": "Fake Channel",
            }
        )
    return out


# --- weights / pick ---------------------------------------------------------


def test_recency_weights_zero_equal():
    w = recency_weights(5, 0.0)
    assert len(w) == 5
    assert all(abs(x - 1.0) < 1e-12 for x in w)


def test_recency_weights_decreasing():
    w = recency_weights(5, 2.0)
    assert w[0] > w[1] > w[2] > w[3] > w[4]


def test_recency_weights_single():
    assert recency_weights(1, 2.0) == [1.0]
    assert recency_weights(0, 2.0) == []


def test_weighted_order_same_seed():
    w = recency_weights(10, 2.0)
    assert weighted_order(w, 7) == weighted_order(w, 7)


def test_weighted_order_different_seeds_often_differ():
    w = recency_weights(20, 2.0)
    a = weighted_order(w, 1)
    b = weighted_order(w, 2)
    assert a != b


def test_weighted_order_bias_favours_newest_quarter():
    n = 40
    w = recency_weights(n, 3.0)
    newest = set(range(n // 4))
    oldest = set(range(3 * n // 4, n))
    new_first = 0
    old_first = 0
    for seed in range(2000):
        order = weighted_order(w, seed)
        if order[0] in newest:
            new_first += 1
        if order[0] in oldest:
            old_first += 1
    assert new_first > old_first


def test_weighted_order_bias_zero_roughly_equal():
    n = 8
    w = recency_weights(n, 0.0)
    counts = [0] * n
    for seed in range(4000):
        counts[weighted_order(w, seed)[0]] += 1
    mean = sum(counts) / n
    assert all(abs(c - mean) < mean * 0.25 for c in counts)


# --- fill / overshoot -------------------------------------------------------


def test_fill_allows_overshoot_within_20_percent():
    # target 1000 s; ceiling 1200. First 900, second 250 → take both (1150).
    picks, accrued = fill_to_budget(
        [_cand("a", 900), _cand("b", 250), _cand("c", 100)],
        accrued_s=0,
        target_s=1000,
    )
    assert [p.video_id for p in picks] == ["a", "b"]
    assert accrued == 1150


def test_fill_skips_too_long_and_stops_under():
    # target 1000; ceiling 1200. 900 then 500 (skip) then 400 (skip) → under.
    picks, accrued = fill_to_budget(
        [_cand("a", 900), _cand("b", 500), _cand("c", 400)],
        accrued_s=0,
        target_s=1000,
    )
    assert [p.video_id for p in picks] == ["a"]
    assert accrued == 900


def test_fill_skips_then_takes_shorter():
    picks, accrued = fill_to_budget(
        [_cand("a", 900), _cand("b", 500), _cand("c", 200)],
        accrued_s=0,
        target_s=1000,
    )
    assert [p.video_id for p in picks] == ["a", "c"]
    assert accrued == 1100


# --- held / plan ------------------------------------------------------------


def test_held_videos_from_log_and_file(tmp_path: Path):
    source = "yt_fakechannel"
    incoming = tmp_path / "incoming_clips"
    src_dir = incoming / source
    src_dir.mkdir(parents=True)
    clip = src_dir / "unlabelled__2026-01-01__00-00-00__abcdefghijk.mp4"
    clip.write_bytes(b"x")
    log = incoming / "fetch_log.csv"
    with open(log, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        w.writeheader()
        w.writerow(
            {
                "utc": "2026-01-01T00:00:00Z",
                "url": "https://www.youtube.com/watch?v=abcdefghijk",
                "site": "youtube",
                "clip_id": "abcdefghijk",
                "status": "ok",
                "file": f"{source}/{clip.name}",
                "uploader_id": "yt:UCchannelfake1",
                "source": source,
            }
        )
    held = held_videos(
        tmp_path,
        source,
        "UCchannelfake1",
        durations={"abcdefghijk": 120.0},
    )
    assert set(held) == {"abcdefghijk"}
    assert held["abcdefghijk"][1] == 120.0


def test_held_ignores_other_source_file(tmp_path: Path):
    source = "yt_fakechannel"
    other = "yt_other"
    incoming = tmp_path / "incoming_clips"
    (incoming / other).mkdir(parents=True)
    clip = incoming / other / "unlabelled__2026-01-01__00-00-00__abcdefghijk.mp4"
    clip.write_bytes(b"x")
    log = incoming / "fetch_log.csv"
    with open(log, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        w.writeheader()
        w.writerow(
            {
                "utc": "2026-01-01T00:00:00Z",
                "url": "https://www.youtube.com/watch?v=abcdefghijk",
                "site": "youtube",
                "clip_id": "abcdefghijk",
                "status": "ok",
                "file": f"{other}/{clip.name}",
                "uploader_id": "yt:UCotherchannel",
                "source": other,
            }
        )
    held = held_videos(tmp_path, source, "UCchannelfake1", durations={"abcdefghijk": 120.0})
    assert held == {}


def test_plan_new_excludes_ok_even_without_file(tmp_path: Path):
    entries = _entries(5, duration_s=1800)
    ok = {entries[0]["id"], entries[1]["id"]}
    plan = plan_sample(
        entries,
        held={},
        mode="new",
        max_time_h=1.0,
        bias=0.0,
        seed=1,
        ok_ids=ok,
    )
    pick_ids = {c.video_id for c in plan.picks}
    assert pick_ids.isdisjoint(ok)


def test_plan_total_noop_when_held_enough(tmp_path: Path):
    entries = _entries(3, duration_s=3600)
    fake = tmp_path / "f.mp4"
    fake.write_bytes(b"x")
    held = {
        entries[0]["id"]: (fake, 4000.0),
        entries[1]["id"]: (fake, 4000.0),
    }
    plan = plan_sample(
        entries,
        held=held,
        mode="total",
        max_time_h=2.0,
        bias=0.0,
        seed=1,
        ok_ids=set(held),
    )
    assert plan.noop
    assert plan.picks == []


def test_plan_total_adds_when_below():
    entries = _entries(6, duration_s=1800)
    fake = Path("x.mp4")
    held = {entries[0]["id"]: (fake, 1800.0)}
    plan = plan_sample(
        entries,
        held=held,
        mode="total",
        max_time_h=1.5,  # 5400 s; held 1800 → need more
        bias=0.0,
        seed=3,
        ok_ids=set(held),
    )
    assert not plan.noop
    assert plan.picks
    assert entries[0]["id"] not in {c.video_id for c in plan.picks}


def test_preview_selection_drops_toggled_off():
    pool = [_cand("a", 600), _cand("b", 600), _cand("c", 600), _cand("d", 600)]
    picks, rejected, accrued = apply_preview_selection(
        pool,
        ["a", "c", "d"],
        accrued_s=0,
        target_s=1200,
    )
    assert [p.video_id for p in rejected] == ["b"]
    assert [p.video_id for p in picks] == ["a", "c"]
    assert accrued == 1200


# --- channel URL ------------------------------------------------------------


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://www.youtube.com/@example", True),
        ("https://www.youtube.com/@example/videos", True),
        ("https://www.youtube.com/channel/UCabcdef", True),
        ("https://www.youtube.com/watch?v=abcdefghijk", False),
        ("https://youtu.be/abcdefghijk", False),
        ("https://www.youtube.com/playlist?list=PLxxxx", False),
        ("https://www.youtube.com/results?search_query=game", False),
    ],
)
def test_is_channel_url(url, ok):
    assert is_channel_url(url) is ok


# --- run_sample / CLI -------------------------------------------------------


def test_run_sample_dry_run_writes_nothing(tmp_path: Path):
    users = tmp_path / "users.csv"

    def fake_list(_url: str) -> list[dict]:
        return _entries(8, duration_s=900)

    code, summary = run_sample(
        "https://www.youtube.com/@example",
        max_time_h=0.5,
        seed=1,
        dry_run=True,
        preview=False,
        data_root=tmp_path,
        users_path=users,
        lister=fake_list,
        now=lambda: datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    assert code == 0
    assert summary is not None
    assert not users.exists()
    assert not (tmp_path / "clip_links").exists()
    assert not (tmp_path / "incoming_clips" / "fetch_log.csv").exists()


def test_run_sample_downloads_and_picks_file(tmp_path: Path):
    users = tmp_path / "users.csv"
    downloaded: list[str] = []

    def fake_list(_url: str) -> list[dict]:
        return _entries(10, duration_s=600)

    def fake_meta(url: str) -> dict:
        vid = url.rsplit("=", 1)[-1]
        return {
            "id": vid,
            "channel_id": "UCchannelfake1",
            "channel": "Fake Channel",
            "duration": 600,
            "width": 1280,
            "height": 720,
            "fps": 30,
            "timestamp": 1_700_000_000,
        }

    def fake_dl(url: str, out_dir: Path, temp_name: str, **_kw) -> dict:
        downloaded.append(url)
        dest = Path(out_dir) / temp_name
        dest.write_bytes(b"fake")
        return fake_meta(url)

    code, summary = run_sample(
        "https://www.youtube.com/@example",
        max_time_h=0.5,  # 1800 s → 3 × 600
        seed=5,
        dry_run=False,
        preview=False,
        game="Minecraft",
        data_root=tmp_path,
        users_path=users,
        lister=fake_list,
        downloader=fake_dl,
        metadata=fake_meta,
        pause_s=0,
        now=lambda: datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    assert code == 0
    assert summary is not None
    assert summary.by_status.get("ok", 0) >= 1
    picks = list((tmp_path / "clip_links").glob("*_sample.txt"))
    assert len(picks) == 1
    text = picks[0].read_text(encoding="utf-8")
    assert "# seed: 5" in text
    assert "# mode: new" in text
    assert "Minecraft" in text


def test_picks_file_lists_only_downloaded_videos(tmp_path: Path):
    users = tmp_path / "users.csv"
    attempted: list[str] = []

    def fake_list(_url: str) -> list[dict]:
        return _entries(10, duration_s=600)

    def fake_meta(url: str) -> dict:
        vid = url.rsplit("=", 1)[-1]
        return {
            "id": vid,
            "channel_id": "UCchannelfake1",
            "channel": "Fake Channel",
            "duration": 600,
            "width": 1280,
            "height": 720,
            "fps": 30,
            "timestamp": 1_700_000_000,
        }

    def fake_dl(url: str, out_dir: Path, temp_name: str, **_kw) -> dict:
        attempted.append(url)
        if len(attempted) == 1:
            raise RuntimeError("video unavailable")
        dest = Path(out_dir) / temp_name
        dest.write_bytes(b"fake")
        return fake_meta(url)

    code, summary = run_sample(
        "https://www.youtube.com/@example",
        max_time_h=0.5,
        seed=5,
        preview=False,
        data_root=tmp_path,
        users_path=users,
        lister=fake_list,
        downloader=fake_dl,
        metadata=fake_meta,
        pause_s=0,
        now=lambda: datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    assert summary is not None and summary.by_status.get("failed", 0) == 1
    text = next((tmp_path / "clip_links").glob("*_sample.txt")).read_text(encoding="utf-8")
    listed = [line.split(",")[0] for line in text.splitlines() if line.startswith("https://")]
    assert attempted[0] not in listed
    assert sorted(listed) == sorted(attempted[1:])


def test_run_sample_preview_rejects(tmp_path: Path):
    users = tmp_path / "users.csv"

    def fake_list(_url: str) -> list[dict]:
        return _entries(8, duration_s=600)

    def fake_meta(url: str) -> dict:
        vid = url.rsplit("=", 1)[-1]
        return {
            "id": vid,
            "channel_id": "UCchannelfake1",
            "channel": "Fake Channel",
            "duration": 600,
            "width": 1280,
            "height": 720,
            "fps": 30,
            "timestamp": 1_700_000_000,
        }

    def fake_dl(url: str, out_dir: Path, temp_name: str, **_kw) -> dict:
        dest = Path(out_dir) / temp_name
        dest.write_bytes(b"fake")
        return fake_meta(url)

    def fake_preview(cands):
        # drop the first candidate
        return [c.video_id for c in cands[1:]]

    code, _summary = run_sample(
        "https://www.youtube.com/@example",
        max_time_h=0.5,
        seed=2,
        preview=True,
        preview_fn=fake_preview,
        data_root=tmp_path,
        users_path=users,
        lister=fake_list,
        downloader=fake_dl,
        metadata=fake_meta,
        pause_s=0,
        now=lambda: datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    assert code == 0
    text = next((tmp_path / "clip_links").glob("*_sample.txt")).read_text(encoding="utf-8")
    assert "# skipped_preview:" in text


def test_preview_keeps_only_approved_even_when_under_budget(tmp_path: Path):
    """After preview, do not pull unpreviewed ids to fill the time budget."""
    users = tmp_path / "users.csv"
    downloaded: list[str] = []

    def fake_list(_url: str) -> list[dict]:
        return _entries(12, duration_s=600)

    def fake_meta(url: str) -> dict:
        vid = url.rsplit("=", 1)[-1]
        return {
            "id": vid,
            "channel_id": "UCchannelfake1",
            "channel": "Fake Channel",
            "duration": 600,
            "width": 1280,
            "height": 720,
            "fps": 30,
            "timestamp": 1_700_000_000,
        }

    def fake_dl(url: str, out_dir: Path, temp_name: str, **_kw) -> dict:
        downloaded.append(url.rsplit("=", 1)[-1])
        dest = Path(out_dir) / temp_name
        dest.write_bytes(b"fake")
        return fake_meta(url)

    kept_only: list[str] = []

    def fake_preview(cands):
        # Approve only the first pool item; leave the rest off.
        kept_only.clear()
        kept_only.append(cands[0].video_id)
        return list(kept_only)

    code, summary = run_sample(
        "https://www.youtube.com/@example",
        max_time_h=0.5,  # 1800 s — one 600 s keep leaves a large shortfall
        seed=2,
        preview=True,
        preview_fn=fake_preview,
        data_root=tmp_path,
        users_path=users,
        lister=fake_list,
        downloader=fake_dl,
        metadata=fake_meta,
        pause_s=0,
        now=lambda: datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    assert code == 0
    assert summary is not None
    assert downloaded == kept_only
    assert summary.by_status.get("ok", 0) == 1
    text = next((tmp_path / "clip_links").glob("*_sample.txt")).read_text(encoding="utf-8")
    assert text.count("# skipped_preview:") >= 1


def test_cli_channel_rejects_video_url():
    code = cli_main(["--channel", "https://www.youtube.com/watch?v=abcdefghijk", "--dry-run"])
    assert code == 2


def test_cli_channel_rejects_playlist():
    code = cli_main(
        ["--channel", "https://www.youtube.com/playlist?list=PLxxxx", "--max-time", "1", "--dry-run"]
    )
    assert code == 2


def test_cli_channel_rejects_max_time_zero():
    code = cli_main(["--channel", "https://www.youtube.com/@example", "--max-time", "0"])
    assert code == 2


def test_cli_channel_rejects_bad_mode():
    with pytest.raises(SystemExit) as exc:
        cli_main(
            ["--channel", "https://www.youtube.com/@example", "--mode", "shrink", "--dry-run"]
        )
    assert exc.value.code == 2


def test_cli_channel_rejects_links_combo(tmp_path: Path):
    links = tmp_path / "links.txt"
    links.write_text("https://www.youtube.com/watch?v=abcdefghijk\n", encoding="utf-8")
    code = cli_main(
        ["--channel", "https://www.youtube.com/@example", str(links), "--dry-run"]
    )
    assert code == 2
