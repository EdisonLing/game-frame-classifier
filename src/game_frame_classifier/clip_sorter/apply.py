"""Apply sorting decisions: copy labelled clips, archive trash."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game_frame_classifier.sourcing.hashing import sha256_file
from game_frame_classifier.sourcing.labels import OTHER, GAMES

from .scan import Clip
from .store import append, replay

LASTING_DECISIONS = frozenset({"label", "disabled", "trash"})


def accept_hints(session_dir: Path, clips: list[Clip]) -> int:
    """Label every undecided clip whose game came from a hints file (the Medal game tag).

    Clips with a problem, an Other suggestion without a content name, or a lasting
    decision already are left alone. Returns the number of clips labelled.
    """
    state = replay(session_dir)
    labelled = 0
    for clip in clips:
        if clip.suggestion_origin != "hints" or not clip.suggestion or clip.problem:
            continue
        if clip.suggestion == OTHER and not clip.other_name:
            continue
        entry = state.get(clip.quick_id)
        if entry is not None and entry.get("decision") in LASTING_DECISIONS:
            continue
        append(
            session_dir,
            clip.quick_id,
            clip.rel_path,
            "label",
            game=clip.suggestion,
            other_name=clip.other_name if clip.suggestion == OTHER else "",
        )
        labelled += 1
    return labelled


@dataclass
class Action:
    rel_path: str
    decision: str
    result: str
    destination: str
    path: Path | None = None
    dest_path: Path | None = None
    game: str = ""
    other_name: str = ""


def _load_index(data_root: Path) -> dict[str, Any]:
    path = data_root / "frame_sources" / "_index" / "by_sha256.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _unique_dest(dest: Path) -> Path:
    """Never overwrite: add _1, _2 before the suffix if needed."""
    if not dest.exists():
        return dest
    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    n = 1
    while True:
        candidate = parent / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _path_below_source(rel_path: str, source: str) -> Path:
    """Path under the source folder; full rel_path when it has no source prefix (override mode)."""
    parts = Path(rel_path.replace("\\", "/")).parts
    if parts and parts[0] == source:
        rest = parts[1:]
        return Path(*rest) if rest else Path(".")
    return Path(rel_path)


def plan(
    session_dir: Path,
    folder: Path,
    clips: list[Clip],
    source: str,
    data_root: Path,
) -> list[Action]:
    """Build the apply plan from the latest decision per clip.

    Prefers ``clip.source`` when set; otherwise ``source``. Destination uses the path
    below the source folder so auto-mode does not double the source segment.
    """
    state = replay(session_dir)
    index = _load_index(data_root)
    actions: list[Action] = []
    for clip in clips:
        entry = state.get(clip.quick_id)
        if entry is None:
            actions.append(Action(clip.rel_path, "undecided", "untouched", ""))
            continue
        decision = entry.get("decision") or ""
        game = entry.get("game") or ""
        other_name = entry.get("other_name") or ""
        if decision in ("disabled", "skip") or decision == "":
            actions.append(
                Action(clip.rel_path, decision or "undecided", "untouched", "", game=game, other_name=other_name)
            )
            continue
        if decision == "trash":
            dest = _unique_dest(folder / "_archive" / Path(clip.rel_path))
            actions.append(
                Action(
                    clip.rel_path,
                    "trash",
                    "move",
                    dest.as_posix(),
                    path=clip.path,
                    dest_path=dest,
                )
            )
            continue
        if decision != "label":
            actions.append(Action(clip.rel_path, decision, "untouched", ""))
            continue
        src = clip.source or source
        if not src or (clip.problem.startswith("no_source") if clip.problem else False):
            actions.append(
                Action(clip.rel_path, "label", "conflict", "", game=game, other_name=other_name)
            )
            continue
        below = _path_below_source(clip.rel_path, src)
        if game == OTHER:
            if not other_name:
                actions.append(
                    Action(clip.rel_path, "label", "conflict", "", game=game, other_name=other_name)
                )
                continue
            dest = data_root / "raw" / "_other" / other_name / src / below
        elif game in GAMES:
            dest = data_root / "raw" / game / src / below
        else:
            actions.append(
                Action(clip.rel_path, "label", "conflict", "", game=game, other_name=other_name)
            )
            continue
        digest = sha256_file(clip.path)
        if digest in index:
            actions.append(
                Action(
                    clip.rel_path,
                    "label",
                    "already_in_pipeline",
                    "",
                    game=game,
                    other_name=other_name,
                )
            )
            continue
        if dest.is_file():
            if sha256_file(dest) == digest:
                actions.append(
                    Action(
                        clip.rel_path,
                        "label",
                        "already_copied",
                        dest.as_posix(),
                        game=game,
                        other_name=other_name,
                    )
                )
            else:
                actions.append(
                    Action(
                        clip.rel_path,
                        "label",
                        "conflict",
                        dest.as_posix(),
                        game=game,
                        other_name=other_name,
                    )
                )
            continue
        actions.append(
            Action(
                clip.rel_path,
                "label",
                "copy",
                dest.as_posix(),
                path=clip.path,
                dest_path=dest,
                game=game,
                other_name=other_name,
            )
        )
    return actions


def run(actions: list[Action], dry_run: bool = False) -> dict[str, Any]:
    """Execute the plan; return a report dict with counts and rows."""
    rows: list[dict[str, str]] = []
    counts: dict[str, int] = {
        "copied": 0,
        "trashed": 0,
        "already_in_pipeline": 0,
        "already_copied": 0,
        "conflict": 0,
        "untouched": 0,
        "disabled": 0,
        "skipped": 0,
        "undecided": 0,
    }
    per_game: dict[str, int] = {}
    per_other: dict[str, int] = {}

    for action in actions:
        rows.append(
            {
                "rel_path": action.rel_path,
                "decision": action.decision,
                "result": action.result,
                "destination": action.destination,
            }
        )
        if action.result == "copy" and action.path and action.dest_path:
            if not dry_run:
                action.dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(action.path, action.dest_path)
            counts["copied"] += 1
            if action.game == OTHER:
                per_other[action.other_name] = per_other.get(action.other_name, 0) + 1
            elif action.game:
                per_game[action.game] = per_game.get(action.game, 0) + 1
        elif action.result == "move" and action.path and action.dest_path:
            if not dry_run:
                action.dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(action.path), str(action.dest_path))
            counts["trashed"] += 1
        elif action.result in counts:
            counts[action.result] += 1
        if action.decision == "disabled":
            counts["disabled"] += 1
        elif action.decision == "skip":
            counts["skipped"] += 1
        elif action.decision == "undecided":
            counts["undecided"] += 1

    return {
        "dry_run": dry_run,
        "counts": counts,
        "per_game": per_game,
        "per_other": per_other,
        "rows": rows,
    }


def write_report(session_dir: Path, report: dict[str, Any]) -> None:
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "apply_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    csv_path = session_dir / "apply_report.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=("rel_path", "decision", "result", "destination"))
        writer.writeheader()
        for row in report.get("rows", []):
            writer.writerow(row)


def print_summary(report: dict[str, Any]) -> None:
    counts = report.get("counts", {})
    print(f"copied={counts.get('copied', 0)} trashed={counts.get('trashed', 0)} "
          f"already_in_pipeline={counts.get('already_in_pipeline', 0)} "
          f"already_copied={counts.get('already_copied', 0)} "
          f"conflict={counts.get('conflict', 0)} "
          f"disabled={counts.get('disabled', 0)} "
          f"skipped={counts.get('skipped', 0)} "
          f"untouched={counts.get('untouched', 0)}")
    per_game = report.get("per_game") or {}
    if per_game:
        print("per game:", ", ".join(f"{k}={v}" for k, v in sorted(per_game.items())))
    per_other = report.get("per_other") or {}
    if per_other:
        print("per Other:", ", ".join(f"{k}={v}" for k, v in sorted(per_other.items())))
