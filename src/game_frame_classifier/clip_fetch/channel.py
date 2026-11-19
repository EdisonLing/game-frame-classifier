"""List a YouTube channel's videos into a links file (no download)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from game_frame_classifier.sourcing.labels import normalize_handle

from .links import CONTENT_TYPES, parse_content_type, parse_game_field
from .users import append_user, load_users, proposed_source

ListerFn = Callable[[str], list[dict]]
NowFn = Callable[[], datetime]


def ytdlp_flat_list(url: str) -> list[dict]:
    """Flat-list videos for a channel or playlist URL (no download)."""
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - CLI guards this
        raise RuntimeError("yt-dlp is not installed") from exc

    cleaned = url.rstrip("/")
    parsed = urlparse(cleaned)
    parts = [p for p in parsed.path.split("/") if p]
    list_url = cleaned
    # Channel root (@handle or /channel/<id>) → its /videos tab (do not double /videos).
    if parts and (parts[0].startswith("@") or parts[0] == "channel"):
        if "videos" not in parts:
            list_url = cleaned + "/videos"

    opts = {"extract_flat": "in_playlist", "quiet": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(list_url, download=False) or {}
    # Flat entries often omit channel fields; the playlist/channel object has them.
    channel_id = str(
        info.get("channel_id") or info.get("uploader_id") or info.get("id") or ""
    )
    channel_name = str(info.get("channel") or info.get("uploader") or "")
    out: list[dict] = []
    for entry in info.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        if channel_id and not (row.get("channel_id") or row.get("uploader_id")):
            row["channel_id"] = channel_id
        if channel_name and not (row.get("channel") or row.get("uploader")):
            row["channel"] = channel_name
        out.append(row)
    return out


def _channel_meta(entries: list[dict], url: str) -> tuple[str, str, str]:
    """Return (channel_id, channel_name, handle_for_file)."""
    channel_id = ""
    channel_name = ""
    for entry in entries:
        channel_id = str(entry.get("channel_id") or entry.get("uploader_id") or channel_id or "")
        channel_name = str(entry.get("channel") or entry.get("uploader") or channel_name or "")
        if channel_id and channel_name:
            break
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    handle = ""
    if parts and parts[0].startswith("@"):
        handle = parts[0][1:]
    elif channel_name:
        handle = channel_name
    elif channel_id:
        handle = channel_id
    return channel_id, channel_name, handle


def _video_url(entry: dict) -> str:
    vid = str(entry.get("id") or "").strip()
    if not vid:
        return ""
    return f"https://www.youtube.com/watch?v={vid}"


def _is_live_now(entry: dict) -> bool:
    if entry.get("live_status") == "is_live":
        return True
    if entry.get("is_live") is True:
        return True
    return False


def list_channel(
    url: str,
    *,
    game: str = "",
    content_type: str = "",
    note: str = "",
    out: Path | None = None,
    users_path: Path,
    data_root: Path | None = None,
    lister: ListerFn = ytdlp_flat_list,
    now: NowFn | None = None,
) -> Path:
    """Write a links file for the channel and ensure an uploader row exists.

    Returns the path written. With ``content_type``, also tags the channel.
    """
    game_val, other_name = parse_game_field(game) if game else ("", "")
    if game_val == "Other" and other_name:
        game_field = f"Other:{other_name}"
    else:
        game_field = game_val
    ct = parse_content_type(content_type) if content_type else ""
    if content_type and not ct:
        raise ValueError("content type is required when --content-type is given")
    if ct and ct not in CONTENT_TYPES:
        raise ValueError(f"invalid content type: {content_type!r}")

    entries = lister(url)
    # Newest first: flat list is usually newest-first already; keep order, drop live.
    videos: list[dict] = []
    for entry in entries:
        if _is_live_now(entry):
            continue
        if not _video_url(entry):
            continue
        videos.append(entry)

    channel_id, channel_name, handle = _channel_meta(entries or videos, url)
    if not channel_id:
        raise ValueError("could not determine channel id from listing")
    display = channel_name or handle or channel_id
    handle_norm = normalize_handle(handle or display)
    uploader_id = f"yt:{channel_id}"
    source = proposed_source(display, prefix="yt")

    stamp = (now or (lambda: datetime.now(timezone.utc)))()
    if stamp.tzinfo is None:
        day = stamp.strftime("%Y-%m-%d")
    else:
        day = stamp.astimezone(timezone.utc).strftime("%Y-%m-%d")

    if out is None:
        root = Path(data_root) if data_root is not None else Path("data")
        out = root / "clip_links" / f"{day}_yt_{handle_norm}.txt"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    header = [
        f"# channel: {display}",
        f"# channel_id: {channel_id}",
        f"# date: {day}",
        f"# note: {note}",
        f"# count: {len(videos)}",
    ]
    lines = list(header)
    for entry in videos:
        vurl = _video_url(entry)
        lines.append(f"{vurl},{game_field},{ct}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    users = load_users(users_path)
    known = users.get(uploader_id)
    need_new = known is None or not (known.get("allowed") or "").strip()
    if need_new:
        append_user(
            users_path,
            {
                "uploader_id": uploader_id,
                "uploader": display,
                "source": source,
                "allowed": "yes",
                "first_seen": day,
                "note": note or "auto",
                "content_type": ct,
            },
        )
    elif ct:
        # Tag the channel: append a row with the same identity and the new tag.
        append_user(
            users_path,
            {
                "uploader_id": uploader_id,
                "uploader": known.get("uploader") or display,
                "source": known.get("source") or source,
                "allowed": known.get("allowed") or "yes",
                "first_seen": day,
                "note": note or known.get("note") or "",
                "content_type": ct,
            },
        )
    return out
