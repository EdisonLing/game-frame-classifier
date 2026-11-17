"""config/user.json and config/history.json (friend-pack spec §4.2, §4.3)."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from game_frame_classifier.sourcing import SCHEMA_USER
from game_frame_classifier.sourcing.labels import normalize_handle

from . import paths


@dataclass
class UserSettings:
    contributor_id: str
    handle: str
    consent_data_use: bool
    consent_public_examples: bool
    consent_utc: str
    last_game: str = ""
    frame_mode_override: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_json(path: Path, obj: Any) -> None:
    target = paths.ensure_inside_home(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def user_path() -> Path:
    return paths.config_dir() / "user.json"


def history_path() -> Path:
    return paths.config_dir() / "history.json"


def new_user(handle: str, public_examples: bool) -> UserSettings:
    return UserSettings(str(uuid.uuid4()), handle, True, public_examples, utc_now_iso())


def load_user() -> UserSettings | None:
    """Saved user, or None when missing, unreadable, or without data-use consent."""
    path = user_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_USER:
        return None
    handle = normalize_handle(str(data.get("handle") or ""))
    contributor_id = str(data.get("contributor_id") or "")
    if not handle or not contributor_id or data.get("consent_data_use") is not True:
        return None
    override = data.get("frame_mode_override")
    return UserSettings(
        contributor_id=contributor_id,
        handle=handle,
        consent_data_use=True,
        consent_public_examples=data.get("consent_public_examples") is True,
        consent_utc=str(data.get("consent_utc") or ""),
        last_game=str(data.get("last_game") or ""),
        frame_mode_override=override if override in ("native", "compact") else None,
    )


def save_user(user: UserSettings) -> None:
    atomic_write_json(user_path(), {"schema": SCHEMA_USER, **asdict(user)})


def load_history() -> dict[str, dict[str, Any]]:
    path = history_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def save_history(history: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(history_path(), history)
