"""Batch-extract frames for every clip in the catalog."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

from game_frame_classifier.clip_catalog import (
    KNOWN_GAMES,
    ClipRecord,
    build_catalog,
    load_clip_catalog,
)
from game_frame_classifier.frame_extractor import (
    DEFAULT_HEIGHT,
    DEFAULT_INTERVAL_S,
    DEFAULT_WIDTH,
    extract_frames,
)


@dataclass(frozen=True)
class ClipExtractResult:
    """Outcome for one catalog row."""

    clip_id: str
    status: str  # extracted | skipped | error
    output_dir: str
    frame_count: int = 0
    detail: str = ""


def clip_frames_dir(
    frames_root: Path | str,
    clip: ClipRecord,
) -> Path:
    """
    ``data/frames/<Game>/<source>/<stem>/`` for one catalog clip.

    Matches the batch layout in data-layout.md.
    """
    stem = Path(clip.filename).stem
    return Path(frames_root) / clip.game / clip.source / stem


def manifest_path_for(clip_dir: Path) -> Path:
    return Path(clip_dir) / "frames_manifest.csv"


def already_extracted(clip_dir: Path) -> bool:
    return manifest_path_for(clip_dir).is_file()


def _remove_tree(path: Path) -> bool:
    """Delete a file or directory tree. Return True if something was removed."""
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def clear_batch_frame_outputs(
    frames_root: Path | str,
    clips: Sequence[ClipRecord],
    *,
    remove_orphans: bool = True,
) -> list[str]:
    """
    Delete batch extract folders so the next run starts from scratch.

    Always removes each clip's ``<Game>/<source>/<stem>/`` dir under
    ``frames_root``. When ``remove_orphans`` is True, also removes other
    stem folders under known game names that are no longer in ``clips``
    (e.g. after a source video was deleted from ``data/raw``).

    Does not touch non-game top-level folders (smoke runs, etc.).
    """
    frames_root = Path(frames_root)
    removed: list[str] = []
    expected = {clip_frames_dir(frames_root, c).resolve() for c in clips}

    for clip in clips:
        d = clip_frames_dir(frames_root, clip)
        if _remove_tree(d):
            removed.append(str(d))

    if remove_orphans and frames_root.is_dir():
        for game_dir in frames_root.iterdir():
            if not game_dir.is_dir() or game_dir.name not in KNOWN_GAMES:
                continue
            for source_dir in game_dir.iterdir():
                if not source_dir.is_dir():
                    continue
                for stem_dir in list(source_dir.iterdir()):
                    if not stem_dir.is_dir():
                        continue
                    if stem_dir.resolve() in expected:
                        continue
                    if _remove_tree(stem_dir):
                        removed.append(str(stem_dir))
                # Drop empty source / game folders left behind.
                if source_dir.is_dir() and not any(source_dir.iterdir()):
                    source_dir.rmdir()
            if game_dir.is_dir() and not any(game_dir.iterdir()):
                game_dir.rmdir()

    summary = frames_root / "batch_extract_summary.json"
    if _remove_tree(summary):
        removed.append(str(summary))

    return removed


def rebuild_from_raw(
    raw_dir: Path | str,
    manifests_dir: Path | str,
    frames_root: Path | str,
    *,
    remove_orphans: bool = True,
) -> tuple[list[ClipRecord], list[str]]:
    """
    Rescan ``raw_dir``, rewrite clips.csv/json, clear stale frame outputs.

    Catalog then matches only videos that still exist on disk.
    """
    records = build_catalog(raw_dir, manifests_dir)
    removed = clear_batch_frame_outputs(
        frames_root, records, remove_orphans=remove_orphans
    )
    return records, removed


def extract_one_clip(
    clip: ClipRecord,
    frames_root: Path | str,
    *,
    interval_s: float = DEFAULT_INTERVAL_S,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    max_duration_s: float | None = None,
    force: bool = False,
    debug: bool = False,
) -> ClipExtractResult:
    """Extract frames for one catalog clip into its frames subfolder."""
    out_dir = clip_frames_dir(frames_root, clip)
    out_str = str(out_dir.resolve()) if out_dir.exists() else str(out_dir)

    if already_extracted(out_dir) and not force:
        return ClipExtractResult(
            clip_id=clip.clip_id,
            status="skipped",
            output_dir=str(out_dir.resolve()) if out_dir.exists() else str(out_dir),
            detail="frames_manifest.csv already exists (use --force to redo)",
        )

    video_path = Path(clip.path)
    if not video_path.is_file():
        return ClipExtractResult(
            clip_id=clip.clip_id,
            status="error",
            output_dir=str(out_dir),
            detail=f"video not found: {video_path}",
        )

    try:
        records = extract_frames(
            video_path,
            out_dir,
            game=clip.game,
            video_id=Path(clip.filename).stem,
            interval_s=interval_s,
            width=width,
            height=height,
            max_duration_s=max_duration_s,
            write_manifest=True,
            debug=debug,
        )
    except Exception as exc:  # noqa: BLE001 — batch must keep going
        return ClipExtractResult(
            clip_id=clip.clip_id,
            status="error",
            output_dir=str(out_dir),
            detail=str(exc),
        )

    return ClipExtractResult(
        clip_id=clip.clip_id,
        status="extracted",
        output_dir=str(out_dir.resolve()),
        frame_count=len(records),
    )


def extract_catalog(
    catalog_path: Path | str,
    frames_root: Path | str,
    *,
    interval_s: float = DEFAULT_INTERVAL_S,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    max_duration_s: float | None = None,
    force: bool = False,
    debug: bool = False,
    game: str | None = None,
    limit: int | None = None,
) -> list[ClipExtractResult]:
    """
    Extract frames for each row in ``clips.csv`` / ``clips.json``.

    Skips clips that already have ``frames_manifest.csv`` unless ``force``.
    Errors are recorded per clip; the batch continues.
    """
    clips = load_clip_catalog(catalog_path)
    if game is not None:
        clips = [c for c in clips if c.game == game]
    if limit is not None:
        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        clips = clips[:limit]

    frames_root = Path(frames_root)
    frames_root.mkdir(parents=True, exist_ok=True)

    results: list[ClipExtractResult] = []
    for clip in clips:
        results.append(
            extract_one_clip(
                clip,
                frames_root,
                interval_s=interval_s,
                width=width,
                height=height,
                max_duration_s=max_duration_s,
                force=force,
                debug=debug,
            )
        )
    return results


def write_batch_summary(
    results: Sequence[ClipExtractResult],
    output_path: Path | str,
) -> Path:
    """Write batch_extract_summary.json next to (or at) ``output_path``."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    payload = {
        "clip_count": len(results),
        "by_status": by_status,
        "total_frames_extracted": sum(
            r.frame_count for r in results if r.status == "extracted"
        ),
        "results": [asdict(r) for r in results],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Batch-extract frames for every clip in the catalog."
    )
    p.add_argument(
        "catalog",
        type=Path,
        nargs="?",
        default=Path("data/manifests/clips.csv"),
        help="clips.csv or clips.json (default: data/manifests/clips.csv)",
    )
    p.add_argument(
        "-o",
        "--frames-root",
        type=Path,
        default=Path("data/frames"),
        help="Root for Game/source/stem folders (default: data/frames)",
    )
    p.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Raw clip root used with --clean (default: data/raw)",
    )
    p.add_argument(
        "--manifests-dir",
        type=Path,
        default=None,
        help="Where to write a fresh catalog with --clean "
        "(default: parent of catalog path, e.g. data/manifests)",
    )
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S)
    p.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    p.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    p.add_argument(
        "--max-duration",
        type=float,
        default=None,
        help="Optional cap per clip (seconds); useful for smoke runs",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even when frames_manifest.csv already exists",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="From scratch: rescan --raw-dir, rewrite clips.csv/json, "
        "delete batch frame folders (incl. orphans for removed sources), "
        "then re-extract everything",
    )
    p.add_argument("--debug", action="store_true", help="Pass through extractor --debug")
    p.add_argument("--game", default=None, help="Only process this game folder name")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N clips (after --game filter)",
    )
    p.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Where to write batch_extract_summary.json "
        "(default: <frames-root>/batch_extract_summary.json)",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    catalog_path = Path(args.catalog)
    force = bool(args.force)

    if args.clean:
        manifests_dir = Path(args.manifests_dir) if args.manifests_dir else catalog_path.parent
        records, removed = rebuild_from_raw(
            args.raw_dir,
            manifests_dir,
            args.frames_root,
        )
        catalog_path = manifests_dir / "clips.csv"
        force = True
        print(
            f"clean rebuild: catalogued {len(records)} clip(s) from {args.raw_dir}; "
            f"removed {len(removed)} stale path(s)"
        )

    results = extract_catalog(
        catalog_path,
        args.frames_root,
        interval_s=args.interval,
        width=args.width,
        height=args.height,
        max_duration_s=args.max_duration,
        force=force,
        debug=args.debug,
        game=args.game,
        limit=args.limit,
    )
    summary_path = args.summary or (Path(args.frames_root) / "batch_extract_summary.json")
    write_batch_summary(results, summary_path)

    n_ok = sum(1 for r in results if r.status == "extracted")
    n_skip = sum(1 for r in results if r.status == "skipped")
    n_err = sum(1 for r in results if r.status == "error")
    frames = sum(r.frame_count for r in results if r.status == "extracted")
    print(
        f"batch extract: {n_ok} extracted, {n_skip} skipped, {n_err} errors "
        f"({frames} new frames) → {summary_path}"
    )
    for r in results:
        if r.status == "error":
            print(f"  ERROR {r.clip_id}: {r.detail}")
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
