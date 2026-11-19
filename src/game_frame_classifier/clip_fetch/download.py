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
from typing import Callable, Sequence

from game_frame_classifier.sourcing.hashing import sha256_file

from .links import (
    OLD_MEDAL_ERROR,
    UNSUPPORTED_SITE_ERROR,
    LinkEntry,
    LinkInfo,
    game_for_slug,
    parse_link,
)
from .naming import clip_file_name
from .users import AskFn, append_user, decide, load_users

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
    "source",
    "uploader_id",
    "uploader",
    "content_type",
    "content_type_origin",
)
HINTS_COLUMNS = ("file", "game", "other_name", "content_type", "content_type_origin")

YOUTUBE_FORMAT = "bestvideo[height<=720]+bestaudio/best[height<=720]"
MEDAL_FORMAT = "bestvideo*+bestaudio/best"


class RateLimited(Exception):
    """HTTP 429 from the downloader; stop the run."""


Downloader = Callable[[str, Path, str], dict]
MetadataFn = Callable[[str], dict]
SleepFn = Callable[[float], None]
NowFn = Callable[[], datetime]


@dataclass
class Summary:
    by_status: Counter = field(default_factory=Counter)
    by_game: Counter = field(default_factory=Counter)
    by_source: Counter = field(default_factory=Counter)
    pending: list[str] = field(default_factory=list)
    rate_limited: bool = False
    unlabelled: int = 0

    @property
    def exit_code(self) -> int:
        if self.rate_limited:
            return 3
        if self.by_status.get("pending_permission", 0) > 0 or self.pending:
            return 4
        if self.by_status.get("failed", 0) > 0:
            return 1
        return 0


def ytdlp_download(url: str, out_dir: Path, temp_name: str, *, format_str: str | None = None) -> dict:
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
        "format": format_str or MEDAL_FORMAT,
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


