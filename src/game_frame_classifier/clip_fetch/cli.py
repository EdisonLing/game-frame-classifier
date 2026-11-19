"""CLI for gfc-fetch-clips."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from game_frame_classifier.sourcing.labels import normalize_handle

from .download import print_summary, run
from .links import read_link_files
from .users import validate_source


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfc-fetch-clips",
        description=(
            "Download Medal clip links into data/incoming_clips/<source>/. "
            "Automatic sources from uploaders by default; --source overrides. "
            "Only Medal clip links (medal.tv/games/<game>/clips/<id>) are supported for now."
        ),
    )
    p.add_argument(
        "links",
        type=Path,
        nargs="+",
        help="Links file(s) or folder(s) of *.txt",
    )
    p.add_argument(
        "--source",
        default=None,
        help="Override: put every link under this source (no uploader prompts)",
    )
    p.add_argument(
        "--ask",
        action="store_true",
        help="Ask before using each new uploader (default: accept as friend_<username>)",
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
    return p


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)

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
        links = read_link_files(link_paths)
    except OSError as exc:
        print(f"error: could not read links: {exc}", file=sys.stderr)
        return 2

    data_root = Path(args.data_root)
    incoming_dir = data_root / "incoming_clips"
    users_path = Path(args.users) if args.users else data_root / "clip_links" / "medal_users.csv"
    ask = None
    if args.ask and source_override is None:
        if not sys.stdin.isatty():
            print("error: --ask needs a terminal", file=sys.stderr)
            return 2
        ask = input

    summary = run(
        links,
        incoming_dir,
        source_override=source_override,
        users_path=users_path if source_override is None else None,
        ask=ask,
        refetch_missing=args.refetch_missing,
        pause_s=args.pause_s,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print_summary(summary)
    return summary.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
