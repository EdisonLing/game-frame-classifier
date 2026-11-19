"""Ingest labelled still images into frame_sources clips.

Spec: ``docs/roadmap/tools/ingest-stills.md``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from game_frame_classifier.derive_frames import frame_name
from game_frame_classifier.public_sources import (
    PublicSourcesError,
    license_dir,
    load_sources,
    record_download,
)
from game_frame_classifier.sourcing.hashing import jpeg_size, sha256_file
from game_frame_classifier.sourcing.labels import (
    CLASSES,
    OTHER,
    normalize_handle,
    normalize_other_name,
)
from game_frame_classifier.sourcing.manifests import CLIP_COLUMNS, blank_clip_row, write_json

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_USAGE = 2

SYNTHETIC_BASE = datetime(2000, 1, 1, tzinfo=timezone.utc)
MADE_UP_WARNING = (
    "made-up groups: stills from one video may sit in different clips; "
    "near-duplicates are removed by the cleaner, but leakage is possible"
)


class IngestStillsError(Exception):
    """Expected ingest error with a command exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class StillRow:
    file: str
    game: str
    other_name: str
    group: str
    order: float | None


@dataclass
class StillClip:
    game: str
    other_name: str
    group: str
    group_origin: str
    rows: list[StillRow] = field(default_factory=list)


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` (default cwd) looking for ``pyproject.toml``."""
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return cur


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _posix_rel(path: str) -> str:
    return path.replace("\\", "/")


def read_manifest(path: Path | str, images_root: Path | str) -> list[StillRow]:
    """Parse and validate a stills manifest (Behaviour 1)."""
    path = Path(path)
    images_root = Path(images_root)
    if not images_root.is_dir():
        raise IngestStillsError(f"images folder not found: {images_root}", EXIT_USAGE)
    if not path.is_file():
        raise IngestStillsError(f"manifest not found: {path}", EXIT_USAGE)

    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise IngestStillsError("manifest has no header row", EXIT_USAGE)
        fields = {name.strip() for name in reader.fieldnames if name}
        for required in ("file", "game"):
            if required not in fields:
                raise IngestStillsError(f"manifest missing required column: {required}", EXIT_USAGE)
        has_other_name = "other_name" in fields
        has_group = "group" in fields
        has_order = "order" in fields

        rows: list[StillRow] = []
        seen_files: set[str] = set()
        missing: list[str] = []
        for raw in reader:
            file_raw = (raw.get("file") or "").strip()
            if not file_raw or file_raw.startswith("#"):
                continue
            # Blank lines already skipped by empty file; also skip all-empty rows.
            if not any((v or "").strip() for v in raw.values()):
                continue
            file_rel = _posix_rel(file_raw)
            if file_rel in seen_files:
                raise IngestStillsError(f"duplicate file in manifest: {file_rel}", EXIT_USAGE)
            seen_files.add(file_rel)

            game = (raw.get("game") or "").strip()
            if game not in CLASSES:
                raise IngestStillsError(f"unknown game: {game!r} (file {file_rel})", EXIT_USAGE)

            other_raw = (raw.get("other_name") or "").strip() if has_other_name else ""
            if game == OTHER:
                other_name = normalize_other_name(other_raw)
                if not other_name:
                    raise IngestStillsError(
                        f"Other row requires other_name (file {file_rel})", EXIT_USAGE
                    )
            else:
                other_name = ""

            group = (raw.get("group") or "").strip() if has_group else ""
            order: float | None = None
            if has_order:
                order_raw = (raw.get("order") or "").strip()
                if order_raw:
                    try:
                        order = float(order_raw)
                    except ValueError as exc:
                        raise IngestStillsError(
                            f"bad order value {order_raw!r} (file {file_rel})", EXIT_USAGE
                        ) from exc

            abs_path = images_root / Path(file_rel)
            if not abs_path.is_file():
                missing.append(file_rel)
            rows.append(
                StillRow(
                    file=file_rel,
                    game=game,
                    other_name=other_name,
                    group=group,
                    order=order,
                )
            )

    if missing:
        listed = ", ".join(missing[:20])
        more = f" (+{len(missing) - 20} more)" if len(missing) > 20 else ""
        raise IngestStillsError(f"missing image(s): {listed}{more}", EXIT_USAGE)
    if not rows:
        raise IngestStillsError("manifest has no still rows", EXIT_USAGE)
    return rows


def check_licence(source: str, *, repo_root: Path) -> None:
    """Refuse a public source without approval and a saved licence (Behaviour 2)."""
    if not source.startswith("public_"):
        return
    repo_root = Path(repo_root)
    config_path = repo_root / "config" / "public_sources.json"
    try:
        sources = load_sources(config_path)
    except PublicSourcesError as exc:
        raise IngestStillsError(str(exc), EXIT_USAGE) from exc
    entry = sources.get(source)
    if entry is None or not entry.get("approved"):
        raise IngestStillsError(
            "save the licence first: run the dataset's downloader or `fetch_license`",
            EXIT_USAGE,
        )
    license_path = license_dir(repo_root, source) / "LICENSE.txt"
    if not license_path.is_file():
        raise IngestStillsError(
            "save the licence first: run the dataset's downloader or `fetch_license`",
            EXIT_USAGE,
        )


def _sort_within_clip(rows: list[StillRow]) -> list[StillRow]:
    return sorted(
        rows,
        key=lambda r: (
            r.order is None,
            r.order if r.order is not None else 0.0,
            r.file,
        ),
    )


def group_rows(
    rows: list[StillRow],
    group_size: int,
    limit_groups: int | None,
) -> list[StillClip]:
    """Form StillClip groups (Behaviour 3)."""
    if group_size < 1:
        raise IngestStillsError("--group-size must be >= 1", EXIT_USAGE)

    dataset_buckets: dict[tuple[str, str, str], list[StillRow]] = defaultdict(list)
    made_up_buckets: dict[tuple[str, str], list[StillRow]] = defaultdict(list)
    for row in rows:
        if row.group:
            dataset_buckets[(row.game, row.other_name, row.group)].append(row)
        else:
            made_up_buckets[(row.game, row.other_name)].append(row)

    clips: list[StillClip] = []
    for (game, other_name, group), bucket in sorted(dataset_buckets.items()):
        clips.append(
            StillClip(
                game=game,
                other_name=other_name,
                group=group,
                group_origin="dataset",
                rows=_sort_within_clip(bucket),
            )
        )

    for (game, other_name), bucket in sorted(made_up_buckets.items()):
        ordered = sorted(bucket, key=lambda r: r.file)
        auto_i = 0
        for start in range(0, len(ordered), group_size):
            chunk = ordered[start : start + group_size]
            clips.append(
                StillClip(
                    game=game,
                    other_name=other_name,
                    group=f"auto{auto_i:04d}",
                    group_origin="made_up",
                    rows=_sort_within_clip(chunk),
                )
            )
            auto_i += 1

    clips.sort(key=lambda c: (c.game, c.other_name, c.group))

    if limit_groups is not None:
        if limit_groups < 0:
            raise IngestStillsError("--limit-groups must be >= 0", EXIT_USAGE)
        per_game: dict[str, int] = defaultdict(int)
        kept: list[StillClip] = []
        for clip in clips:
            if per_game[clip.game] >= limit_groups:
                continue
            kept.append(clip)
            per_game[clip.game] += 1
        clips = kept
    return clips


def clip_key_for(source: str, clip: StillClip) -> str:
    seed = f"stills:{source}:{clip.game}:{clip.other_name}:{clip.group}"
    return "c" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def clip_dest(fs_root: Path, source: str, clip: StillClip, key: str) -> Path:
    if clip.game == OTHER:
        return Path(fs_root) / "_other" / clip.other_name / source / key
    return Path(fs_root) / clip.game / source / key


def _load_still_jpeg_bytes(src: Path) -> bytes:
    """Return JPEG bytes for a still (copy JPEG; convert other formats)."""
    suffix = src.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        jpeg_size(src)  # refuse unreadable JPEGs before copying
        return src.read_bytes()
    from PIL import Image

    with Image.open(src) as im:
        rgb = im.convert("RGB")
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=95)
        return buf.getvalue()


def write_still_clip(
    fs_root: Path,
    source: str,
    clip: StillClip,
    images_root: Path,
    *,
    clip_index: int,
    force: bool,
) -> tuple[str, int, int]:
    """Write one clip folder (Behaviours 5–7). Returns (status, written, failed)."""
    fs_root = Path(fs_root)
    images_root = Path(images_root)
    key = clip_key_for(source, clip)
    dest = clip_dest(fs_root, source, clip, key)
    if (dest / "clip.json").is_file() and not force:
        return "skipped", 0, 0

    jpeg_blobs: list[bytes] = []
    source_bytes = 0
    failed = 0
    for row in clip.rows:
        src = images_root / Path(row.file)
        try:
            source_bytes += src.stat().st_size
            jpeg_blobs.append(_load_still_jpeg_bytes(src))
        except (OSError, ValueError):
            failed += 1

    if not jpeg_blobs:
        return "empty", 0, failed

    if dest.exists():
        shutil.rmtree(dest)
    full = dest / "full"
    full.mkdir(parents=True)

    h = hashlib.sha256()
    widths: list[int] = []
    heights: list[int] = []
    for i, data in enumerate(jpeg_blobs):
        h.update(data)
        out = full / frame_name(key, "full", i)
        out.write_bytes(data)
        w, ht = jpeg_size(out)
        widths.append(w)
        heights.append(ht)

    recorded = SYNTHETIC_BASE + timedelta(hours=clip_index)
    recorded_start_utc = recorded.strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = h.hexdigest()
    n = len(jpeg_blobs)

    row = blank_clip_row()
    row.update(
        {
            "clip_key": key,
            "clip_sha256": digest,
            "quick_id": digest[:16],
            "status": "ok",
            "status_detail": "stills",
            "original_filename": f"{clip.group}.stills",
            "original_relpath": clip.group,
            "file_bytes": source_bytes,
            "recorded_start_utc": recorded_start_utc,
            "recorded_start_source": "synthetic",
            "duration_s": float(n) * 5.0,
            "width": widths[0],
            "height": heights[0],
            "expected_slots": n,
            "slots": n,
            "label_hint": clip.game,
        }
    )
    payload = {c: row.get(c, "") for c in CLIP_COLUMNS}
    payload["game"] = clip.game
    payload["other_name"] = clip.other_name
    payload["stills_group"] = clip.group
    payload["group_origin"] = clip.group_origin
    write_json(payload, dest / "clip.json")
    return "written", n, failed


def _print_summary(summary: dict[str, Any]) -> None:
    per_game = summary.get("per_game") or {}
    print("ingest stills summary")
    for game in sorted(per_game):
        g = per_game[game]
        print(
            f"  {game}: clips written={g['clips_written']} skipped={g['clips_skipped']} "
            f"stills={g['stills_written']} failed={g['stills_failed']}"
        )
    made_up = summary.get("made_up_clips", 0)
    total = summary.get("clips_total", 0)
    print(f"  made_up groups: {made_up} / {total} clips")
    if made_up:
        print(f"  warning: {MADE_UP_WARNING}")


def run(
    images_root: Path | str,
    manifest: Path | str,
    source: str,
    *,
    data_root: Path | str = "data",
    repo_root: Path | str | None = None,
    group_size: int = 10,
    limit_groups: int | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ingest stills (Behaviours 8–10). Raises IngestStillsError on usage errors."""
    images_root = Path(images_root)
    manifest = Path(manifest)
    data_root = Path(data_root)
    repo_root = Path(repo_root) if repo_root is not None else find_repo_root()

    source = normalize_handle(source)
    if not source:
        raise IngestStillsError("empty --source after normalisation", EXIT_USAGE)
    if source.startswith("contributor_"):
        raise IngestStillsError(
            "contributor_ sources go through gfc-ingest-pack, not gfc-ingest-stills",
            EXIT_USAGE,
        )

    rows = read_manifest(manifest, images_root)
    check_licence(source, repo_root=repo_root)
    clips = group_rows(rows, group_size, limit_groups)

    per_game: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "clips_written": 0,
            "clips_skipped": 0,
            "clips_empty": 0,
            "stills_written": 0,
            "stills_failed": 0,
        }
    )
    made_up_clips = sum(1 for c in clips if c.group_origin == "made_up")
    plan_lines: list[str] = []
    for i, clip in enumerate(clips):
        key = clip_key_for(source, clip)
        plan_lines.append(
            f"{clip.game}/{source}/{key} "
            f"group={clip.group} origin={clip.group_origin} stills={len(clip.rows)}"
        )
        if dry_run:
            per_game[clip.game]["clips_written"] += 1
            per_game[clip.game]["stills_written"] += len(clip.rows)
            continue

        fs_root = data_root / "frame_sources"
        status, written, failed = write_still_clip(
            fs_root,
            source,
            clip,
            images_root,
            clip_index=i,
            force=force,
        )
        g = per_game[clip.game]
        g["stills_failed"] += failed
        if status == "written":
            g["clips_written"] += 1
            g["stills_written"] += written
        elif status == "skipped":
            g["clips_skipped"] += 1
        else:
            g["clips_empty"] += 1
            g["stills_failed"] += failed

    clips_written = sum(g["clips_written"] for g in per_game.values())
    clips_skipped = sum(g["clips_skipped"] for g in per_game.values())
    stills_written = sum(g["stills_written"] for g in per_game.values())
    stills_failed = sum(g["stills_failed"] for g in per_game.values())

    summary: dict[str, Any] = {
        "source": source,
        "manifest": str(manifest),
        "images_root": str(images_root),
        "group_size": group_size,
        "limit_groups": limit_groups,
        "dry_run": dry_run,
        "clips_total": len(clips),
        "clips_written": clips_written,
        "clips_skipped": clips_skipped,
        "stills_written": stills_written,
        "stills_failed": stills_failed,
        "made_up_clips": made_up_clips,
        "made_up_share": (made_up_clips / len(clips)) if clips else 0.0,
        "per_game": {k: dict(v) for k, v in sorted(per_game.items())},
        "plan": plan_lines,
    }

    if dry_run:
        print("dry-run: no files written")
        for line in plan_lines:
            print(f"  {line}")
        _print_summary(summary)
        return summary

    # Run record
    now = _utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    record_dir = data_root / "frame_sources" / "_stills" / source
    record_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "ingested_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest": str(manifest),
        "manifest_sha256": sha256_file(manifest),
        "images_folder": str(images_root),
        "source": source,
        "group_size": group_size,
        "limit_groups": limit_groups,
        "force": force,
        "counts": {
            "clips_written": clips_written,
            "clips_skipped": clips_skipped,
            "stills_written": stills_written,
            "stills_failed": stills_failed,
            "made_up_clips": made_up_clips,
            "made_up_share": summary["made_up_share"],
            "per_game": summary["per_game"],
        },
    }
    write_json(record, record_dir / f"ingest_{stamp}.json")

    if source.startswith("public_"):
        try:
            record_download(source, manifest, repo_root=repo_root)
        except PublicSourcesError as exc:
            raise IngestStillsError(str(exc), getattr(exc, "exit_code", EXIT_USAGE)) from exc

    _print_summary(summary)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfc-ingest-stills",
        description="Ingest labelled still images into data/frame_sources clips.",
    )
    p.add_argument("images_folder", type=Path, help="root for manifest file paths")
    p.add_argument("--manifest", type=Path, required=True, help="CSV manifest")
    p.add_argument("--source", required=True, help="source name (normalised)")
    p.add_argument(
        "--group-size",
        type=int,
        default=10,
        help="stills per made-up group when manifest has no group (default 10)",
    )
    p.add_argument(
        "--limit-groups",
        type=int,
        default=None,
        help="at most N clips per game",
    )
    p.add_argument("--force", action="store_true", help="rewrite existing clips")
    p.add_argument("--dry-run", action="store_true", help="validate and print plan; write nothing")
    p.add_argument("--data-root", type=Path, default=Path("data"))
    p.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="repository root for public licence checks (default: find pyproject.toml)",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    repo_root = Path(args.repo_root) if args.repo_root is not None else find_repo_root()
    try:
        summary = run(
            args.images_folder,
            args.manifest,
            args.source,
            data_root=args.data_root,
            repo_root=repo_root,
            group_size=args.group_size,
            limit_groups=args.limit_groups,
            force=args.force,
            dry_run=args.dry_run,
        )
    except IngestStillsError as exc:
        print(f"gfc-ingest-stills: {exc}", file=sys.stderr)
        return exc.exit_code
    if summary.get("stills_failed", 0) > 0:
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
