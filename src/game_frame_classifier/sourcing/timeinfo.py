"""Recording-time evidence and best estimate for a clip (Frame Export Kit spec §5.2b)."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MIN_YEAR = 2010
_PATTERNS = (
    re.compile(r"(?<!\d)(\d{4})\.(\d{2})\.(\d{2}) - (\d{2})\.(\d{2})\.(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})[ _](\d{2})-(\d{2})-(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"),
)
_CONTAINER = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{2}:\d{2})?$")


@dataclass(frozen=True)
class NameTime:
    value: datetime  # naive local time
    has_time: bool


@dataclass(frozen=True)
class RecordingTimes:
    file_mtime_utc: str
    file_mtime_local: str
    file_created_utc: str
    container_creation_utc: str
    filename_datetime_local: str
    recorded_start_utc: str
    recorded_start_source: str
    start: datetime  # aware UTC, used for budget day grouping


def parse_filename_time(relpath: str, now: datetime | None = None) -> NameTime | None:
    """First valid timestamp in the file name, then parent folders (nearest first)."""
    now = now or datetime.now()
    for text in reversed(relpath.replace("\\", "/").split("/")):
        for pattern in _PATTERNS:
            for match in pattern.finditer(text):
                nums = [int(g) for g in match.groups()]
                try:
                    if len(nums) == 3:
                        value = datetime(nums[0], nums[1], nums[2])
                    else:
                        second = nums[5] if len(nums) > 5 else 0
                        value = datetime(nums[0], nums[1], nums[2], nums[3], nums[4], second)
                except ValueError:
                    continue
                if value.year < MIN_YEAR or value > now + timedelta(days=1):
                    continue
                return NameTime(value, len(nums) > 3)
    return None


def parse_container_time(raw: str, now_utc: datetime | None = None) -> datetime | None:
    """format.tags.creation_time as aware UTC; None when missing or implausible."""
    text = (raw or "").strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1]
    match = _CONTAINER.match(text)
    if not match:
        return None
    try:
        value = datetime.fromisoformat(match.group(1))
    except ValueError:
        return None
    if match.group(3):
        sign = 1 if match.group(3)[0] == "+" else -1
        offset = timedelta(hours=int(match.group(3)[1:3]), minutes=int(match.group(3)[4:6]))
        value = value - sign * offset
    value = value.replace(tzinfo=timezone.utc)
    now_utc = now_utc or datetime.now(timezone.utc)
    if value.year < MIN_YEAR or value > now_utc + timedelta(days=1):
        return None
    return value


def local_to_utc(naive_local: datetime) -> datetime:
    """Convert a naive local time with this PC's timezone and DST rules for that date."""
    return datetime.fromtimestamp(time.mktime(naive_local.timetuple()), timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_local(value: datetime) -> str:
    return value.astimezone().isoformat(timespec="seconds")


def recording_times(
    path: Path,
    name_text: str,
    container_raw: str,
    duration_s: float,
    now: datetime | None = None,
) -> RecordingTimes:
    """All recording-time evidence; best estimate is container > filename > mtime - duration."""
    st = path.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, timezone.utc)
    created_ts = getattr(st, "st_birthtime", None)
    if created_ts is None and os.name == "nt":
        created_ts = st.st_ctime
    created = datetime.fromtimestamp(created_ts, timezone.utc) if created_ts else None
    container = parse_container_time(container_raw)
    name = parse_filename_time(name_text, now)
    name_local = ""
    name_utc = None
    if name is not None:
        if name.has_time:
            name_utc = local_to_utc(name.value)
            name_local = iso_local(name_utc)
        else:
            name_local = name.value.date().isoformat()
    if container is not None:
        start, source = container, "container"
    elif name_utc is not None:
        start, source = name_utc, "filename"
    else:
        start, source = mtime - timedelta(seconds=max(0.0, duration_s)), "mtime"
    return RecordingTimes(
        file_mtime_utc=iso_utc(mtime),
        file_mtime_local=iso_local(mtime),
        file_created_utc=iso_utc(created) if created else "",
        container_creation_utc=iso_utc(container) if container else "",
        filename_datetime_local=name_local,
        recorded_start_utc=iso_utc(start),
        recorded_start_source=source,
        start=start,
    )


def local_day(value_utc: datetime) -> date:
    return value_utc.astimezone().date()


def host_timezone() -> dict[str, object]:
    now = datetime.now().astimezone()
    offset = now.utcoffset() or timedelta(0)
    return {
        "tz_name": time.tzname[1 if time.localtime().tm_isdst > 0 else 0],
        "utc_offset_min": int(round(offset.total_seconds() / 60)),
    }
