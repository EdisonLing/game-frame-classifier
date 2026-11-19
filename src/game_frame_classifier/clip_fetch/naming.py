"""Clip file names from link info and upload time."""

from __future__ import annotations

from datetime import datetime

from .links import LinkInfo, name_prefix


def clip_file_name(
    info: LinkInfo,
    upload: datetime | None,
    upload_date: str | None,
    now: datetime,
    *,
    game: str = "",
    other_name: str = "",
) -> tuple[str, datetime, str]:
    """Return (file_name, time_used, time_source).

    time_source is timestamp | upload_date | download. Name uses local time.
    Prefix is the Medal slug when present, else the game / other name / unlabelled.
    """
    if upload is not None:
        used = upload.astimezone().replace(tzinfo=None) if upload.tzinfo else upload
        source = "timestamp"
    elif upload_date:
        try:
            used = datetime.strptime(upload_date[:8], "%Y%m%d")
            source = "upload_date"
        except ValueError:
            used = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
            source = "download"
    else:
        used = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
        source = "download"

    prefix = name_prefix(game, other_name, info.slug)
    clip_id = info.clip_id or "clip"
    name = (
        f"{prefix}__{used.strftime('%Y-%m-%d')}__{used.strftime('%H-%M-%S')}__{clip_id}.mp4"
    )
    return name, used, source
