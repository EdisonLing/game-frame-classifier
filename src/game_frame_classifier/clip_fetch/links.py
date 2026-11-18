"""Parse contributor link lists and map Medal slugs to game labels."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from game_frame_classifier.sourcing.labels import CLASSES, OTHER, label_hints, normalize_other_name

SLUG_GAMES: dict[str, str] = {
    "valorant": "Valorant",
    "league-of-legends": "League_of_Legends",
    "counter-strike-2": "CS2",
    "cs2": "CS2",
    "counter-strike-global-offensive": "CS2",
    "csgo": "CS2",
    "counter-strike": "CS2",
    "minecraft": "Minecraft",
    "overwatch-2": "Overwatch_2",
    "overwatch": "Overwatch_2",
    "marvel-rivals": "Marvel_Rivals",
}

OLD_MEDAL_ERROR = "old Medal link form; ask for the full medal.tv/games/... link"
# Only Medal clip links are supported and tested. Other sites (YouTube, Insights.gg, Twitch, ...)
# may be added later, each with its own link parsing, game mapping and tests.
UNSUPPORTED_SITE_ERROR = "unsupported site: only Medal clip links are supported for now"


@dataclass(frozen=True)
class LinkInfo:
    url: str
    site: str
    clip_id: str
    slug: str


def read_links(path: Path | str) -> list[str]:
    """One link per line; blank and # lines dropped; duplicates removed, order kept."""
    seen: set[str] = set()
    out: list[str] = []
    text = Path(path).read_text(encoding="utf-8-sig")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def parse_link(url: str) -> LinkInfo:
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").lower()
    if host in ("medal.tv", "www.medal.tv"):
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 4 and parts[0] == "games" and parts[2] == "clips":
            return LinkInfo(url=cleaned, site="medal", clip_id=parts[3], slug=parts[1])
        if len(parts) >= 2 and parts[0] == "clips":
            return LinkInfo(url=cleaned, site="medal", clip_id=parts[1], slug="")
        return LinkInfo(url=cleaned, site="medal", clip_id="", slug="")
    return LinkInfo(url=cleaned, site="other", clip_id="", slug="")


def game_for_slug(slug: str) -> tuple[str, str]:
    """Return (game, other_name); game in CLASSES, or ("", "") when no suggestion."""
    if not slug:
        return ("", "")
    mapped = SLUG_GAMES.get(slug.lower())
    if mapped is not None:
        return (mapped, "")
    hints = label_hints(slug.replace("-", " "))
    if len(hints) == 1:
        game = next(iter(hints))
        if game in CLASSES:
            return (game, "")
    other = normalize_other_name(slug)
    if other:
        return (OTHER, other)
    return ("", "")
