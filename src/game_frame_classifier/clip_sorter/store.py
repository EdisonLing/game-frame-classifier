"""Append-only decisions.csv and replay to current state."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .scan import Clip

DECISION_COLUMNS = (
    "utc",
    "quick_id",
    "rel_path",
    "decision",
    "game",
    "other_name",
    "content_type",
)
VALID_DECISIONS = frozenset({"label", "disabled", "trash", "skip", "undo", "content"})
LASTING_DECISIONS = frozenset({"label", "disabled", "trash"})
LABEL_DECISIONS = frozenset({"label", "disabled", "trash", "skip"})


def _decisions_path(session_dir: Path) -> Path:
    return Path(session_dir) / "decisions.csv"


def append(
    session_dir: Path,
    quick_id: str,
    rel_path: str,
    decision: str,
    game: str = "",
    other_name: str = "",
    content_type: str = "",
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
                "content_type": content_type,
            }
        )
        f.flush()


def _collapse(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Collapse a clip's history into label state + content type."""
    if not entries:
        return None
    decision = ""
    game = ""
    other_name = ""
    rel_path = ""
    utc = ""
    content_type = ""
    content_type_origin = ""
    has_label = False
    for entry in entries:
        kind = entry.get("decision") or ""
        if kind == "content":
            content_type = entry.get("content_type") or ""
            content_type_origin = "sorter"
            continue
        if kind in LABEL_DECISIONS:
            has_label = True
            decision = kind
            game = entry.get("game") or ""
            other_name = entry.get("other_name") or ""
            rel_path = entry.get("rel_path") or ""
            utc = entry.get("utc") or ""
            # accept-hints may carry content type on the label row
            row_ct = entry.get("content_type") or ""
            if row_ct and not content_type:
                content_type = row_ct
                content_type_origin = entry.get("content_type_origin") or "video"
    if not has_label and not content_type and content_type_origin != "sorter":
        # content cleared (empty) still counts as sorter state when last content row cleared it
        if not any(e.get("decision") == "content" for e in entries):
            return None
    out: dict[str, Any] = {
        "decision": decision,
        "game": game,
        "other_name": other_name,
        "rel_path": rel_path,
        "utc": utc,
        "content_type": content_type,
        "content_type_origin": content_type_origin,
    }
    return out


def replay(session_dir: Path) -> dict[str, dict[str, Any]]:
    """Latest state per quick_id; undo removes that clip's newest row of either kind."""
    path = _decisions_path(session_dir)
    history: dict[str, list[dict[str, Any]]] = {}
    if not path.is_file():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            qid = row.get("quick_id") or ""
            decision = row.get("decision") or ""
            if not qid:
                continue
            if decision == "undo":
                if history.get(qid):
                    history[qid].pop()
                continue
            if decision not in VALID_DECISIONS:
                continue
            history.setdefault(qid, []).append(
                {
                    "decision": decision,
                    "game": row.get("game") or "",
                    "other_name": row.get("other_name") or "",
                    "rel_path": row.get("rel_path") or "",
                    "utc": row.get("utc") or "",
                    "content_type": row.get("content_type") or "",
                    "content_type_origin": row.get("content_type_origin") or "",
                }
            )
    out: dict[str, dict[str, Any]] = {}
    for qid, entries in history.items():
        collapsed = _collapse(entries)
        if collapsed is not None:
            out[qid] = collapsed
    return out


def first_undecided(clips: list[Clip], state: dict[str, dict[str, Any]]) -> int:
    """Index of the first clip with no lasting label/disabled/trash (skip = undecided)."""
    for i, clip in enumerate(clips):
        entry = state.get(clip.quick_id)
        if entry is None or entry.get("decision") not in LASTING_DECISIONS:
            return i
    return 0 if not clips else len(clips) - 1


def last_decision_quick_id(session_dir: Path) -> str | None:
    """quick_id of the most recent non-undo decision still in effect, or None."""
    path = _decisions_path(session_dir)
    if not path.is_file():
        return None
    stack: list[str] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            decision = row.get("decision") or ""
            qid = row.get("quick_id") or ""
            if not qid:
                continue
            if decision == "undo":
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


def filter_unlabelled(clips: list[Clip], state: dict[str, dict[str, Any]]) -> list[Clip]:
    """Clips with no game suggestion and no lasting label/disabled/trash decision."""
    out: list[Clip] = []
    for clip in clips:
        if clip.suggestion:
            continue
        entry = state.get(clip.quick_id)
        if entry is not None and entry.get("decision") in LASTING_DECISIONS:
            continue
        out.append(clip)
    return out
