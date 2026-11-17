"""Game list, display names and label hints from file and folder names (spec §9)."""

from __future__ import annotations

import re

GAMES = ("Valorant", "League_of_Legends", "CS2", "Minecraft", "Overwatch_2", "Marvel_Rivals")
OTHER = "Other"
DISPLAY_NAMES = {
    "Valorant": "Valorant",
    "League_of_Legends": "League of Legends",
    "CS2": "CS2",
    "Minecraft": "Minecraft",
    "Overwatch_2": "Overwatch 2",
    "Marvel_Rivals": "Marvel Rivals",
    OTHER: "Other",
}
_HINTS = (
    (re.compile(r"valorant", re.I), "Valorant"),
    (re.compile(r"league[ _]?of[ _]?legends|(?<![a-z0-9])lol(?![a-z0-9])", re.I), "League_of_Legends"),
    (re.compile(r"counter[ -]strike|(?<![a-z0-9])(?:cs2|csgo)(?![a-z0-9])", re.I), "CS2"),
    (re.compile(r"minecraft", re.I), "Minecraft"),
    (re.compile(r"overwatch", re.I), "Overwatch_2"),
    (re.compile(r"marvel[ _]?rivals", re.I), "Marvel_Rivals"),
)
STEAM_APP_IDS = {"730": "CS2", "2357570": "Overwatch_2", "2767030": "Marvel_Rivals"}
_STEAM_CLIP = re.compile(r"(?<![a-z0-9])clip_(\d+)_", re.I)


def label_hints(text: str) -> set[str]:
    found = {game for pattern, game in _HINTS if pattern.search(text)}
    for match in _STEAM_CLIP.finditer(text):
        game = STEAM_APP_IDS.get(match.group(1))
        if game:
            found.add(game)
    return found


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
