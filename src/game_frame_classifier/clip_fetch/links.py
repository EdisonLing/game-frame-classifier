"""Parse contributor link lists and map Medal slugs to game labels."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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

KIND_CONTENT_TYPES = ("esports_vod", "gameplay", "streamer_overlay")
MIXED_CONTENT_TYPE = "mixed"
CONTENT_TYPES = KIND_CONTENT_TYPES + (MIXED_CONTENT_TYPE,)

OLD_MEDAL_ERROR = "old Medal link form; ask for the full medal.tv/games/... link"
UNSUPPORTED_SITE_ERROR = "unsupported site: only Medal and YouTube links are supported"


def split_content_types(raw: str) -> tuple[str, bool]:
    """Parse stored content_type into (kind, mixed).

    ``kind`` is one of ``KIND_CONTENT_TYPES`` or empty. ``mixed`` is independent
    and may combine with a kind (e.g. ``gameplay,mixed``).
    """
    kind = ""
    mixed = False
    for part in (raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        if token == MIXED_CONTENT_TYPE:
            mixed = True
        elif token in KIND_CONTENT_TYPES:
            kind = token
        else:
            raise ValueError(f"invalid content type: {token!r}")
    return kind, mixed


def join_content_types(kind: str = "", mixed: bool = False) -> str:
    """Canonical storage: ``gameplay``, ``mixed``, ``gameplay,mixed``, or empty."""
    kind = (kind or "").strip()
    if kind and kind not in KIND_CONTENT_TYPES:
        raise ValueError(f"invalid content type: {kind!r}")
    parts: list[str] = []
    if kind:
        parts.append(kind)
    if mixed:
        parts.append(MIXED_CONTENT_TYPE)
    return ",".join(parts)


def content_type_has_mixed(raw: str) -> bool:
    """True when the stored value includes the mixed flag."""
    try:
        _kind, mixed = split_content_types(raw)
    except ValueError:
        return (raw or "").strip() == MIXED_CONTENT_TYPE
    return mixed


def toggle_content_kind(current: str, kind: str) -> str:
    """Set or clear a kind (Q/W/E); mixed is preserved. Same kind again clears it."""
    if kind not in KIND_CONTENT_TYPES:
        raise ValueError(f"invalid content type: {kind!r}")
    cur_kind, mixed = split_content_types(current)
    if cur_kind == kind:
        return join_content_types("", mixed)
    return join_content_types(kind, mixed)


def toggle_mixed(current: str) -> str:
    """Add or remove mixed (R); kind is preserved."""
    kind, mixed = split_content_types(current)
    return join_content_types(kind, not mixed)


@dataclass(frozen=True)
class LinkInfo:
    url: str
    site: str
    clip_id: str
    slug: str


@dataclass(frozen=True)
class LinkEntry:
    url: str
    game: str = ""
    other_name: str = ""
    content_type: str = ""


def parse_content_type(raw: str) -> str:
    """Return a canonical content type string, or raise ValueError.

    Accepts one token (``gameplay``, ``mixed``, …) or a comma-separated
    combination of one kind plus optional ``mixed`` (``gameplay,mixed``).
    """
    value = (raw or "").strip()
    if not value:
        return ""
    if "," not in value and value in CONTENT_TYPES:
        return value
    kind, mixed = split_content_types(value)
    return join_content_types(kind, mixed)


def parse_game_field(raw: str) -> tuple[str, str]:
    """Parse a links-file game field into (game, other_name).

    Empty → ("", ""). ``Other:<name>`` → (Other, normalised name).
    A CLASSES value → (game, ""). Anything else raises ValueError.
    """
    text = (raw or "").strip()
    if not text:
        return ("", "")
    if text.startswith("Other:"):
        other = normalize_other_name(text[len("Other:") :])
        if not other:
            raise ValueError(f"invalid Other name: {raw!r}")
        return (OTHER, other)
    if text == OTHER:
        raise ValueError("Other requires Other:<name>")
    if text in CLASSES:
        return (text, "")
    raise ValueError(f"invalid game: {raw!r}")


def read_links(path: Path | str) -> list[str]:
    """One link per line; blank and # lines dropped; duplicates removed, order kept.

    Lines may be ``url[,game[,content_type]]``; only the URL is returned.
    """
    return [entry.url for entry in read_link_entries([path])]


def read_link_files(paths: list[Path | str]) -> list[str]:
    """Read links from files and folders (folders → sorted *.txt); de-dupe across files."""
    return [entry.url for entry in read_link_entries(paths)]


def read_link_entries(paths: list[Path | str]) -> list[LinkEntry]:
    """Read ``url[,game[,content_type]]`` entries; folders → sorted *.txt; de-dupe by URL."""
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(path.glob("*.txt")))
        else:
            files.append(path)
    seen: set[str] = set()
    out: list[LinkEntry] = []
    for file_path in files:
        text = Path(file_path).read_text(encoding="utf-8-sig")
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            entry = parse_link_line(line)
            if entry.url in seen:
                continue
            seen.add(entry.url)
            out.append(entry)
    return out


def parse_link_line(line: str) -> LinkEntry:
    """Parse ``<url>[,<Game>[,<content_type>]]``."""
    parts = [p.strip() for p in line.strip().split(",", 2)]
    url = parts[0]
    if not url:
        raise ValueError("empty link line")
    game, other_name = ("", "")
    content_type = ""
    if len(parts) >= 2:
        game, other_name = parse_game_field(parts[1])
    if len(parts) >= 3:
        content_type = parse_content_type(parts[2])
    return LinkEntry(url=url, game=game, other_name=other_name, content_type=content_type)


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
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        parts = [p for p in parsed.path.split("/") if p]
        qs = parse_qs(parsed.query)
        if parts and parts[0] == "watch":
            vid = (qs.get("v") or [""])[0]
            if vid:
                return LinkInfo(url=cleaned, site="youtube", clip_id=vid, slug="")
        if len(parts) >= 2 and parts[0] == "shorts" and parts[1]:
            return LinkInfo(url=cleaned, site="youtube", clip_id=parts[1], slug="")
        return LinkInfo(url=cleaned, site="youtube", clip_id="", slug="")
    if host == "youtu.be":
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[0]:
            return LinkInfo(url=cleaned, site="youtube", clip_id=parts[0], slug="")
        return LinkInfo(url=cleaned, site="youtube", clip_id="", slug="")
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


def name_prefix(game: str, other_name: str, slug: str) -> str:
    """File-name prefix: Medal slug when present, else game / other / unlabelled."""
    if slug:
        return slug
    if game == OTHER and other_name:
        return other_name
    if game:
        return game
    return "unlabelled"