def ytdlp_metadata(url: str) -> dict:
    """Read clip metadata without downloading."""
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - CLI guards this
        raise RuntimeError("yt-dlp is not installed") from exc

    opts = {
        "quiet": True,
        "noprogress": True,
        "noplaylist": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        text = str(exc)
        if "HTTP Error 429" in text:
            raise RateLimited(text) from exc
        raise
    return info or {}


def _skip_key(info: LinkInfo) -> str:
    if info.site in ("medal", "youtube") and info.clip_id:
        return info.clip_id
    return info.url


def _load_ok_keys(log_path: Path) -> set[str]:
    """Keys with any status=ok row (file may be gone)."""
    if not log_path.is_file():
        return set()
    ok: set[str] = set()
    with open(log_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("status") or "") != "ok":
                continue
            clip_id = (row.get("clip_id") or "").strip()
            url = (row.get("url") or "").strip()
            site = (row.get("site") or "").strip()
            if site in ("medal", "youtube") and clip_id:
                ok.add(clip_id)
            elif url:
                ok.add(url)
    return ok


def _has_clip_file(incoming_dir: Path, clip_id: str) -> bool:
    """True if any *.mp4 under incoming ends with __<clip_id>.mp4 (_archive included)."""
    if not clip_id or not incoming_dir.is_dir():
        return False
    suffix = f"__{clip_id}.mp4"
    for path in incoming_dir.rglob("*.mp4"):
        if path.name.endswith(suffix):
            return True
    return False


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


def _write_hints(incoming_dir: Path, log_path: Path) -> None:
    """Rewrite hints.csv from ok log rows (including unlabelled, game empty)."""
    hints_path = incoming_dir / HINTS_NAME
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    if log_path.is_file():
        with open(log_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("status") or "") != "ok":
                    continue
                rel = (row.get("file") or "").strip()
                if not rel:
                    continue
                if rel in seen:
                    rows = [r for r in rows if r["file"] != rel]
                seen.add(rel)
                rows.append(
                    {
                        "file": rel,
                        "game": (row.get("game") or "").strip(),
                        "other_name": (row.get("other_name") or "").strip(),
                        "content_type": (row.get("content_type") or "").strip(),
                        "content_type_origin": (row.get("content_type_origin") or "").strip(),
                    }
                )
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


def _uploader_fields(meta: dict, site: str) -> tuple[str, str]:
    if site == "youtube":
        uid = meta.get("channel_id") or meta.get("uploader_id")
        name = meta.get("channel") or meta.get("uploader")
        uid_s = str(uid) if uid is not None and str(uid) else ""
        if uid_s and not uid_s.startswith("yt:"):
            uid_s = f"yt:{uid_s}"
        return (uid_s, str(name) if name else "")
    uid = meta.get("uploader_id")
    name = meta.get("uploader")
    return (str(uid) if uid is not None and str(uid) else "", str(name) if name else "")


def _resolve_game(entry: LinkEntry, info: LinkInfo) -> tuple[str, str]:
    if entry.game:
        return entry.game, entry.other_name if entry.game == "Other" else ""
    return game_for_slug(info.slug)


def _resolve_content_type(
    entry: LinkEntry,
    users: dict[str, dict[str, str]],
    uploader_id: str,
) -> tuple[str, str]:
    if entry.content_type:
        return entry.content_type, "video"
    row = users.get(uploader_id) or {}
    channel_ct = (row.get("content_type") or "").strip()
    if channel_ct:
        return channel_ct, "channel"
    return "", ""


def _as_entries(links: Sequence[str | LinkEntry]) -> list[LinkEntry]:
    out: list[LinkEntry] = []
    for item in links:
        if isinstance(item, LinkEntry):
            out.append(item)
        else:
            out.append(LinkEntry(url=str(item)))
    return out


def _duration_s(meta: dict) -> float | None:
    raw = meta.get("duration")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def run(
    links: Sequence[str | LinkEntry],
    incoming_dir: Path,
    *,
    source_override: str | None = None,
    users_path: Path | None = None,
    ask: AskFn | None = None,
    refetch_missing: bool = False,
    downloader: Downloader = ytdlp_download,
    metadata: MetadataFn = ytdlp_metadata,
    pause_s: float = 3.0,
    limit: int | None = None,
    dry_run: bool = False,
    sleep: SleepFn = time.sleep,
    now: NowFn = datetime.now,
    max_minutes: float = 60.0,
) -> Summary:
    """Download links into incoming_dir/<source>/; log and hints at incoming_dir."""
    incoming_dir = Path(incoming_dir)
    incoming_dir.mkdir(parents=True, exist_ok=True)
    log_path = incoming_dir / LOG_NAME
    summary = Summary()
    finished = _load_ok_keys(log_path)
    downloads_done = 0
    pending_pause = False
    auto = source_override is None
    entries = _as_entries(links)

    # Parse and classify refusals / skips first.
    work: list[tuple[LinkEntry, LinkInfo, str, str]] = []  # entry, info, game, other_name
    for entry in entries:
        info = parse_link(entry.url)
        game, other_name = _resolve_game(entry, info)
        key = _skip_key(info)

        refusal = ""
        if info.site not in ("medal", "youtube"):
            refusal = UNSUPPORTED_SITE_ERROR
        elif info.site == "medal" and info.clip_id and not info.slug:
            refusal = OLD_MEDAL_ERROR
        elif info.site == "youtube" and not info.clip_id:
            refusal = "could not parse YouTube video id"
        if refusal:
            if dry_run:
                print(f"dry-run fail  {entry.url}  ({refusal})")
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
                        "source": source_override or "",
                        "content_type": entry.content_type,
                    },
                )
            summary.by_status["failed"] += 1
            continue

        if key and key in finished:
            refetch = False
            if refetch_missing and info.clip_id and not _has_clip_file(incoming_dir, info.clip_id):
                refetch = True
            if not refetch:
                summary.by_status["skipped"] += 1
                if dry_run:
                    print(f"dry-run skip  {entry.url}  already ok")
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
                            "source": source_override or "",
                            "content_type": entry.content_type,
                        },
                    )
                continue

        work.append((entry, info, game, other_name))

    if dry_run:
        for entry, info, game, other_name in work:
            label = game or (f"Other/{other_name}" if other_name else "(no game)")
            src = source_override or "(auto)"
            print(
                f"dry-run fetch  {info.url}  game={label}  slug={info.slug or '-'}  "
                f"id={info.clip_id or '-'}  source={src}"
            )
            summary.by_status["ok"] += 1
            if game:
                summary.by_game[game] += 1
            else:
                summary.unlabelled += 1
            if source_override:
                summary.by_source[source_override] += 1
        return summary

    # Metadata pass (automatic mode always; override mode when max_minutes needs a check).
    meta_by_url: dict[str, dict] = {}
    if auto:
        for entry, info, game, other_name in work:
            if pending_pause and pause_s > 0:
                sleep(pause_s)
            pending_pause = True
            try:
                meta = metadata(info.url)
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
                        "content_type": entry.content_type,
                    },
                )
                summary.by_status["rate_limited"] += 1
                summary.rate_limited = True
                _write_hints(incoming_dir, log_path)
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
                        "content_type": entry.content_type,
                    },
                )
                summary.by_status["failed"] += 1
                continue
            uid, uname = _uploader_fields(meta, info.site)
            if not uid:
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
                        "error": "no uploader in metadata; use --source",
                        "content_type": entry.content_type,
                    },
                )
                summary.by_status["failed"] += 1
                continue
            meta_by_url[info.url] = meta

        # Drop failed / rate-limited from work (already logged).
        work = [(e, i, g, o) for e, i, g, o in work if i.url in meta_by_url]

        # Uploader decisions.
        if users_path is None:
            raise ValueError("users_path is required in automatic mode")
        users = load_users(users_path)
        # Count clips per new uploader in first-appearance order.
        counts: dict[str, int] = {}
        order: list[tuple[str, str, str]] = []  # (id, name, prefix)
        for entry, info, _g, _o in work:
            meta = meta_by_url[info.url]
            uid, uname = _uploader_fields(meta, info.site)
            known = users.get(uid)
            if known is not None and (known.get("allowed") or "").strip():
                continue  # decided (yes or no)
            if uid not in counts:
                counts[uid] = 0
                prefix = "yt" if info.site == "youtube" else "friend"
                order.append((uid, uname, prefix))
            counts[uid] += 1
        new_list = [(uid, name, counts[uid], prefix) for uid, name, prefix in order]
        decided = decide(new_list, ask)
        for uid, row in decided.items():
            append_user(users_path, row)
            users[uid] = row

        # Assign source or log not_allowed / pending; resolve content type.
        assigned: list[tuple[LinkEntry, LinkInfo, str, str, str, str, str, str, str]] = []
        # entry, info, game, other, source, uploader_id, uploader, content_type, origin
        for entry, info, game, other_name in work:
            meta = meta_by_url[info.url]
            uid, uname = _uploader_fields(meta, info.site)
            row = users.get(uid) or {}
            allowed = (row.get("allowed") or "").strip().lower()
            source = (row.get("source") or "").strip()
            ct, cto = _resolve_content_type(entry, users, uid)
            if allowed == "yes" and source:
                assigned.append((entry, info, game, other_name, source, uid, uname, ct, cto))
            elif allowed == "no":
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
                        "status": "not_allowed",
                        "source": source,
                        "uploader_id": uid,
                        "uploader": uname,
                        "content_type": ct,
                        "content_type_origin": cto,
                    },
                )
                summary.by_status["not_allowed"] += 1
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
                        "status": "pending_permission",
                        "source": source,
                        "uploader_id": uid,
                        "uploader": uname,
                        "content_type": ct,
                        "content_type_origin": cto,
                    },
                )
                summary.by_status["pending_permission"] += 1
                if uid not in summary.pending:
                    summary.pending.append(uid)
        download_items = assigned
        users_for_ct = users
    else:
        users_for_ct = load_users(users_path) if users_path else {}
        download_items = [
            (entry, info, game, other_name, source_override, "", "", entry.content_type, "video" if entry.content_type else "")
            for entry, info, game, other_name in work
        ]

    # Downloads.
    pending_pause = False  # pause again between downloads (after metadata)
    max_s = float(max_minutes) * 60.0 if max_minutes and max_minutes > 0 else None
    for entry, info, game, other_name, source, uploader_id, uploader, content_type, content_type_origin in download_items:
        if limit is not None and downloads_done >= limit:
            break

        if pending_pause and pause_s > 0:
            sleep(pause_s)
        pending_pause = True

        # Duration check before download when metadata is already available (auto mode).
        meta_pre = meta_by_url.get(info.url)
        if max_s is not None and meta_pre is not None:
            dur = _duration_s(meta_pre)
            if dur is not None and dur > max_s:
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
                        "status": "skipped_long",
                        "error": f"duration {dur:g}s > max {max_minutes:g} min",
                        "source": source,
                        "uploader_id": uploader_id,
                        "uploader": uploader,
                        "content_type": content_type,
                        "content_type_origin": content_type_origin,
                    },
                )
                summary.by_status["skipped_long"] += 1
                continue

        source_dir = incoming_dir / source
        source_dir.mkdir(parents=True, exist_ok=True)
        temp_name = f"_tmp_{info.clip_id or 'clip'}.mp4"
        fmt = YOUTUBE_FORMAT if info.site == "youtube" else MEDAL_FORMAT

        def _call_downloader(u: str, d: Path, n: str) -> dict:
            # Prefer keyword format_str when the fake/real downloader accepts it.
            try:
                return downloader(u, d, n, format_str=fmt)  # type: ignore[call-arg]
            except TypeError:
                return downloader(u, d, n)

        try:
            meta = _call_downloader(info.url, source_dir, temp_name)
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
                    "source": source,
                    "uploader_id": uploader_id,
                    "uploader": uploader,
                    "content_type": content_type,
                    "content_type_origin": content_type_origin,
                },
            )
            summary.by_status["rate_limited"] += 1
            summary.rate_limited = True
            _write_hints(incoming_dir, log_path)
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
                    "source": source,
                    "uploader_id": uploader_id,
                    "uploader": uploader,
                    "content_type": content_type,
                    "content_type_origin": content_type_origin,
                },
            )
            summary.by_status["failed"] += 1
            continue

        if not auto:
            uid, uname = _uploader_fields(meta, info.site)
            uploader_id = uid
            uploader = uname
            ct, cto = _resolve_content_type(entry, users_for_ct, uploader_id)
            if ct and not entry.content_type:
                content_type, content_type_origin = ct, cto
            elif entry.content_type:
                content_type, content_type_origin = entry.content_type, "video"

        # Override mode: skip long after download using returned info (no metadata pass).
        if max_s is not None and meta_pre is None:
            dur = _duration_s(meta)
            if dur is not None and dur > max_s:
                temp_path = source_dir / temp_name
                if temp_path.exists():
                    temp_path.unlink()
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
                        "status": "skipped_long",
                        "error": f"duration {dur:g}s > max {max_minutes:g} min",
                        "source": source,
                        "uploader_id": uploader_id,
                        "uploader": uploader,
                        "content_type": content_type,
                        "content_type_origin": content_type_origin,
                    },
                )
                summary.by_status["skipped_long"] += 1
                continue

        if not info.clip_id and meta.get("id"):
            info = LinkInfo(url=info.url, site=info.site, clip_id=str(meta["id"]), slug=info.slug)

        upload = _info_timestamp(meta)
        upload_date = _upload_date_str(meta)
        file_name, used, time_source = clip_file_name(
            info, upload, upload_date, now(), game=game, other_name=other_name
        )
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
                    "source": source,
                    "uploader_id": uploader_id,
                    "uploader": uploader,
                    "content_type": content_type,
                    "content_type_origin": content_type_origin,
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
        rel_file = f"{source}/{file_name}"

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
                "file": rel_file,
                "bytes": size,
                "sha256": digest,
                "upload_time": upload_time,
                "time_source": time_source,
                "width": width,
                "height": height,
                "fps": fps,
                "format_id": format_id,
                "error": "",
                "source": source,
                "uploader_id": uploader_id,
                "uploader": uploader,
                "content_type": content_type,
                "content_type_origin": content_type_origin,
            },
        )
        summary.by_status["ok"] += 1
        if game:
            summary.by_game[game] += 1
        else:
            summary.unlabelled += 1
        summary.by_source[source] += 1
        finished.add(_skip_key(info))
        downloads_done += 1

    _write_hints(incoming_dir, log_path)
    return summary


def print_summary(summary: Summary) -> None:
    print("status:", dict(summary.by_status))
    if summary.by_game:
        print("games:", dict(summary.by_game))
    if summary.unlabelled:
        print("unlabelled:", summary.unlabelled)
    if summary.by_source:
        print("sources:", dict(summary.by_source))
    if summary.pending:
        print("pending uploaders:", ", ".join(summary.pending))
