"""Download clips with yt-dlp, log results, and write sorter hints."""

from __future__ import annotations

import csv
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from game_frame_classifier.sourcing.hashing import sha256_file

from .links import OLD_MEDAL_ERROR, UNSUPPORTED_SITE_ERROR, LinkInfo, game_for_slug, parse_link
from .naming import clip_file_name

LOG_NAME = "fetch_log.csv"
HINTS_NAME = "hints.csv"
LOG_COLUMNS = (
    "utc",
    "url",
    "site",
    "clip_id",
    "slug",
    "game",
    "other_name",
    "status",
    "file",
    "bytes",
    "sha256",
    "upload_time",
    "time_source",
    "width",
    "height",
    "fps",
    "format_id",
    "error",
)
HINTS_COLUMNS = ("file", "game", "other_name")


class RateLimited(Exception):
    """HTTP 429 from the downloader; stop the run."""


Downloader = Callable[[str, Path, str], dict]
SleepFn = Callable[[float], None]
NowFn = Callable[[], datetime]


@dataclass
class Summary:
    by_status: Counter = field(default_factory=Counter)
    by_game: Counter = field(default_factory=Counter)
    rate_limited: bool = False

    @property
    def exit_code(self) -> int:
        if self.rate_limited:
            return 3
        if self.by_status.get("failed", 0) > 0:
            return 1
        return 0


def ytdlp_download(url: str, out_dir: Path, temp_name: str) -> dict:
    """Download one URL with yt-dlp into out_dir/temp_name; return the info dict."""
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - CLI guards this
        raise RuntimeError("yt-dlp is not installed") from exc

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / temp_name
    # outtmpl without extension; merge_output_format supplies .mp4
    stem = dest.with_suffix("")
    opts = {
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "retries": 3,
        "outtmpl": str(stem) + ".%(ext)s",
        "quiet": True,
        "noprogress": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        text = str(exc)
        if "HTTP Error 429" in text:
            raise RateLimited(text) from exc
        raise

    final = out_dir / temp_name
    if not final.exists():
        # yt-dlp may leave the merged name slightly different; prefer .mp4 next to stem
        candidates = list(out_dir.glob(stem.name + ".*"))
        mp4s = [p for p in candidates if p.suffix.lower() == ".mp4"]
        if mp4s:
            mp4s[0].replace(final)
        elif candidates:
            candidates[0].replace(final)
    return info or {}


def _skip_key(info: LinkInfo) -> str:
    if info.site == "medal" and info.clip_id:
        return info.clip_id
    return info.url


def _load_ok_keys(log_path: Path, source_dir: Path) -> set[str]:
    """Keys with status=ok whose file still exists."""
    if not log_path.is_file():
        return set()
    ok: set[str] = set()
    with open(log_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("status") or "") != "ok":
                continue
            rel = (row.get("file") or "").strip()
            if not rel or not (source_dir / rel).is_file():
                continue
            clip_id = (row.get("clip_id") or "").strip()
            url = (row.get("url") or "").strip()
            site = (row.get("site") or "").strip()
            if site == "medal" and clip_id:
                ok.add(clip_id)
            elif url:
                ok.add(url)
    return ok


def _scrub_error(text: str) -> str:
    one = " ".join(str(text).split())
    one = re.sub(r"[A-Za-z]:\\[^\s\"']+", "<path>", one)
    one = re.sub(r"(?<![A-Za-z0-9_])/(?:Users|home|tmp|var|mnt|opt)[^\s\"']*", "<path>", one)
    return one[:500]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_log(log_path: Path, row: dict[str, object]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not log_path.is_file()
    with open(log_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in LOG_COLUMNS})


def _write_hints(source_dir: Path, log_path: Path) -> None:
    """Rewrite hints.csv from ok log rows that have a game or Other."""
    hints_path = source_dir / HINTS_NAME
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    if log_path.is_file():
        with open(log_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("status") or "") != "ok":
                    continue
                rel = (row.get("file") or "").strip()
                game = (row.get("game") or "").strip()
                other = (row.get("other_name") or "").strip()
                if not rel or not game:
                    continue
                if rel in seen:
                    # keep latest
                    rows = [r for r in rows if r["file"] != rel]
                seen.add(rel)
                rows.append({"file": rel, "game": game, "other_name": other})
    with open(hints_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HINTS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _info_timestamp(info: dict) -> datetime | None:
    ts = info.get("timestamp")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts))
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _upload_date_str(info: dict) -> str | None:
    raw = info.get("upload_date")
    if not raw:
        return None
    return str(raw)


