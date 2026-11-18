"""Find, fingerprint and probe candidate clips (Frame Export Kit spec §5.1, §5.2, §5.2a)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from game_frame_classifier.sourcing.budget import Candidate, select_within_budget
from game_frame_classifier.sourcing.ffbin import FFTools
from game_frame_classifier.sourcing.hashing import quick_id
from game_frame_classifier.sourcing.labels import MixedClassification, OTHER, classify_mixed_filename
from game_frame_classifier.sourcing.probe import ProbeError, ProbeInfo, probe_file
from game_frame_classifier.sourcing.recipe import Recipe
from game_frame_classifier.sourcing.timeinfo import RecordingTimes, local_day, recording_times

MAX_PATH = 259
Progress = Callable[[int, int], None]
MIXED_SKIP_DETAILS = frozenset({"unsupported_mixed_filename_format", "mixed_label_conflict"})


@dataclass
class ScanItem:
    path: Path
    relpath: str
    file_bytes: int = 0
    status: str = "eligible"  # eligible, selected or skipped
    detail: str = ""
    quick_id: str = ""
    packed_game: str = ""
    aliases: list[str] = field(default_factory=list)
    info: ProbeInfo | None = None
    times: RecordingTimes | None = None
    mixed_game: str = ""  # assigned category in mixed mode (game label or Other)
    mixed_title: str = ""  # title__timestamp_v1 title when recognised

    def skip(self, detail: str) -> None:
        self.status, self.detail = "skipped", detail


def _is_link(entry: Any) -> bool:
    if entry.is_symlink():
        return True
    is_junction = getattr(entry, "is_junction", None)
    return bool(is_junction and is_junction())


def discover(root: Path, recipe: Recipe, exclude: Path) -> list[ScanItem]:
    """Walk root recursively without following links; classify every file."""
    root = root.resolve()
    exclude = exclude.resolve()
    extensions = set(recipe.video_extensions)
    items: list[ScanItem] = []
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            continue
        if any(e.name.lower() == "session.mpd" for e in entries):
            rel = folder.relative_to(root).as_posix()
            item = ScanItem(folder, rel)
            item.skip("steam_recording")
            items.append(item)
            continue
        for entry in entries:
            path = Path(entry.path)
            if _is_link(entry):
                continue
            if entry.is_dir(follow_symlinks=False):
                if path.resolve() != exclude:
                    stack.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            item = ScanItem(path, path.relative_to(root).as_posix())
            try:
                item.file_bytes = entry.stat(follow_symlinks=False).st_size
            except OSError:
                item.skip("unreadable")
                items.append(item)
                continue
            if len(str(path)) > MAX_PATH:
                item.skip("path_too_long")
            elif path.suffix.lower() not in extensions:
                item.skip("not_video")
            items.append(item)
    items.sort(key=lambda i: i.relpath.lower())
    return items


def fingerprint(
    items: list[ScanItem],
    history: dict[str, dict[str, Any]],
    include_packed: bool,
    on_progress: Progress | None = None,
) -> None:
    """Quick ids; mark duplicates in this run and clips already sent before."""
    todo = [it for it in items if it.status == "eligible"]
    first: dict[str, ScanItem] = {}
    for n, it in enumerate(todo, 1):
        try:
            it.quick_id = quick_id(it.path)
        except OSError:
            it.skip("unreadable")
        else:
            if it.quick_id in first:
                first[it.quick_id].aliases.append(it.relpath)
                it.skip("duplicate_in_run")
            else:
                first[it.quick_id] = it
                entry = history.get(it.quick_id)
                if entry:
                    it.packed_game = str(entry.get("game") or "")
                    if not include_packed:
                        it.skip("already_packed")
        if on_progress:
            on_progress(n, len(todo))


def probe_all(
    items: list[ScanItem],
    tools: FFTools,
    recipe: Recipe,
    root_name: str,
    on_progress: Progress | None = None,
) -> None:
    todo = [it for it in items if it.status == "eligible"]
    for n, it in enumerate(todo, 1):
        try:
            it.info = probe_file(it.path, tools)
            it.times = recording_times(
                it.path, f"{root_name}/{it.relpath}", it.info.container_creation_raw, it.info.duration_s
            )
        except ProbeError as exc:
            it.skip(exc.detail)
        except OSError:
            it.skip("unreadable")
        else:
            if it.info.duration_s < recipe.min_duration_s:
                it.skip("too_short")
        if on_progress:
            on_progress(n, len(todo))


def apply_budget(items: list[ScanItem], budget_s: float) -> None:
    """(Re)select eligible clips within the footage budget; the rest become over_budget."""
    for it in items:
        if it.status == "selected" or (it.status == "skipped" and it.detail == "over_budget"):
            it.status, it.detail = "eligible", ""
    pool = [it for it in items if it.status == "eligible"]
    candidates = [Candidate(it.quick_id, it.info.duration_s, it.times.start) for it in pool]
    selected, _ = select_within_budget(candidates, budget_s, local_day)
    chosen = set(selected)
    for it in pool:
        if it.quick_id in chosen:
            it.status = "selected"
        else:
            it.skip("over_budget")


def classify_mixed_items(items: list[ScanItem], games: tuple[str, ...] | list[str]) -> None:
    """Assign mixed-mode categories; skip unsupported or conflicting filenames.

    Already-packed clips are classified too so they land in the matching pack's table,
    but their skip status is left unchanged.
    """
    for it in items:
        if it.status != "eligible" and it.detail != "already_packed":
            continue
        result: MixedClassification = classify_mixed_filename(it.path.name, games)
        it.mixed_title = result.title
        if result.detail:
            it.mixed_game = ""
            if it.status == "eligible":
                it.skip(result.detail)
        else:
            it.mixed_game = result.game


def apply_budget_by_category(items: list[ScanItem], budget_s: float) -> None:
    """Apply the footage budget independently to each mixed-mode category."""
    for it in items:
        if it.status == "selected" or (it.status == "skipped" and it.detail == "over_budget"):
            it.status, it.detail = "eligible", ""
    categories = sorted({it.mixed_game for it in items if it.status == "eligible" and it.mixed_game})
    for category in categories:
        pool = [it for it in items if it.status == "eligible" and it.mixed_game == category]
        apply_budget(pool, budget_s)


def mixed_category_order(games: tuple[str, ...] | list[str]) -> list[str]:
    """Stable display order: recipe games first, then Other."""
    order = list(games)
    if OTHER not in order:
        order.append(OTHER)
    return order
