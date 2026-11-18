"""Scan a folder of videos and attach suggested labels."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from game_frame_classifier.sourcing.ffbin import FFTools
from game_frame_classifier.sourcing.hashing import quick_id
from game_frame_classifier.sourcing.labels import (
    OTHER,
    classify_mixed_filename,
    label_hints,
)
from game_frame_classifier.sourcing.probe import ProbeError, probe_file
from game_frame_classifier.sourcing.recipe import Recipe


@dataclass
class Clip:
    rel_path: str
    path: Path
    size: int
    quick_id: str
    duration_s: float | None
    width: int
    height: int
    problem: str
    suggestion: str
    other_name: str
    suggestion_origin: str


def read_hints(path: Path) -> dict[str, tuple[str, str]]:
    """Load hints.csv: file,game,other_name → dict keyed by relative path."""
    out: dict[str, tuple[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rel = (row.get("file") or "").replace("\\", "/").strip()
            if not rel:
                continue
            game = (row.get("game") or "").strip()
            other = (row.get("other_name") or "").strip()
            out[rel] = (game, other)
    return out


def suggest(
    rel_path: str,
    hints: dict[str, tuple[str, str]],
) -> tuple[str, str, str]:
    """Return (game_or_Other, other_name, origin). Empty game means no suggestion."""
    key = rel_path.replace("\\", "/")
    if key in hints:
        game, other = hints[key]
        if game:
            return game, other if game == OTHER else "", "hints"
    name = Path(rel_path).name
    mixed = classify_mixed_filename(name)
    if mixed.game:
        if mixed.game == OTHER:
            return OTHER, "mixed_other", "medal_filename"
        return mixed.game, "", "medal_filename"
    found = label_hints(rel_path)
    if len(found) == 1:
        return next(iter(found)), "", "path_hint"
    return "", "", ""


def scan(
    folder: Path,
    recipe: Recipe,
    tools: FFTools,
    hints: dict[str, tuple[str, str]],
) -> list[Clip]:
    """Walk folder for videos; skip _archive/; return clips sorted by rel_path."""
    folder = folder.resolve()
    exts = {e.lower() for e in recipe.video_extensions}
    clips: list[Clip] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(folder).as_posix()
        except ValueError:
            continue
        parts = Path(rel).parts
        if "_archive" in parts:
            continue
        if path.suffix.lower() not in exts:
            continue
        size = path.stat().st_size
        qid = quick_id(path)
        duration_s: float | None = None
        width = 0
        height = 0
        problem = ""
        try:
            info = probe_file(path, tools)
            duration_s = info.duration_s
            width = info.width
            height = info.height
            if info.duration_s < recipe.min_duration_s:
                problem = f"too_short:{info.duration_s:g}s"
        except ProbeError as exc:
            problem = exc.detail or "unreadable"
        except Exception as exc:  # noqa: BLE001 — surface any probe failure as a problem
            problem = f"unreadable:{exc}"
        game, other_name, origin = suggest(rel, hints)
        clips.append(
            Clip(
                rel_path=rel,
                path=path,
                size=size,
                quick_id=qid,
                duration_s=duration_s,
                width=width,
                height=height,
                problem=problem,
                suggestion=game,
                other_name=other_name,
                suggestion_origin=origin,
            )
        )
    clips.sort(key=lambda c: c.rel_path)
    return clips
