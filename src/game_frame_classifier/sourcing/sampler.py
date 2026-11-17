"""bucket_v1 sampler: first frame in each interval bucket (Frame Export Kit spec §5.4, §5.6)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_SHOWINFO = re.compile(r"\[Parsed_showinfo_\d+ @ [^\]]+\] n:\s*\d+ .*?pts_time:\s*(\S+)")


def offset_s(nominal_fps: float) -> float:
    """Half a frame, clamped to 2-50 ms, rounded to the 6 decimals ffmpeg sees."""
    return round(min(0.05, max(0.002, 0.5 / nominal_fps)), 6)


def _fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def select_expr(interval_s: float, off: float) -> str:
    i, o = _fmt(interval_s), _fmt(off)
    return (
        f"gte(t\\,0)*(isnan(prev_selected_t)"
        f"+gt(floor((t+{o})/{i})\\,floor((prev_selected_t+{o})/{i})))"
    )


def bucket_of(pts_time_s: float, interval_s: float, off: float) -> int:
    return math.floor((pts_time_s + off) / interval_s)


def expected_slots(duration_s: float, interval_s: float, nominal_fps: float) -> int:
    """Buckets a clip of this duration should fill (QA only)."""
    if duration_s <= 0:
        return 0
    last = max(0.0, duration_s - 1.0 / nominal_fps)
    return bucket_of(last, interval_s, offset_s(nominal_fps)) + 1


def parse_showinfo(stderr_text: str) -> list[float]:
    """pts_time of each frame showinfo printed, in output order."""
    times: list[float] = []
    for match in _SHOWINFO.finditer(stderr_text):
        try:
            times.append(float(match.group(1)))
        except ValueError as exc:
            raise ValueError(f"frame without a timestamp: {match.group(1)}") from exc
    return times


@dataclass(frozen=True)
class Slot:
    bucket: int
    indices: dict[str, int]
    pts: dict[str, float]


@dataclass(frozen=True)
class Pairing:
    slots: list[Slot]
    unpaired_dropped: int
    max_align_err_s: float
    mode: str  # "index" or "bucket"


def _first_by_bucket(times: list[float], interval_s: float, off: float) -> dict[int, int]:
    out: dict[int, int] = {}
    for index, t in enumerate(times):
        out.setdefault(bucket_of(t, interval_s, off), index)
    return out


def pair_tiers(times: dict[str, list[float]], interval_s: float, off: float, tolerance_s: float) -> Pairing:
    """Pair tier frames into slots: by order when they agree, else by bucket."""
    tiers = list(times)
    lists = [times[t] for t in tiers]
    count = len(lists[0])
    by_order = all(len(values) == count for values in lists) and all(
        max(values[k] for values in lists) - min(values[k] for values in lists) <= tolerance_s
        for k in range(count)
    )
    if by_order:
        mode = "index"
        rows = [{t: k for t in tiers} for k in range(count)]
    else:
        mode = "bucket"
        maps = {t: _first_by_bucket(times[t], interval_s, off) for t in tiers}
        common = sorted(set.intersection(*(set(m) for m in maps.values())))
        rows = [{t: maps[t][b] for t in tiers} for b in common]
    slots: list[Slot] = []
    seen: set[int] = set()
    for row in rows:
        ref = tiers[0]
        bucket = bucket_of(times[ref][row[ref]], interval_s, off)
        if bucket in seen:
            continue
        seen.add(bucket)
        slots.append(Slot(bucket, row, {t: times[t][row[t]] for t in tiers}))
    err = max((max(s.pts.values()) - min(s.pts.values()) for s in slots), default=0.0)
    return Pairing(
        slots=slots,
        unpaired_dropped=max(len(values) for values in lists) - len(slots),
        max_align_err_s=round(err, 6),
        mode=mode,
    )
