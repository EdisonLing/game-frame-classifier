"""Channel sampling: weighted picks by time budget for gfc-fetch-clips 1.3."""

from __future__ import annotations

import csv
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlparse

from game_frame_classifier.sourcing.labels import normalize_handle

from .channel import (
    _channel_meta,
    _is_live_now,
    _video_url,
    ytdlp_flat_list,
)
from .download import LOG_NAME, Summary, print_summary, run as download_run
from .links import LinkEntry, parse_content_type, parse_game_field
from .users import append_user, load_users, proposed_source

ListerFn = Callable[[str], list[dict]]
NowFn = Callable[[], datetime]
PreviewFn = Callable[[list["SampleCandidate"]], list[str]]

OVERSHOOT_FRAC = 0.2
PREVIEW_BUFFER_FRAC = 2.0
DEFAULT_MAX_TIME_H = 3.0
DEFAULT_RECENCY_BIAS = 2.0
# download.run skips when duration > max_minutes * 60; use a huge cap for no filter.
NO_MAX_MINUTES = 1e12


@dataclass(frozen=True)
class SampleCandidate:
    video_id: str
    url: str
    title: str
    duration_s: float
    rank: int


@dataclass
class Plan:
    preview_pool: list[SampleCandidate] = field(default_factory=list)
    picks: list[SampleCandidate] = field(default_factory=list)
    held_before_s: float = 0.0
    target_s: float = 0.0
    shortfall_s: float = 0.0
    noop: bool = False
    message: str = ""


def recency_weights(n: int, bias: float) -> list[float]:
    """Weights for ranks 0..n-1 (0 = newest). bias 0 → all equal."""
    if n <= 0:
        return []
    if n == 1:
        return [1.0]
    denom = max(n - 1, 1)
    return [math.exp(-bias * i / denom) for i in range(n)]


def weighted_order(weights: Sequence[float], seed: int) -> list[int]:
    """Efraimidis–Spirakis order: descending u**(1/w)."""
    if not weights:
        return []
    rng = random.Random(seed)
    keys: list[tuple[float, int]] = []
    for i, w in enumerate(weights):
        ww = float(w)
        if ww <= 0:
            keys.append((-1.0, i))
            continue
        u = rng.random()
        while u <= 0.0:
            u = rng.random()
        keys.append((u ** (1.0 / ww), i))
    keys.sort(key=lambda t: t[0], reverse=True)
    return [i for _, i in keys]


