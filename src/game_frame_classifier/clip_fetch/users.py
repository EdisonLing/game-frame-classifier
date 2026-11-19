"""Uploader → source mapping (medal_users.csv; Medal and YouTube)."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from game_frame_classifier.sourcing.labels import normalize_handle

from .links import CONTENT_TYPES, parse_content_type

USER_COLUMNS = (
    "uploader_id",
    "uploader",
    "source",
    "allowed",
    "first_seen",
    "note",
    "content_type",
)

AskFn = Callable[[str], str]


def proposed_source(uploader: str, prefix: str = "friend") -> str:
    handle = normalize_handle(uploader)
    base = prefix if prefix else "friend"
    return f"{base}_{handle}" if handle else f"{base}_"


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
    """Load medal_users.csv keyed by uploader_id; a later row for the same uploader wins.

    Old files without a content_type column read that field as empty.
    """
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


def _ensure_content_type_column(path: Path) -> None:
    """Add an empty content_type column to older uploader files (one-time rewrite)."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and "content_type" in reader.fieldnames:
            return
        rows = list(reader)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=USER_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (row.get(k) or "").strip() for k in USER_COLUMNS})


def append_user(path: Path | str, row: dict[str, str]) -> None:
    """Append one new uploader row; never rewrite existing identity rows.

    Older files missing ``content_type`` are migrated once (empty values) so the
    header matches before the new row is appended.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file()
    if not new_file:
        _ensure_content_type_column(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=USER_COLUMNS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in USER_COLUMNS})


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def decide(
    new_uploaders: list[tuple[str, str, int]] | list[tuple[str, str, int, str]],
    ask: AskFn | None,
) -> dict[str, dict[str, str]]:
    """Decide each new uploader: accept with proposed source when ask is None, else ask.

    Each item is (uploader_id, name, count) or (uploader_id, name, count, prefix).
    Prefix defaults to ``friend`` (Medal); YouTube uses ``yt``.
    Returns rows keyed by uploader_id.
    """
    decided: dict[str, dict[str, str]] = {}
    first_seen = _today_utc()
    for item in new_uploaders:
        if len(item) == 4:
            uid, name, count, prefix = item  # type: ignore[misc]
        else:
            uid, name, count = item  # type: ignore[misc]
            prefix = "friend"
        proposed = proposed_source(name, prefix=prefix)
        if ask is None:
            decided[uid] = {
                "uploader_id": uid,
                "uploader": name,
                "source": proposed,
                "allowed": "yes",
                "first_seen": first_seen,
                "note": "auto",
                "content_type": "",
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
                "content_type": "",
            }
            break
    return decided


def tag_uploader(users_path: Path | str, key: str, content_type: str) -> dict[str, str]:
    """Append a row that sets content_type for an uploader matched by id or source.

    Raises KeyError when neither matches; ValueError for an invalid content type.
    """
    value = parse_content_type(content_type)
    if not value:
        raise ValueError("content type is required")
    if value not in CONTENT_TYPES:
        raise ValueError(f"invalid content type: {content_type!r}")
    users_path = Path(users_path)
    users = load_users(users_path)
    match: dict[str, str] | None = None
    needle = key.strip()
    for row in users.values():
        if row.get("uploader_id") == needle or row.get("source") == needle:
            match = row
    if match is None:
        raise KeyError(f"uploader not found: {key}")
    row = {
        "uploader_id": match["uploader_id"],
        "uploader": match.get("uploader", ""),
        "source": match.get("source", ""),
        "allowed": match.get("allowed", "") or "yes",
        "first_seen": _today_utc(),
        "note": match.get("note", ""),
        "content_type": value,
    }
    append_user(users_path, row)
    return row
