"""CLI for gfc-fetch-clips."""

from __future__ import annotations

import argparse
import importlib.util
import shlex
import sys
from pathlib import Path
from typing import Callable

from game_frame_classifier.sourcing.labels import normalize_handle

from .channel import list_channel
from .download import Summary, print_summary, run
from .links import CONTENT_TYPES, parse_content_type, parse_game_field, read_link_entries
from .sample import DEFAULT_MAX_TIME_H, DEFAULT_RECENCY_BIAS, run_sample
from .users import tag_uploader, validate_source

__version__ = "1.3.0"

AskFn = Callable[[str], str]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfc-fetch-clips",
        description=(
            "Download Medal and YouTube clip links into data/incoming_clips/<source>/. "
            "Automatic sources from uploaders/channels by default; --source overrides. "
            "List a YouTube channel with --list-channel; sample with --channel; "
            "tag a channel with --tag-uploader."
        ),
    )
    p.add_argument(
        "links",
        type=Path,
        nargs="*",
        help="Links file(s) or folder(s) of *.txt",
    )
    p.add_argument(
        "--channel",
        default=None,
        metavar="URL",
        help="Sample videos from a YouTube channel by time budget (needs no links file)",
    )
    p.add_argument(
        "--max-time",
        type=float,
        default=DEFAULT_MAX_TIME_H,
        metavar="H",
        help=f"Hours to sample (default {DEFAULT_MAX_TIME_H:g}); with --channel",
    )
    p.add_argument(
        "--mode",
        choices=("new", "total"),
        default="new",
        help="With --channel: new hours (default) or minimum total held hours",
    )
    p.add_argument(
        "--recency-bias",
        type=float,
        default=DEFAULT_RECENCY_BIAS,
        metavar="B",
        help=f"Lean toward recent uploads (default {DEFAULT_RECENCY_BIAS:g}); with --channel",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for channel sampling (printed and recorded)",
    )
    preview = p.add_mutually_exclusive_group()
    preview.add_argument(
        "--preview",
        action="store_true",
        help="Open the channel-sample keep/skip page before download",
    )
    preview.add_argument(
        "--no-preview",
        action="store_true",
        help="Skip the keep/skip page (scripts / batch)",
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
    sort = p.add_mutually_exclusive_group()
    sort.add_argument(
        "--sort",
        action="store_true",
        help="After new downloads, open gfc-sort-clips (browser contact-sheet page)",
    )
    sort.add_argument(
        "--no-sort",
        action="store_true",
        help="Never prompt to open the sorter (scripts / batch)",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def sort_argv(incoming_dir: Path, data_root: Path, *, unlabelled: bool) -> list[str]:
    """Args for gfc-sort-clips after a fetch (folder + data-root, optional --unlabelled)."""
    argv = [str(incoming_dir), "--data-root", str(data_root)]
    if unlabelled:
        argv.append("--unlabelled")
    return argv


def format_sort_command(incoming_dir: Path, data_root: Path, *, unlabelled: bool) -> str:
    parts = ["gfc-sort-clips", *sort_argv(incoming_dir, data_root, unlabelled=unlabelled)]
    return " ".join(shlex.quote(p) for p in parts)


def print_next_sort_step(incoming_dir: Path, data_root: Path, summary: Summary) -> None:
    """Always print how to open the sorter after new downloads."""
    unlabelled = summary.unlabelled > 0
    cmd = format_sort_command(incoming_dir, data_root, unlabelled=unlabelled)
    print(f"next: {cmd}")
    if unlabelled:
        print("  (uses --unlabelled because this run downloaded clips with no game)")
    print("  Contact sheets open in the browser; you do not open files by hand.")


def maybe_open_sorter(
    incoming_dir: Path,
    data_root: Path,
    summary: Summary,
    *,
    sort: bool,
    no_sort: bool,
    ask: AskFn | None = None,
    launch: Callable[[list[str]], int] | None = None,
) -> int | None:
    """Prompt or --sort to open the sorter. Returns sorter exit code, or None if skipped."""
    if summary.by_status.get("ok", 0) <= 0:
        return None
    unlabelled = summary.unlabelled > 0
    argv = sort_argv(incoming_dir, data_root, unlabelled=unlabelled)
    open_it = False
    if sort:
        open_it = True
    elif no_sort:
        open_it = False
    elif ask is not None:
        answer = (ask("Open sorter now? [y/N] ") or "").strip().lower()
        open_it = answer in ("y", "yes")
    if not open_it:
        return None
    if launch is None:
        from game_frame_classifier.clip_sorter.cli import main as sort_main

        launch = sort_main
    print(f"opening sorter: {' '.join(shlex.quote(a) for a in argv)}", flush=True)
    return launch(argv)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    data_root = Path(args.data_root)
    users_path = Path(args.users) if args.users else data_root / "clip_links" / "medal_users.csv"

    channel_mode = args.channel is not None
    if channel_mode:
        if args.links or args.list_channel or args.tag_uploader:
            print(
                "error: --channel cannot be combined with links files, "
                "--list-channel or --tag-uploader",
                file=sys.stderr,
            )
            return 2
        if args.max_time <= 0:
            print("error: --max-time must be > 0", file=sys.stderr)
            return 2
        if args.recency_bias < 0:
            print("error: --recency-bias must be >= 0", file=sys.stderr)
            return 2
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
        do_preview = False
        if not args.dry_run:
            if args.preview:
                do_preview = True
            elif args.no_preview:
                do_preview = False
            else:
                do_preview = sys.stdin.isatty()
        code, summary = run_sample(
            args.channel,
            max_time_h=args.max_time,
            mode=args.mode,
            recency_bias=args.recency_bias,
            seed=args.seed,
            dry_run=args.dry_run,
            preview=do_preview,
            game=args.game,
            content_type=args.content_type,
            note=args.note,
            out=args.out,
            data_root=data_root,
            users_path=users_path,
            pause_s=args.pause_s,
        )
        if args.dry_run or summary is None or summary.by_status.get("ok", 0) <= 0:
            return code
        incoming_dir = data_root / "incoming_clips"
        print_next_sort_step(incoming_dir, data_root, summary)
        if args.no_sort:
            return code
        sort_ask: AskFn | None = None
        if not args.sort and sys.stdin.isatty():
            sort_ask = input
        sorter_code = maybe_open_sorter(
            incoming_dir,
            data_root,
            summary,
            sort=args.sort,
            no_sort=False,
            ask=sort_ask,
        )
        if sorter_code is not None and sorter_code != 0:
            return sorter_code
        return code

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
        print(
            "error: links file(s) required (or use --channel / --list-channel / --tag-uploader)",
            file=sys.stderr,
        )
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
    if args.dry_run or summary.by_status.get("ok", 0) <= 0:
        return summary.exit_code

    print_next_sort_step(incoming_dir, data_root, summary)
    if args.no_sort:
        return summary.exit_code
    sort_ask: AskFn | None = None
    if not args.sort and sys.stdin.isatty():
        sort_ask = input
    # Non-TTY without --sort: print next step only (no prompt).
    sorter_code = maybe_open_sorter(
        incoming_dir,
        data_root,
        summary,
        sort=args.sort,
        no_sort=False,
        ask=sort_ask,
    )
    if sorter_code is not None and sorter_code != 0:
        return sorter_code
    return summary.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
