"""Append-only decisions.csv and replay to current state."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .scan import Clip

DECISION_COLUMNS = ("utc", "quick_id", "rel_path", "decision", "game", "other_name")
VALID_DECISIONS = frozenset({"label", "disabled", "trash", "skip", "undo"})


def _decisions_path(session_dir: Path) -> Path:
    return Path(session_dir) / "decisions.csv"


def append(
    session_dir: Path,
    quick_id: str,
    rel_path: str,
    decision: str,
    game: str = "",
    other_name: str = "",
) -> None:
    """Append one decision line; create the CSV with a header on first write."""
    if decision not in VALID_DECISIONS:
        raise ValueError(f"invalid decision: {decision}")
    path = _decisions_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file() or path.stat().st_size == 0
    utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DECISION_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                "utc": utc,
                "quick_id": quick_id,
                "rel_path": rel_path,
                "decision": decision,
                "game": game,
                "other_name": other_name,
            }
        )
        f.flush()


def replay(session_dir: Path) -> dict[str, dict[str, Any]]:
    """Latest decision per quick_id; undo removes that clip's latest non-undo decision."""
    path = _decisions_path(session_dir)
    state: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return state
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            qid = row.get("quick_id") or ""
            decision = row.get("decision") or ""
            if not qid:
                continue
            if decision == "undo":
                state.pop(qid, None)
                continue
            if decision not in VALID_DECISIONS:
                continue
            state[qid] = {
                "decision": decision,
                "game": row.get("game") or "",
                "other_name": row.get("other_name") or "",
                "rel_path": row.get("rel_path") or "",
                "utc": row.get("utc") or "",
            }
    return state


def first_undecided(clips: list[Clip], state: dict[str, dict[str, Any]]) -> int:
    """Index of the first clip with no lasting label/disabled/trash (skip = undecided)."""
    lasting = frozenset({"label", "disabled", "trash"})
    for i, clip in enumerate(clips):
        entry = state.get(clip.quick_id)
        if entry is None or entry.get("decision") not in lasting:
            return i
    return 0 if not clips else len(clips) - 1


def last_decision_quick_id(session_dir: Path) -> str | None:
    """quick_id of the most recent non-undo decision still in effect, or None."""
    path = _decisions_path(session_dir)
    if not path.is_file():
        return None
    # Replay chronologically with a stack of applied decisions per clip is overkill;
    # walk rows and track the last non-undo that is not later undone.
    stack: list[str] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            decision = row.get("decision") or ""
            qid = row.get("quick_id") or ""
            if not qid:
                continue
            if decision == "undo":
                # Remove the latest occurrence of this qid from the stack
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i] == qid:
                        del stack[i]
                        break
            elif decision in VALID_DECISIONS:
                stack.append(qid)
    return stack[-1] if stack else None


def other_names(state: dict[str, dict[str, Any]]) -> list[str]:
    """Distinct Other content names used so far, sorted."""
    names = {
        (entry.get("other_name") or "").strip()
        for entry in state.values()
        if entry.get("decision") == "label" and (entry.get("game") or "") == "Other"
    }
    return sorted(n for n in names if n)
