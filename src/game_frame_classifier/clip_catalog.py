"""Scan data/raw/<Game>/<source>/ and build a clip inventory manifest."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

from game_frame_classifier.frame_extractor import require_ffprobe

KNOWN_GAMES: frozenset[str] = frozenset(
    {
        "Valorant",
        "League_of_Legends",
        "CS2",
        "Minecraft",
        "Overwatch_2",
        "Marvel_Rivals",
    }
)

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mkv", ".webm", ".mov", ".avi"}
)

CLIP_FIELDNAMES = (
    "clip_id",
    "path",
    "game",
    "source",
    "filename",
    "duration_s",
    "width",
    "height",
)


@dataclass(frozen=True)
class ClipRecord:
    """One source video/clip and its catalog metadata."""

    clip_id: str
    path: str
    game: str
    source: str
    filename: str
    duration_s: float
    width: int
    height: int


def make_clip_id(game: str, source: str, filename: str) -> str:
    """Stable id: Game/source/filename."""
    return f"{game}/{source}/{filename}"


def validate_game(game: str) -> str:
    """Return game if known; otherwise raise ValueError."""
    if game not in KNOWN_GAMES:
        known = ", ".join(sorted(KNOWN_GAMES))
        raise ValueError(f"unknown game folder {game!r}; expected one of: {known}")
    return game


def probe_video_meta(video_path: Path) -> tuple[float, int, int]:
    """
    Return (duration_s, width, height) via ffprobe.

    Raises RuntimeError with the path if the file is unreadable or has no video stream.
    """
    ffprobe = require_ffprobe()
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for {video_path}\nstderr: {proc.stderr.strip()}"
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON for {video_path}") from exc

    streams = payload.get("streams") or []
    if not streams:
        raise RuntimeError(f"no video stream in {video_path}")

    stream = streams[0]
    try:
        width = int(stream["width"])
        height = int(stream["height"])
        duration_s = float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"incomplete ffprobe metadata for {video_path}") from exc

    return duration_s, width, height


def _iter_candidate_files(raw_dir: Path) -> list[tuple[str, str, Path]]:
    """
    Yield (game, source, file_path) for videos under raw/<Game>/<source>/.

    Unknown game folder names raise. Loose files (not game/source/file) are ignored.
    """
    raw_dir = Path(raw_dir)
    if not raw_dir.exists():
        return []
    if not raw_dir.is_dir():
        raise NotADirectoryError(f"raw dir is not a directory: {raw_dir}")

    found: list[tuple[str, str, Path]] = []
    for game_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        validate_game(game_dir.name)
        for source_dir in sorted(p for p in game_dir.iterdir() if p.is_dir()):
            for path in sorted(source_dir.iterdir()):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                found.append((game_dir.name, source_dir.name, path))
    return found


def scan_raw_tree(raw_dir: Path | str, *, probe: bool = True) -> list[ClipRecord]:
    """
    Scan ``raw_dir/<Game>/<source>/`` and return one ClipRecord per video.

    When ``probe`` is False (unit tests), duration/width/height are zeros and
    ffprobe is not called.
    """
    raw_dir = Path(raw_dir)
    records: list[ClipRecord] = []

    for game, source, path in _iter_candidate_files(raw_dir):
        abs_path = path.resolve()
        filename = path.name
        clip_id = make_clip_id(game, source, filename)

        if probe:
            duration_s, width, height = probe_video_meta(abs_path)
        else:
            duration_s, width, height = 0.0, 0, 0

        records.append(
            ClipRecord(
                clip_id=clip_id,
                path=str(abs_path),
                game=game,
                source=source,
                filename=filename,
                duration_s=duration_s,
                width=width,
                height=height,
            )
        )

    return records


def write_clip_catalog(
    records: Sequence[ClipRecord], output_dir: Path | str
) -> tuple[Path, Path]:
    """Write clips.csv + clips.json; return their paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "clips.csv"
    json_path = output_dir / "clips.json"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CLIP_FIELDNAMES)
        writer.writeheader()
        for rec in records:
            writer.writerow(asdict(rec))

    with json_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, indent=2)

    return csv_path, json_path


def _clip_from_mapping(row: dict) -> ClipRecord:
    return ClipRecord(
        clip_id=str(row["clip_id"]),
        path=str(row["path"]),
        game=str(row["game"]),
        source=str(row["source"]),
        filename=str(row["filename"]),
        duration_s=float(row["duration_s"]),
        width=int(row["width"]),
        height=int(row["height"]),
    )


def load_clip_catalog(path: Path | str) -> list[ClipRecord]:
    """Load clips.csv or clips.json into ClipRecord list."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"clip catalog not found: {path}")

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"expected a JSON list in {path}")
        return [_clip_from_mapping(row) for row in data]

    with path.open(newline="", encoding="utf-8") as f:
        return [_clip_from_mapping(row) for row in csv.DictReader(f)]


def build_catalog(
    raw_dir: Path | str,
    output_dir: Path | str,
    *,
    probe: bool = True,
) -> list[ClipRecord]:
    """Scan raw tree, write catalog manifests, return records."""
    records = scan_raw_tree(raw_dir, probe=probe)
    write_clip_catalog(records, output_dir)
    return records


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build a clip catalog from data/raw/<Game>/<source>/."
    )
    p.add_argument(
        "raw_dir",
        type=Path,
        nargs="?",
        default=Path("data/raw"),
        help="Root raw directory (default: data/raw)",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("data/manifests"),
        help="Directory for clips.csv / clips.json (default: data/manifests)",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    records = build_catalog(args.raw_dir, args.output_dir)
    out = Path(args.output_dir)
    print(f"catalogued {len(records)} clip(s) → {out / 'clips.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
