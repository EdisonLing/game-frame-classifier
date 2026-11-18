"""Game list, display names and label hints from file and folder names (spec §9)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

GAMES = ("Valorant", "League_of_Legends", "CS2", "Minecraft", "Overwatch_2", "Marvel_Rivals")
OTHER = "Other"
CLASSES = GAMES + (OTHER,)
MIXED = "Mixed"
MIXED_OTHER_NAME = "mixed_other"
MIXED_FILENAME_FORMAT = "title__timestamp_v1"
DISPLAY_NAMES = {
    "Valorant": "Valorant",
    "League_of_Legends": "League of Legends",
    "CS2": "CS2",
    "Minecraft": "Minecraft",
    "Overwatch_2": "Overwatch 2",
    "Marvel_Rivals": "Marvel Rivals",
    OTHER: "Other",
    MIXED: "(mixed)",
}
_HINTS = (
    (re.compile(r"valorant", re.I), "Valorant"),
    (re.compile(r"league[ _\-]?of[ _\-]?legends|(?<![a-z0-9])lol(?![a-z0-9])", re.I), "League_of_Legends"),
    (re.compile(r"counter[ _\-]?strike|(?<![a-z0-9])(?:cs2|csgo)(?![a-z0-9])", re.I), "CS2"),
    (re.compile(r"minecraft", re.I), "Minecraft"),
    (re.compile(r"overwatch", re.I), "Overwatch_2"),
    (re.compile(r"marvel[ _\-]?rivals", re.I), "Marvel_Rivals"),
)
STEAM_APP_IDS = {"730": "CS2", "2357570": "Overwatch_2", "2767030": "Marvel_Rivals"}
_STEAM_CLIP = re.compile(r"(?<![a-z0-9])clip_(\d+)_", re.I)
# Medal-style mixed folder names: Title__YYYY-MM-DD__HH-MM-SS.ext
_TITLE_TIMESTAMP_V1 = re.compile(
    r"^(?P<title>.+?)__(?P<date>\d{4}-\d{2}-\d{2})__(?P<time>\d{2}-\d{2}-\d{2})$"
)


@dataclass(frozen=True)
class MixedClassification:
    """Result of classifying one clip for mixed-folder mode."""

    format_id: str = MIXED_FILENAME_FORMAT
    title: str = ""
    game: str = ""  # target game label, OTHER, or empty when skipped
    detail: str = ""  # empty when assigned; skip reason otherwise
    source_title: str = ""  # original title text from the filename


def label_hints(text: str) -> set[str]:
    found = {game for pattern, game in _HINTS if pattern.search(text)}
    for match in _STEAM_CLIP.finditer(text):
        game = STEAM_APP_IDS.get(match.group(1))
        if game:
            found.add(game)
    return found


def parse_title_timestamp_v1(filename: str) -> str | None:
    """Return the title from a title__timestamp_v1 filename, or None if the format does not match."""
    stem = Path(filename).stem
    match = _TITLE_TIMESTAMP_V1.fullmatch(stem)
    if match is None:
        return None
    title = match.group("title").strip()
    return title or None


def classify_mixed_filename(filename: str, games: tuple[str, ...] | list[str] | None = None) -> MixedClassification:
    """Classify a clip name for mixed-folder mode (title__timestamp_v1 only).

    - Exactly one target-game match → that game.
    - Well-formed title with no target-game match → Other.
    - Conflicting target-game matches → skipped (mixed_label_conflict).
    - Filename not in the supported format → skipped (unsupported_mixed_filename_format).
    """
    allowed = set(games if games is not None else GAMES)
    title = parse_title_timestamp_v1(filename)
    if title is None:
        return MixedClassification(detail="unsupported_mixed_filename_format")
    found = {game for game in label_hints(title) if game in allowed}
    if len(found) > 1:
        return MixedClassification(
            title=title,
            source_title=title,
            detail="mixed_label_conflict",
        )
    if len(found) == 1:
        game = next(iter(found))
        return MixedClassification(title=title, game=game, source_title=title)
    return MixedClassification(title=title, game=OTHER, source_title=title)


def normalize_handle(text: str) -> str:
    """Lowercase [a-z0-9_]{0,24}; spaces and dashes become _, other characters dropped."""
    s = re.sub(r"[\s\-]+", "_", text.strip().lower())
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:24]


def normalize_other_name(text: str) -> str:
    """[A-Za-z0-9_]{0,32} game name for --game Other."""
    s = re.sub(r"[\s\-]+", "_", text.strip())
    s = re.sub(r"[^A-Za-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:32]
