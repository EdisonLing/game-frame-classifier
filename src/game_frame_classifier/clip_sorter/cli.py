"""gfc-sort-clips / python -m game_frame_classifier.clip_sorter."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from game_frame_classifier.sourcing.ffbin import find_tools
from game_frame_classifier.sourcing.labels import normalize_handle
from game_frame_classifier.sourcing.recipe import load_recipe

from .apply import plan, print_summary, run, write_report
from .scan import read_hints, scan
from .server import Session, serve
from .sheets import SheetWorker
from .store import first_undecided, replay


def _validate_source(raw: str) -> str:
    source = normalize_handle(raw)
    if not source:
        print("error: --source is empty after normalisation", file=sys.stderr)
        sys.exit(2)
    if source.startswith("contributor_"):
        print("error: --source must not start with contributor_ (reserved for packs)", file=sys.stderr)
        sys.exit(2)
    return source


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfc-sort-clips",
        description="Label a folder of clips via contact sheets, then copy into data/raw/.",
    )
    p.add_argument("folder", type=Path, help="Folder of videos (recursive; _archive ignored)")
    p.add_argument(
        "--source",
        default=None,
        help="Source name for copies (override). Default: take source from each clip's folder",
    )
    p.add_argument("--session", default="", help="Session name (default: <folder>_<source> or <folder>_auto)")
    p.add_argument("--hints", type=Path, default=None, help="CSV file,game,other_name")
    p.add_argument("--data-root", type=Path, default=Path("data"), help="Data root (default data)")
    p.add_argument("--recipe", type=Path, default=Path("config/recipe.json"), help="Recipe JSON")
    p.add_argument("--port", type=int, default=8765, help="Local port (default 8765)")
    p.add_argument("--no-open", action="store_true", help="Do not open the browser")
    p.add_argument("--apply", action="store_true", help="Apply decisions instead of serving the page")
    p.add_argument("--dry-run", action="store_true", help="With --apply: print plan, write nothing")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # File and Other names can hold any character; never crash on a narrow console code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    folder = args.folder.resolve()
    if not folder.is_dir():
        print(f"error: folder not found: {folder}", file=sys.stderr)
        return 2
    source_override: str | None = None
    if args.source is not None:
        source_override = _validate_source(args.source)
    data_root = args.data_root.resolve()
    if args.session:
        session_name = args.session
    elif source_override:
        session_name = f"{folder.name}_{source_override}"
    else:
        session_name = f"{folder.name}_auto"
    session_dir = data_root / "sorting" / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "sheets").mkdir(parents=True, exist_ok=True)

    recipe = load_recipe(args.recipe)
    tools = find_tools()
    hints_path = args.hints
    if hints_path is None:
        default_hints = folder / "hints.csv"
        if default_hints.is_file():
            hints_path = default_hints
    hints = read_hints(hints_path) if hints_path else {}
    clips = scan(folder, recipe, tools, hints, source=source_override)
    print(f"scanned {len(clips)} clips -> session {session_dir}", flush=True)

    plan_source = source_override or ""
    if args.apply:
        actions = plan(session_dir, folder, clips, plan_source, data_root)
        report = run(actions, dry_run=args.dry_run)
        if not args.dry_run:
            write_report(session_dir, report)
        else:
            print("(dry-run: nothing written)", flush=True)
            for row in report["rows"]:
                print(
                    f"  {row['rel_path']}: {row['decision']} -> {row['result']}"
                    + (f"  {row['destination']}" if row["destination"] else ""),
                    flush=True,
                )
        print_summary(report)
        return 0 if report["counts"].get("conflict", 0) == 0 else 1

    state = replay(session_dir)
    start = first_undecided(clips, state)
    worker = SheetWorker(tools, session_dir)
    worker.start(clips, start)
    session = Session(session_dir, clips, worker)
    session.current = start
    try:
        serve(session, clips, worker, args.port, open_browser=not args.no_open)
    finally:
        worker.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
