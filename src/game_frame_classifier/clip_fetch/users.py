"""Medal uploader → source mapping (medal_users.csv)."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from game_frame_classifier.sourcing.labels import normalize_handle

USER_COLUMNS = ("uploader_id", "uploader", "source", "allowed", "first_seen", "note")

AskFn = Callable[[str], str]


def proposed_source(uploader: str) -> str:
    handle = normalize_handle(uploader)
    return f"friend_{handle}" if handle else "friend_"


def validate_source(text: str) -> str:
    """Normalise a typed source; return \"\" when refused."""
    raw = text.strip()
    # Refuse before normalisation so leading "_" / contributor_ are not stripped away.
    if not raw or raw.startswith("_") or raw.lower().startswith("contributor_"):
        return ""
    source = normalize_handle(text)
    if not source or source.startswith("contributor_") or source.startswith("_"):
        return ""
    return source


def load_users(path: Path | str) -> dict[str, dict[str, str]]:
    """Load medal_users.csv keyed by uploader_id; a later row for the same uploader wins."""
    path = Path(path)
    if not path.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = (row.get("uploader_id") or "").strip()
            if not uid:
                continue
            out[uid] = {k: (row.get(k) or "").strip() for k in USER_COLUMNS}
    return out


def append_user(path: Path | str, row: dict[str, str]) -> None:
    """Append one new uploader row; never rewrite existing rows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file()
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=USER_COLUMNS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in USER_COLUMNS})


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def decide(
    new_uploaders: list[tuple[str, str, int]],
    ask: AskFn | None,
) -> dict[str, dict[str, str]]:
    """Ask about each new uploader (or mark pending). Returns rows keyed by uploader_id."""
    decided: dict[str, dict[str, str]] = {}
    first_seen = _today_utc()
    for uid, name, count in new_uploaders:
        proposed = proposed_source(name)
        if ask is None:
            decided[uid] = {
                "uploader_id": uid,
                "uploader": name,
                "source": proposed,
                "allowed": "",
                "first_seen": first_seen,
                "note": "",
            }
            continue
        while True:
            prompt = (
                f'Uploader "{name}" ({count} clips). '
                f"Use as source {proposed}? [y = yes / n = no / or type a source name]"
            )
            answer = (ask(prompt) or "").strip()
            lower = answer.lower()
            if lower == "y":
                source = proposed
                allowed = "yes"
            elif lower == "n":
                source = proposed
                allowed = "no"
            else:
                source = validate_source(answer)
                if not source:
                    continue
                allowed = "yes"
            decided[uid] = {
                "uploader_id": uid,
                "uploader": name,
                "source": source,
                "allowed": allowed,
                "first_seen": first_seen,
                "note": "",
            }
            break
    return decided
