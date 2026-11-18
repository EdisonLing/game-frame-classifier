"""CLI for gfc-fetch-clips."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from game_frame_classifier.sourcing.labels import normalize_handle

from .download import print_summary, run
from .links import read_links


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfc-fetch-clips",
        description="Download Medal clip links into data/incoming_clips/<source>/.",
    )
    p.add_argument("links", type=Path, help="Text file of links (one per line)")
    p.add_argument(
        "--source",
        required=True,
        help="Source name (normalised); must not start with contributor_",
    )
    p.add_argument("--data-root", type=Path, default=Path("data"), help="Data root (default data)")
    p.add_argument("--pause-s", type=float, default=3.0, help="Seconds between downloads (default 3)")
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

    source = normalize_handle(args.source)
    if not source:
        print("error: --source is empty after normalisation", file=sys.stderr)
        return 2
    if source.startswith("contributor_"):
        print("error: --source must not start with contributor_", file=sys.stderr)
        return 2

    if not args.dry_run and importlib.util.find_spec("yt_dlp") is None:
        print("install the fetch extra: pip install yt-dlp", file=sys.stderr)
        return 2

    links_path = Path(args.links)
    if not links_path.is_file():
        print(f"error: links file not found: {links_path}", file=sys.stderr)
        return 2

    try:
        links = read_links(links_path)
    except OSError as exc:
        print(f"error: could not read links: {exc}", file=sys.stderr)
        return 2

    source_dir = Path(args.data_root) / "incoming_clips" / source
    summary = run(
        links,
        source_dir,
        pause_s=args.pause_s,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print_summary(summary)
    return summary.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