def is_channel_url(url: str) -> bool:
    """True for YouTube channel URLs; false for watch / playlist / search / youtu.be."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    if host not in ("youtube.com", "youtube-nocookie.com"):
        return False
    path = parsed.path or ""
    parts = [p for p in path.split("/") if p]
    q = parsed.query or ""
    if "watch" in parts or "shorts" in parts or "embed" in parts:
        return False
    if "playlist" in parts or "results" in parts:
        return False
    if "list=" in q or "search_query=" in q or re.search(r"(^|&)v=", q):
        return False
    if not parts:
        return False
    if parts[0].startswith("@"):
        return True
    if parts[0] == "channel" and len(parts) >= 2:
        return True
    if parts[0] in ("c", "user") and len(parts) >= 2:
        return True
    return False


def _duration_of(entry: dict) -> float:
    raw = entry.get("duration")
    if raw is None:
        return 0.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def _ok_ids_for_channel(log_path: Path, uploader_id: str) -> set[str]:
    """Video ids with status=ok for this channel (file may be gone)."""
    if not log_path.is_file():
        return set()
    out: set[str] = set()
    with open(log_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("status") or "") != "ok":
                continue
            if (row.get("uploader_id") or "").strip() != uploader_id:
                continue
            clip_id = (row.get("clip_id") or "").strip()
            if clip_id:
                out.add(clip_id)
    return out


def _find_held_file(data_root: Path, source: str, video_id: str) -> Path | None:
    """Return path of held mp4 for video_id under incoming or raw for this source."""
    if not video_id:
        return None
    suffix = f"__{video_id}.mp4"
    incoming = data_root / "incoming_clips" / source
    if incoming.is_dir():
        for path in incoming.glob("*.mp4"):
            if path.name.endswith(suffix):
                return path
    raw = data_root / "raw"
    if raw.is_dir():
        for path in raw.rglob("*.mp4"):
            if source not in path.parts:
                continue
            if path.name.endswith(suffix):
                return path
    return None


def held_videos(
    data_root: Path,
    source: str,
    channel_id: str,
    *,
    durations: dict[str, float] | None = None,
) -> dict[str, tuple[Path, float]]:
    """Map video id → (path, duration_s) for held clips of this channel."""
    data_root = Path(data_root)
    uploader_id = f"yt:{channel_id}"
    log_path = data_root / "incoming_clips" / LOG_NAME
    ok_ids = _ok_ids_for_channel(log_path, uploader_id)
    durations = durations or {}
    out: dict[str, tuple[Path, float]] = {}
    for vid in ok_ids:
        path = _find_held_file(data_root, source, vid)
        if path is None:
            continue
        out[vid] = (path, float(durations.get(vid, 0.0)))
    return out


def fill_to_budget(
    candidates: Sequence[SampleCandidate],
    *,
    accrued_s: float,
    target_s: float,
    overshoot_frac: float = OVERSHOOT_FRAC,
) -> tuple[list[SampleCandidate], float]:
    """Take candidates in order until target, allowing overshoot_frac; skip too-long.

    Returns (selected, final_accrued). Stops under budget when nothing remaining fits.
    """
    ceiling = target_s * (1.0 + overshoot_frac)
    selected: list[SampleCandidate] = []
    accrued = float(accrued_s)
    for cand in candidates:
        if accrued >= target_s:
            break
        dur = float(cand.duration_s)
        if dur > 0 and accrued + dur > ceiling:
            continue
        selected.append(cand)
        accrued += dur
    return selected, accrued


def preview_buffer(
    ordered: Sequence[SampleCandidate],
    *,
    need_s: float,
    buffer_frac: float = PREVIEW_BUFFER_FRAC,
) -> list[SampleCandidate]:
    """Prefix of ordered picks whose cumulative duration reaches buffer_frac * need_s."""
    if need_s <= 0:
        return []
    goal = need_s * buffer_frac
    pool: list[SampleCandidate] = []
    total = 0.0
    for cand in ordered:
        pool.append(cand)
        total += float(cand.duration_s)
        if total >= goal:
            break
    return pool


def candidates_from_entries(
    entries: Sequence[dict],
    *,
    exclude_ids: set[str] | None = None,
) -> list[SampleCandidate]:
    exclude_ids = exclude_ids or set()
    out: list[SampleCandidate] = []
    for i, entry in enumerate(entries):
        if _is_live_now(entry):
            continue
        url = _video_url(entry)
        vid = str(entry.get("id") or "").strip()
        if not url or not vid or vid in exclude_ids:
            continue
        out.append(
            SampleCandidate(
                video_id=vid,
                url=url,
                title=str(entry.get("title") or vid),
                duration_s=_duration_of(entry),
                rank=i,
            )
        )
    return out


def ordered_candidates(
    entries: Sequence[dict],
    *,
    exclude_ids: set[str],
    bias: float,
    seed: int,
) -> list[SampleCandidate]:
    eligible = candidates_from_entries(entries, exclude_ids=exclude_ids)
    weights = recency_weights(len(eligible), bias)
    order_idx = weighted_order(weights, seed)
    return [eligible[i] for i in order_idx]


def plan_sample(
    entries: Sequence[dict],
    *,
    held: dict[str, tuple[Path, float]],
    mode: str,
    max_time_h: float,
    bias: float,
    seed: int,
    ok_ids: set[str] | None = None,
) -> Plan:
    """Build a sample plan from flat-list entries (newest first)."""
    mode = (mode or "new").strip().lower()
    if mode not in ("new", "total"):
        raise ValueError(f"invalid mode: {mode!r}")
    target_s = float(max_time_h) * 3600.0
    if target_s <= 0:
        raise ValueError("max_time must be > 0")

    held_s = sum(d for _, d in held.values())
    exclude = set(ok_ids) if ok_ids is not None else set(held.keys())

    if mode == "total" and held_s >= target_s:
        return Plan(
            held_before_s=held_s,
            target_s=target_s,
            noop=True,
            message=f"held {held_s / 3600:.2f} h >= target {max_time_h:.2f} h; nothing to do",
        )

    ordered = ordered_candidates(entries, exclude_ids=exclude, bias=bias, seed=seed)

    if mode == "new":
        accrued0 = 0.0
        need_s = target_s
        absolute_target = target_s
    else:
        accrued0 = held_s
        need_s = max(0.0, target_s - held_s)
        absolute_target = target_s

    pool = preview_buffer(ordered, need_s=need_s)
    picks, accrued = fill_to_budget(
        ordered,
        accrued_s=accrued0,
        target_s=absolute_target,
    )
    shortfall = max(0.0, absolute_target - accrued)
    return Plan(
        preview_pool=pool,
        picks=picks,
        held_before_s=held_s,
        target_s=absolute_target,
        shortfall_s=shortfall,
    )


def apply_preview_selection(
    pool: Sequence[SampleCandidate],
    kept_ids: Sequence[str],
    *,
    accrued_s: float,
    target_s: float,
) -> tuple[list[SampleCandidate], list[SampleCandidate], float]:
    """Filter pool to kept ids (preserving order), then fill_to_budget.

    Returns (picks, rejected, final_accrued).
    """
    kept_set = set(kept_ids)
    rejected = [c for c in pool if c.video_id not in kept_set]
    remaining = [c for c in pool if c.video_id in kept_set]
    picks, accrued = fill_to_budget(
        remaining,
        accrued_s=accrued_s,
        target_s=target_s,
    )
    return picks, rejected, accrued


def resolve_source(
    users_path: Path,
    *,
    channel_id: str,
    display: str,
    content_type: str = "",
    note: str = "",
    day: str = "",
    write: bool = True,
) -> str:
    """Return source for the channel; optionally append a new uploader row."""
    uploader_id = f"yt:{channel_id}"
    source = proposed_source(display, prefix="yt")
    users = load_users(users_path)
    known = users.get(uploader_id)
    if known is not None and (known.get("allowed") or "").strip():
        return (known.get("source") or source).strip() or source
    if write:
        append_user(
            users_path,
            {
                "uploader_id": uploader_id,
                "uploader": display,
                "source": source,
                "allowed": "yes",
                "first_seen": day,
                "note": note or "auto",
                "content_type": content_type,
            },
        )
    return source


def _write_picks_file(
    path: Path,
    *,
    display: str,
    channel_id: str,
    day: str,
    mode: str,
    max_time_h: float,
    seed: int,
    bias: float,
    held_before_s: float,
    picks: Sequence[SampleCandidate],
    rejected: Sequence[SampleCandidate],
    downloaded_s: float,
    shortfall_s: float,
    game_field: str,
    content_type: str,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# channel: {display}",
        f"# channel_id: {channel_id}",
        f"# date: {day}",
        f"# mode: {mode}",
        f"# max_time_h: {max_time_h}",
        f"# seed: {seed}",
        f"# recency_bias: {bias}",
        f"# held_s_before: {held_before_s:.1f}",
        f"# picks: {len(picks)}",
        f"# downloaded_s: {downloaded_s:.1f}",
        f"# shortfall_s: {shortfall_s:.1f}",
    ]
    for c in rejected:
        safe_title = re.sub(r"[\r\n]+", " ", c.title)
        lines.append(f"# skipped_preview: {c.video_id} {safe_title}")
    for c in picks:
        lines.append(f"{c.url},{game_field},{content_type}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_sample_summary(
    *,
    mode: str,
    picks: int,
    downloaded_s: float,
    replaced: int,
    shortfall_s: float,
    seed: int,
) -> None:
    print(
        f"sample: mode={mode} picks={picks} downloaded_s={downloaded_s:.0f} "
        f"replaced={replaced} removed=0 shortfall_s={shortfall_s:.0f} seed={seed}"
    )


def _link_entries(
    picks: Sequence[SampleCandidate],
    *,
    game: str,
    other_name: str,
    content_type: str,
) -> list[LinkEntry]:
    return [
        LinkEntry(url=c.url, game=game, other_name=other_name, content_type=content_type)
        for c in picks
    ]


def _new_downloaded_s(
    held_before: dict[str, tuple[Path, float]],
    held_after: dict[str, tuple[Path, float]],
) -> float:
    new_ids = set(held_after) - set(held_before)
    return sum(held_after[i][1] for i in new_ids)


def run_sample(
    channel_url: str,
    *,
    max_time_h: float = DEFAULT_MAX_TIME_H,
    mode: str = "new",
    recency_bias: float = DEFAULT_RECENCY_BIAS,
    seed: int | None = None,
    dry_run: bool = False,
    preview: bool = True,
    game: str = "",
    content_type: str = "",
    note: str = "",
    out: Path | None = None,
    data_root: Path = Path("data"),
    users_path: Path | None = None,
    lister: ListerFn = ytdlp_flat_list,
    preview_fn: PreviewFn | None = None,
    downloader=None,
    metadata=None,
    pause_s: float = 3.0,
    now: NowFn | None = None,
) -> tuple[int, Summary | None]:
    """Run channel sampling. Returns (exit_code, download summary or None)."""
    if not is_channel_url(channel_url):
        print("error: --channel needs a YouTube channel URL", flush=True)
        return 2, None
    if max_time_h <= 0:
        print("error: --max-time must be > 0", flush=True)
        return 2, None
    if recency_bias < 0:
        print("error: --recency-bias must be >= 0", flush=True)
        return 2, None
    mode_norm = (mode or "new").strip().lower()
    if mode_norm not in ("new", "total"):
        print("error: --mode must be new or total", flush=True)
        return 2, None

    game_val, other_name = parse_game_field(game) if game else ("", "")
    if game_val == "Other" and other_name:
        game_field = f"Other:{other_name}"
    else:
        game_field = game_val
    ct = parse_content_type(content_type) if content_type else ""

    data_root = Path(data_root)
    users_path = Path(users_path) if users_path else data_root / "clip_links" / "medal_users.csv"
    stamp = (now or (lambda: datetime.now(timezone.utc)))()
    if stamp.tzinfo is None:
        day = stamp.strftime("%Y-%m-%d")
    else:
        day = stamp.astimezone(timezone.utc).strftime("%Y-%m-%d")

    used_seed = int(seed) if seed is not None else random.SystemRandom().randint(0, 2**31 - 1)

    try:
        entries = lister(channel_url)
    except Exception as exc:  # noqa: BLE001 - surface as exit 1
        print(f"error: channel listing failed: {exc}", flush=True)
        return 1, None

    videos = [
        e
        for e in entries
        if isinstance(e, dict) and not _is_live_now(e) and _video_url(e)
    ]
    channel_id, channel_name, handle = _channel_meta(entries or videos, channel_url)
    if not channel_id:
        print("error: could not determine channel id from listing", flush=True)
        return 1, None
    display = channel_name or handle or channel_id
    handle_norm = normalize_handle(handle or display)
    source = resolve_source(
        users_path,
        channel_id=channel_id,
        display=display,
        content_type=ct,
        note=note,
        day=day,
        write=not dry_run,
    )
    uploader_id = f"yt:{channel_id}"
    durations = {str(e.get("id") or ""): _duration_of(e) for e in videos if e.get("id")}
    held = held_videos(data_root, source, channel_id, durations=durations)
    ok_ids = _ok_ids_for_channel(data_root / "incoming_clips" / LOG_NAME, uploader_id)

    plan = plan_sample(
        videos,
        held=held,
        mode=mode_norm,
        max_time_h=max_time_h,
        bias=recency_bias,
        seed=used_seed,
        ok_ids=ok_ids,
    )

    print(
        f"sample seed={used_seed} mode={mode_norm} max_time_h={max_time_h} source={source}",
        flush=True,
    )
    if plan.noop:
        print(plan.message, flush=True)
        print_sample_summary(
            mode=mode_norm,
            picks=0,
            downloaded_s=0.0,
            replaced=0,
            shortfall_s=0.0,
            seed=used_seed,
        )
        return 0, Summary()

    ordered = ordered_candidates(
        videos, exclude_ids=ok_ids, bias=recency_bias, seed=used_seed
    )
    accrued0 = 0.0 if mode_norm == "new" else plan.held_before_s
    pool = plan.preview_pool
    rejected: list[SampleCandidate] = []

    if dry_run:
        picks = plan.picks
        print(f"dry-run sample pool={len(pool)} provisional_picks={len(picks)}", flush=True)
        for c in picks:
            print(
                f"dry-run pick  {c.url}  title={c.title!r}  duration_s={c.duration_s:.0f}",
                flush=True,
            )
        print_sample_summary(
            mode=mode_norm,
            picks=len(picks),
            downloaded_s=sum(c.duration_s for c in picks),
            replaced=0,
            shortfall_s=plan.shortfall_s,
            seed=used_seed,
        )
        return 0, Summary()

    if preview:
        from . import preview as preview_mod

        fn = preview_fn or preview_mod.run_preview
        kept_ids = fn(list(pool))
        picks, rejected, accrued = apply_preview_selection(
            pool,
            kept_ids,
            accrued_s=accrued0,
            target_s=plan.target_s,
        )
        # Replacements stay inside what the user left on — never pull unpreviewed ids.
        kept_set = set(kept_ids)
        pick_ids = {c.video_id for c in picks}
        reserve = [
            c for c in pool if c.video_id in kept_set and c.video_id not in pick_ids
        ]
    else:
        picks, accrued = fill_to_budget(
            ordered,
            accrued_s=accrued0,
            target_s=plan.target_s,
        )
        pick_ids = {c.video_id for c in picks}
        reserve = [c for c in ordered if c.video_id not in pick_ids]

    download_kwargs: dict = {
        "source_override": source,
        "users_path": users_path,
        "pause_s": pause_s,
        "dry_run": False,
        "max_minutes": NO_MAX_MINUTES,
    }
    if downloader is not None:
        download_kwargs["downloader"] = downloader
    if metadata is not None:
        download_kwargs["metadata"] = metadata

    incoming = data_root / "incoming_clips"
    summary = download_run(
        _link_entries(picks, game=game_val, other_name=other_name, content_type=ct),
        incoming,
        **download_kwargs,
    )

    replaced = 0
    held_after = held_videos(data_root, source, channel_id, durations=durations)
    if mode_norm == "new":
        got_s = _new_downloaded_s(held, held_after)
    else:
        got_s = sum(d for _, d in held_after.values())

    while got_s < plan.target_s and reserve and not summary.rate_limited:
        # Prefer next that fits; fill_to_budget on a one-item list skips if too long.
        trial = reserve[0]
        reserve = reserve[1:]
        trial_picks, _ = fill_to_budget(
            [trial],
            accrued_s=got_s,
            target_s=plan.target_s,
        )
        if not trial_picks:
            continue
        extra_summary = download_run(
            _link_entries(trial_picks, game=game_val, other_name=other_name, content_type=ct),
            incoming,
            **download_kwargs,
        )
        for k, v in extra_summary.by_status.items():
            summary.by_status[k] += v
        summary.rate_limited = summary.rate_limited or extra_summary.rate_limited
        if extra_summary.by_status.get("ok", 0) > 0:
            replaced += 1
            picks.extend(trial_picks)
            held_after = held_videos(data_root, source, channel_id, durations=durations)
            if mode_norm == "new":
                got_s = _new_downloaded_s(held, held_after)
            else:
                got_s = sum(d for _, d in held_after.values())
        # failed trial: continue to next reserve item

    held_final = held_videos(data_root, source, channel_id, durations=durations)
    if mode_norm == "new":
        downloaded_s = _new_downloaded_s(held, held_final)
    else:
        downloaded_s = sum(d for _, d in held_final.values())
    shortfall_s = max(0.0, plan.target_s - downloaded_s)

    # The picks file lists what was downloaded; a pick that failed is not a pick.
    picks = [c for c in picks if c.video_id in held_final]

    picks_path = out
    if picks_path is None:
        picks_path = data_root / "clip_links" / f"{day}_yt_{handle_norm}_sample.txt"
    _write_picks_file(
        picks_path,
        display=display,
        channel_id=channel_id,
        day=day,
        mode=mode_norm,
        max_time_h=max_time_h,
        seed=used_seed,
        bias=recency_bias,
        held_before_s=plan.held_before_s,
        picks=picks,
        rejected=rejected,
        downloaded_s=downloaded_s,
        shortfall_s=shortfall_s,
        game_field=game_field,
        content_type=ct,
    )
    print(f"wrote picks {picks_path}", flush=True)
    print_summary(summary)
    print_sample_summary(
        mode=mode_norm,
        picks=len(picks),
        downloaded_s=downloaded_s,
        replaced=replaced,
        shortfall_s=shortfall_s,
        seed=used_seed,
    )
    return summary.exit_code, summary
