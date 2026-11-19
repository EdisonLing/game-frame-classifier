"""CLI for gfc-fetch-clips."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from game_frame_classifier.sourcing.labels import normalize_handle

from .channel import list_channel
from .download import print_summary, run
from .links import CONTENT_TYPES, parse_content_type, parse_game_field, read_link_entries
from .users import tag_uploader, validate_source

__version__ = "1.2.1"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfc-fetch-clips",
        description=(
            "Download Medal and YouTube clip links into data/incoming_clips/<source>/. "
            "Automatic sources from uploaders/channels by default; --source overrides. "
            "List a YouTube channel with --list-channel; tag a channel with --tag-uploader."
        ),
    )
    p.add_argument(
        "links",
        type=Path,
        nargs="*",
        help="Links file(s) or folder(s) of *.txt",
    )
    p.add_argument(
        "--list-channel",
        default=None,
        metavar="URL",
        help="List a YouTube channel's videos into a links file (no download)",
    )
    p.add_argument(
        "--tag-uploader",
        default=None,
        metavar="ID_OR_SOURCE",
        help="Append a content-type tag for an existing uploader (no download)",
    )
    p.add_argument(
        "--game",
        default="",
        help="Game for --list-channel lines (CLASSES or Other:<name>)",
    )
    p.add_argument(
        "--content-type",
        default="",
        choices=("",) + CONTENT_TYPES,
        help="Content type for --list-channel / --tag-uploader (and channel tag)",
    )
    p.add_argument("--note", default="", help="Note for --list-channel header / uploader row")
    p.add_argument("--out", type=Path, default=None, help="Output links file for --list-channel")
    p.add_argument(
        "--max-minutes",
        type=float,
        default=60.0,
        help="Skip videos longer than this many minutes (default 60)",
    )
    p.add_argument(
        "--source",
        default=None,
        help="Override: put every link under this source (no uploader prompts)",
    )
    p.add_argument(
        "--ask",
        action="store_true",
        help="Ask before using each new uploader (default: accept automatically)",
    )
    p.add_argument(
        "--refetch-missing",
        action="store_true",
        help="Re-download ok clips whose file is gone under incoming_clips/",
    )
    p.add_argument(
        "--users",
        type=Path,
        default=None,
        help="Uploader file (default data/clip_links/medal_users.csv)",
    )
    p.add_argument("--data-root", type=Path, default=Path("data"), help="Data root (default data)")
    p.add_argument("--pause-s", type=float, default=3.0, help="Seconds between requests (default 3)")
    p.add_argument("--limit", type=int, default=None, help="Stop after N new downloads")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse links and show games; no network",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    data_root = Path(args.data_root)
    users_path = Path(args.users) if args.users else data_root / "clip_links" / "medal_users.csv"

    if args.tag_uploader:
        if not args.content_type:
            print("error: --tag-uploader needs --content-type", file=sys.stderr)
            return 2
        try:
            parse_content_type(args.content_type)
            row = tag_uploader(users_path, args.tag_uploader, args.content_type)
        except (ValueError, KeyError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"tagged {row['uploader_id']} source={row['source']} content_type={row['content_type']}")
        return 0

    if args.list_channel:
        if args.game:
            try:
                parse_game_field(args.game)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        if args.content_type:
            try:
                parse_content_type(args.content_type)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        if not args.dry_run and importlib.util.find_spec("yt_dlp") is None:
            print("install the fetch extra: pip install yt-dlp", file=sys.stderr)
            return 2
        try:
            out = list_channel(
                args.list_channel,
                game=args.game,
                content_type=args.content_type,
                note=args.note,
                out=args.out,
                users_path=users_path,
                data_root=data_root,
            )
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"wrote {out}")
        return 0

    if not args.links:
        print("error: links file(s) required (or use --list-channel / --tag-uploader)", file=sys.stderr)
        return 2

    source_override: str | None = None
    if args.source is not None:
        source_override = validate_source(args.source)
        if not source_override:
            raw = normalize_handle(args.source)
            if not raw:
                print("error: --source is empty after normalisation", file=sys.stderr)
            elif raw.startswith("contributor_"):
                print("error: --source must not start with contributor_", file=sys.stderr)
            else:
                print("error: --source is invalid after normalisation", file=sys.stderr)
            return 2

    if not args.dry_run and importlib.util.find_spec("yt_dlp") is None:
        print("install the fetch extra: pip install yt-dlp", file=sys.stderr)
        return 2

    link_paths = [Path(p) for p in args.links]
    for path in link_paths:
        if not path.exists():
            print(f"error: links path not found: {path}", file=sys.stderr)
            return 2
        if path.is_file():
            continue
        if path.is_dir():
            continue
        print(f"error: links path not a file or folder: {path}", file=sys.stderr)
        return 2

    try:
        entries = read_link_entries(link_paths)
    except (OSError, ValueError) as exc:
        print(f"error: could not read links: {exc}", file=sys.stderr)
        return 2

    incoming_dir = data_root / "incoming_clips"
    ask = None
    if args.ask and source_override is None:
        if not sys.stdin.isatty():
            print("error: --ask needs a terminal", file=sys.stderr)
            return 2
        ask = input

    summary = run(
        entries,
        incoming_dir,
        source_override=source_override,
        users_path=users_path if source_override is None else users_path,
        ask=ask,
        refetch_missing=args.refetch_missing,
        pause_s=args.pause_s,
        limit=args.limit,
        dry_run=args.dry_run,
        max_minutes=args.max_minutes,
    )
    print_summary(summary)
    return summary.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