def run(
    links: list[str],
    source_dir: Path,
    *,
    downloader: Downloader = ytdlp_download,
    pause_s: float = 3.0,
    limit: int | None = None,
    dry_run: bool = False,
    sleep: SleepFn = time.sleep,
    now: NowFn = datetime.now,
) -> Summary:
    """Implement Behaviour 4–9 for the given URLs."""
    source_dir = Path(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    log_path = source_dir / LOG_NAME
    summary = Summary()
    finished = _load_ok_keys(log_path, source_dir)
    downloads_done = 0
    pending_pause = False

    for url in links:
        info = parse_link(url)
        game, other_name = game_for_slug(info.slug)
        key = _skip_key(info)

        refusal = ""
        if info.site != "medal":
            refusal = UNSUPPORTED_SITE_ERROR
        elif info.clip_id and not info.slug:
            refusal = OLD_MEDAL_ERROR  # old /clips/<id> form: never download
        if refusal:
            if dry_run:
                print(f"dry-run fail  {url}  ({refusal})")
            else:
                _append_log(
                    log_path,
                    {
                        "utc": _utc_now_iso(),
                        "url": info.url,
                        "site": info.site,
                        "clip_id": info.clip_id,
                        "slug": info.slug,
                        "game": game,
                        "other_name": other_name,
                        "status": "failed",
                        "error": refusal,
                    },
                )
            summary.by_status["failed"] += 1
            continue

        if key and key in finished:
            summary.by_status["skipped"] += 1
            if dry_run:
                print(f"dry-run skip  {url}  already ok")
            else:
                _append_log(
                    log_path,
                    {
                        "utc": _utc_now_iso(),
                        "url": info.url,
                        "site": info.site,
                        "clip_id": info.clip_id,
                        "slug": info.slug,
                        "game": game,
                        "other_name": other_name,
                        "status": "skipped",
                        "error": "already downloaded",
                    },
                )
            continue

        if dry_run:
            label = game or (f"Other/{other_name}" if other_name else "(no game)")
            print(f"dry-run fetch  {url}  game={label}  slug={info.slug or '-'}  id={info.clip_id or '-'}")
            summary.by_status["ok"] += 1
            if game:
                summary.by_game[game] += 1
            continue

        if limit is not None and downloads_done >= limit:
            break

        if pending_pause and pause_s > 0:
            sleep(pause_s)
        pending_pause = True

        temp_name = f"_tmp_{info.clip_id or 'clip'}.mp4"
        try:
            meta = downloader(info.url, source_dir, temp_name)
        except RateLimited as exc:
            _append_log(
                log_path,
                {
                    "utc": _utc_now_iso(),
                    "url": info.url,
                    "site": info.site,
                    "clip_id": info.clip_id,
                    "slug": info.slug,
                    "game": game,
                    "other_name": other_name,
                    "status": "rate_limited",
                    "error": _scrub_error(exc),
                },
            )
            summary.by_status["rate_limited"] += 1
            summary.rate_limited = True
            _write_hints(source_dir, log_path)
            return summary
        except Exception as exc:
            _append_log(
                log_path,
                {
                    "utc": _utc_now_iso(),
                    "url": info.url,
                    "site": info.site,
                    "clip_id": info.clip_id,
                    "slug": info.slug,
                    "game": game,
                    "other_name": other_name,
                    "status": "failed",
                    "error": _scrub_error(exc),
                },
            )
            summary.by_status["failed"] += 1
            continue

        if not info.clip_id and meta.get("id"):
            info = LinkInfo(url=info.url, site=info.site, clip_id=str(meta["id"]), slug=info.slug)

        upload = _info_timestamp(meta)
        upload_date = _upload_date_str(meta)
        file_name, used, time_source = clip_file_name(info, upload, upload_date, now())
        temp_path = source_dir / temp_name
        final_path = source_dir / file_name
        if temp_path.exists():
            if final_path.exists() and final_path != temp_path:
                final_path.unlink()
            temp_path.replace(final_path)
        elif not final_path.exists():
            _append_log(
                log_path,
                {
                    "utc": _utc_now_iso(),
                    "url": info.url,
                    "site": info.site,
                    "clip_id": info.clip_id,
                    "slug": info.slug,
                    "game": game,
                    "other_name": other_name,
                    "status": "failed",
                    "error": "download produced no file",
                },
            )
            summary.by_status["failed"] += 1
            continue

        mtime = used.timestamp()
        os.utime(final_path, (mtime, mtime))
        size = final_path.stat().st_size
        digest = sha256_file(final_path)
        width = meta.get("width") or ""
        height = meta.get("height") or ""
        fps = meta.get("fps") or ""
        format_id = meta.get("format_id") or ""
        upload_time = used.strftime("%Y-%m-%dT%H:%M:%S")

        _append_log(
            log_path,
            {
                "utc": _utc_now_iso(),
                "url": info.url,
                "site": info.site,
                "clip_id": info.clip_id,
                "slug": info.slug,
                "game": game,
                "other_name": other_name,
                "status": "ok",
                "file": file_name,
                "bytes": size,
                "sha256": digest,
                "upload_time": upload_time,
                "time_source": time_source,
                "width": width,
                "height": height,
                "fps": fps,
                "format_id": format_id,
                "error": "",
            },
        )
        summary.by_status["ok"] += 1
        if game:
            summary.by_game[game] += 1
        finished.add(_skip_key(info))
        downloads_done += 1

    if not dry_run:
        _write_hints(source_dir, log_path)
    return summary


def print_summary(summary: Summary) -> None:
    print("status:", dict(summary.by_status))
    if summary.by_game:
        print("games:", dict(summary.by_game))
