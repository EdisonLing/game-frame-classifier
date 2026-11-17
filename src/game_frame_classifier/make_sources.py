"""Personal clips under data/raw/ → native full + crf45 stills in data/frame_sources/.

Scans `data/raw/<Game>/<source>/`, extracts with the shared `sourcing` code and
`config/recipe.json`, and places clips under `data/frame_sources/` in the same
layout as `gfc-ingest-pack`. Spec: `docs/roadmap/tools/make-sources.md`.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from game_frame_classifier.ingest_pack import (
    atomic_write_json,
    frame_sources_root,
    load_index,
    save_index,
)
from game_frame_classifier.sourcing import gpu
from game_frame_classifier.sourcing.extract import ClipResult, ExtractError, extract_clip
from game_frame_classifier.sourcing.ffbin import FFmpegNotFoundError, find_tools, version_line
from game_frame_classifier.sourcing.hashing import quick_id, sha256_file
from game_frame_classifier.sourcing.labels import label_hints, normalize_handle
from game_frame_classifier.sourcing.manifests import (
    CLIP_COLUMNS,
    FRAME_COLUMNS,
    blank_clip_row,
    write_table,
)
from game_frame_classifier.sourcing.probe import ProbeError, ProbeInfo, probe_file
from game_frame_classifier.sourcing.recipe import Recipe, RecipeError, load_recipe
from game_frame_classifier.sourcing.timeinfo import RecordingTimes, recording_times

__version__ = "1.0.0"
SCHEMA_PERSONAL_RUN = "gfc.personal_run/1"
SOURCE_COMMIT = "dev"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

CONTRIBUTOR_PREFIX = "contributor_"
GPU_MAX_FAILURES = 3  # clips in a row whose GPU encode failed before the run stops trying the GPU


class MakeSourcesError(ValueError):
    """Input or placement problem for personal make-sources."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def unique_run_id(fs_root: Path, base: str) -> str:
    """base, or base-2, base-3, ... when a run record with that id already exists."""
    run_id, n = base, 1
    while (fs_root / "_personal" / run_id).exists() or (fs_root / "_tmp" / run_id).exists():
        n += 1
        run_id = f"{base}-{n}"
    return run_id


def source_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return SOURCE_COMMIT
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return SOURCE_COMMIT


def check_source_name(folder_name: str) -> str:
    """Return normalised source handle, or raise if reserved for contributor packs."""
    source = normalize_handle(folder_name)
    if not source:
        raise MakeSourcesError(f"source folder name is empty after normalisation: {folder_name!r}")
    if source.startswith(CONTRIBUTOR_PREFIX):
        raise MakeSourcesError(
            f"source {source!r} is reserved for ingested packs; rename the folder under raw/"
        )
    return source


def native_recipe(recipe: Recipe) -> Recipe:
    """Force frame_mode=native so personal extracts match contributor packs."""
    if recipe.frame_mode == "native":
        return recipe
    return dataclasses.replace(recipe, frame_mode="native")


def sanitize_text(text: str, *roots: Path) -> str:
    """Strip absolute roots and common home markers from messages written to disk."""
    out = text
    for root in roots:
        resolved = str(Path(root).resolve())
        for variant in {resolved, resolved.replace("\\", "/"), str(root)}:
            if variant:
                out = re.sub(re.escape(variant), lambda _m: "<data>", out, flags=re.IGNORECASE)
    for key in ("USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH"):
        value = os.environ.get(key, "")
        if value:
            out = re.sub(re.escape(value), lambda _m: f"%{key}%", out, flags=re.IGNORECASE)
    host = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or ""
    if host:
        out = re.sub(re.escape(host), "<host>", out, flags=re.IGNORECASE)
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if user and len(user) > 1:
        out = re.sub(re.escape(user), "<user>", out, flags=re.IGNORECASE)
    return out


def rel_under(root: Path, path: Path) -> str:
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def iter_videos(source_dir: Path, extensions: set[str]) -> list[Path]:
    found: list[Path] = []
    for path in sorted(source_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in extensions:
            found.append(path)
    return found


def apply_rebuilds(fs_root: Path, index: dict[str, Any], clip_keys: list[str]) -> list[str]:
    """Remove listed clip_key folders and index entries. Returns keys that were found."""
    wanted = set(clip_keys)
    found: list[str] = []
    by_key = {str(rec.get("clip_key")): (sha, rec) for sha, rec in index.items() if isinstance(rec, dict)}
    for key in clip_keys:
        item = by_key.get(key)
        if item is None:
            print(f"  rebuild: {key} not in index (will extract if found under raw/)")
            continue
        sha, rec = item
        rel = str(rec.get("rel_dir") or "")
        dest = (fs_root / Path(rel)).resolve()
        if len(Path(rel).parts) != 3 or dest.parent.parent.parent != fs_root.resolve():
            raise MakeSourcesError(f"index entry for {key} has an invalid rel_dir {rel!r}; not deleting")
        if dest.is_dir():
            shutil.rmtree(dest)
        index.pop(sha, None)
        found.append(key)
        print(f"  rebuild: removed {rel or key}")
    missing = wanted - set(found)
    for key in sorted(missing):
        # already printed; keep quiet
        pass
    return found


def build_clip_row(
    *,
    path: Path,
    source_root: Path,
    game: str,
    info: ProbeInfo | None,
    times: RecordingTimes | None,
    sha: str,
    clip_key: str,
    status: str,
    status_detail: str,
    result: ClipResult | None,
    wall_s: float | None,
) -> dict[str, Any]:
    """One CLIP_COLUMNS row for a scanned personal clip."""
    row = blank_clip_row()
    row["quick_id"] = quick_id(path) if path.is_file() else ""
    row["original_filename"] = path.name
    row["original_relpath"] = rel_under(source_root, path) if path.exists() else path.name
    row["aliases"] = []
    row["file_bytes"] = path.stat().st_size if path.is_file() else 0
    row["status"] = status
    row["status_detail"] = status_detail
    if times is not None:
        row.update(
            file_mtime_utc=times.file_mtime_utc,
            file_mtime_local=times.file_mtime_local,
            file_created_utc=times.file_created_utc,
            container_creation_utc=times.container_creation_utc,
            filename_datetime_local=times.filename_datetime_local,
            recorded_start_utc=times.recorded_start_utc,
            recorded_start_source=times.recorded_start_source,
        )
    if info is not None:
        row.update(
            duration_s=round(info.duration_s, 3),
            start_time_s=round(info.start_time_s, 6),
            container=info.container,
            video_codec=info.video_codec,
            profile=info.profile,
            pix_fmt=info.pix_fmt,
            bit_depth=info.bit_depth,
            bitrate_bps="" if info.bitrate_bps is None else info.bitrate_bps,
            encoder_tag=info.encoder_tag,
            width=info.width,
            height=info.height,
            sar=info.sar,
            rotation=info.rotation,
            avg_fps=round(info.avg_fps, 3),
            r_fps=round(info.r_fps, 3),
            nominal_fps=round(info.nominal_fps, 3),
            vfr=info.vfr,
            color_range=info.color_range,
            color_space=info.color_space,
            color_transfer=info.color_transfer,
            color_primaries=info.color_primaries,
            hdr=info.hdr,
            audio_streams=info.audio_streams,
        )
    hints = label_hints(f"{game}/{row['original_relpath']}")
    row["label_hint"] = "|".join(sorted(hints))
    row["label_hint_conflict"] = bool(hints) and game not in hints
    if sha:
        row["clip_sha256"] = sha
        row["clip_key"] = clip_key or ("c" + sha[:12])
    if result is not None:
        row.update(
            tonemapped=result.tonemapped,
            even_cropped=result.even_cropped,
            expected_slots=result.expected_slots,
            slots=result.slots,
            unpaired_dropped=result.unpaired_dropped,
            max_align_err_s=result.max_align_err_s,
            x264_core=result.x264_core,
            low_encoder=result.low_encoder,
            gpu_fallback=sanitize_text(result.gpu_fallback, source_root)[:300],
        )
    if wall_s is not None:
        row["wall_s"] = round(wall_s, 1)
    return row


def frame_rows_for_clip(result: ClipResult, rel_dir: str) -> list[dict[str, Any]]:
    """FRAME_COLUMNS rows with rel_path relative to frame_sources/."""
    rows: list[dict[str, Any]] = []
    for img in result.images:
        name = f"{img.clip_key}_{img.tier}_b{img.bucket:06d}.jpg"
        rows.append({
            "image_id": img.image_id,
            "slot_id": img.slot_id,
            "clip_key": img.clip_key,
            "tier": img.tier,
            "crf": img.crf,
            "encoder": img.encoder,
            "encoder_rc": img.encoder_rc,
            "bucket": img.bucket,
            "target_time_s": img.target_time_s,
            "pts_time_s": img.pts_time_s,
            "rel_path": f"{rel_dir}/{img.tier}/{name}",
            "width": img.width,
            "height": img.height,
            "bytes": img.bytes,
            "sha256": img.sha256,
        })
    return rows


def place_clip(frames_root: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    (frames_root / dest.name).replace(dest)


def write_clip_json(dest: Path, row: dict[str, Any]) -> None:
    missing = [c for c in CLIP_COLUMNS if c not in row]
    if missing:
        raise MakeSourcesError(f"clip.json missing columns: {missing}")
    payload = {c: row.get(c, "") for c in CLIP_COLUMNS}
    atomic_write_json(dest / "clip.json", payload)


def choose_encoder(args: argparse.Namespace, recipe: Recipe, tools: Any, probe_dir: Path) -> gpu.GpuStatus | None:
    """Self-test the GPU encoder (D28); None means the CPU was chosen (--cpu or recipe encoder x264)."""
    if args.cpu:
        print("Video encoding: libx264 (--cpu)")
        return None
    if recipe.encoder != "auto" or not recipe.crf_list:
        print("Video encoding: libx264 (recipe encoder)")
        return None
    status = gpu.detect_gpu(tools, probe_dir)
    if status.available:
        print(f"Video encoding: {gpu.GPU_ENCODER} on {status.adapter or 'the graphics card'}")
    else:
        print(f"warning: GPU encoder unavailable, using libx264: {status.reason or 'unknown'}")
    return status


def encoder_summary(status: gpu.GpuStatus | None, stopped: str, clip_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Same keys as the Frame Export Kit's pack_manifest encoder block."""
    ok = [r for r in clip_rows if r.get("status") == "ok" and r.get("status_detail") != "dry_run"]
    encoders = [r.get("low_encoder", "") for r in ok]
    return {
        "requested": "cpu" if status is None else "gpu",
        "gpu_encoder": gpu.GPU_ENCODER,
        "gpu_available": bool(status and status.available),
        "gpu_adapter": status.adapter if status else "",
        "gpu_unavailable_reason": status.reason if status else "",
        "gpu_stopped_reason": stopped,
        "clips_gpu": encoders.count(gpu.GPU_ENCODER),
        "clips_cpu": encoders.count("libx264"),
        "clips_mixed": encoders.count("mixed"),
        "clips_gpu_fallback": sum(1 for r in ok if r.get("gpu_fallback")),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfc-make-sources",
        description="Extract personal clips from data/raw into data/frame_sources.",
    )
    p.add_argument("--data-root", type=Path, default=Path("data"), help="data root (default: data)")
    p.add_argument("--recipe", type=Path, default=Path("config/recipe.json"), help="recipe JSON")
    p.add_argument("--game", help="only this game folder")
    p.add_argument("--source", help="only this source folder (normalised handle)")
    p.add_argument("--limit", type=int, metavar="N", help="stop after N new clips")
    p.add_argument(
        "--rebuild",
        action="append",
        default=[],
        metavar="CLIP_KEY",
        help="delete that clip folder and index entry, then extract again (repeatable)",
    )
    p.add_argument("--dry-run", action="store_true", help="probe and hash only; write nothing")
    p.add_argument("--cpu", action="store_true", help="decode and encode on the CPU (libx264) even if the GPU works")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"gfc-make-sources {__version__}")
    data_root = Path(args.data_root)
    raw_root = data_root / "raw"
    if not raw_root.is_dir():
        print(f"Missing input folder: {raw_root.as_posix()}")
        return EXIT_USAGE
    try:
        recipe = native_recipe(load_recipe(args.recipe))
    except (RecipeError, OSError) as exc:
        print(f"Recipe problem: {exc}")
        return EXIT_USAGE
    if args.limit is not None and args.limit < 0:
        print("--limit must be >= 0")
        return EXIT_USAGE

    game_filter = args.game
    if game_filter and game_filter not in recipe.games:
        print(f"Unknown game {game_filter!r}; expected one of: {', '.join(recipe.games)}")
        return EXIT_USAGE
    source_filter = normalize_handle(args.source) if args.source else ""
    if args.source and not source_filter:
        print(f"Invalid --source {args.source!r}")
        return EXIT_USAGE

    try:
        tools = find_tools()
    except FFmpegNotFoundError as exc:
        print(f"ffmpeg/ffprobe not found: {exc}")
        return EXIT_USAGE

    fs_root = frame_sources_root(data_root)
    run_id = unique_run_id(fs_root, run_id_now())
    gpu_status = None if args.dry_run else choose_encoder(args, recipe, tools, fs_root / "_tmp" / f"gpu_probe_{run_id}")
    decode = None if args.cpu else gpu.DecodeCheck()
    gpu_stopped = ""
    gpu_streak = 0
    started = time.perf_counter()
    index = load_index(fs_root)

    if args.rebuild and not args.dry_run:
        fs_root.mkdir(parents=True, exist_ok=True)
        try:
            apply_rebuilds(fs_root, index, list(args.rebuild))
        except MakeSourcesError as exc:
            print(f"error: {exc}")
            return EXIT_USAGE
        save_index(fs_root, index)
    elif args.rebuild and args.dry_run:
        for key in args.rebuild:
            print(f"  dry-run rebuild: would remove {key}")

    extensions = {ext.lower() for ext in recipe.video_extensions}
    clip_rows: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []
    clips_ok = 0
    clips_failed = 0
    clips_skipped_existing = 0
    input_bytes = 0
    input_duration_s = 0.0
    slots_total = 0
    images_total = 0
    videos_found = 0
    x264_core = ""
    any_hard_refuse = False
    new_placed = 0

    tmp_run = fs_root / "_tmp" / run_id
    frames_root = tmp_run / "frames"
    stage_root = tmp_run / "stage"

    try:
        for game_dir in sorted(p for p in raw_root.iterdir() if p.is_dir()):
            game = game_dir.name
            if game not in recipe.games:
                print(f"warning: skipping unknown game folder {game!r}")
                continue
            if game_filter and game != game_filter:
                continue
            for source_dir in sorted(p for p in game_dir.iterdir() if p.is_dir()):
                try:
                    source = check_source_name(source_dir.name)
                except MakeSourcesError as exc:
                    print(f"error: {exc}")
                    any_hard_refuse = True
                    clips_failed += 1
                    continue
                if source_filter and source != source_filter:
                    continue
                for path in iter_videos(source_dir, extensions):
                    videos_found += 1
                    if args.limit is not None and new_placed >= args.limit:
                        break
                    rel = rel_under(source_dir, path)
                    print(f"  {game}/{source}/{rel}")
                    info: ProbeInfo | None = None
                    times: RecordingTimes | None = None
                    sha = ""
                    clip_key = ""
                    try:
                        info = probe_file(path, tools)
                    except (ProbeError, OSError, ValueError) as exc:
                        detail = sanitize_text(str(exc).splitlines()[0], data_root, path.parent)[:300]
                        clip_rows.append(build_clip_row(
                            path=path, source_root=source_dir, game=game, info=None, times=None,
                            sha="", clip_key="", status="skipped", status_detail=detail or "unreadable",
                            result=None, wall_s=None,
                        ))
                        print(f"    skipped: {detail or 'unreadable'}")
                        continue
                    if info.duration_s < recipe.min_duration_s:
                        times = recording_times(
                            path, path.name, info.container_creation_raw, info.duration_s,
                        )
                        clip_rows.append(build_clip_row(
                            path=path, source_root=source_dir, game=game, info=info, times=times,
                            sha="", clip_key="", status="skipped", status_detail="too_short",
                            result=None, wall_s=None,
                        ))
                        print("    skipped: too_short")
                        continue
                    times = recording_times(
                        path, path.name, info.container_creation_raw, info.duration_s,
                    )
                    try:
                        sha = sha256_file(path)
                    except OSError as exc:
                        detail = sanitize_text(str(exc).splitlines()[0], data_root)[:300]
                        clip_rows.append(build_clip_row(
                            path=path, source_root=source_dir, game=game, info=info, times=times,
                            sha="", clip_key="", status="skipped", status_detail=detail or "unreadable",
                            result=None, wall_s=None,
                        ))
                        print(f"    skipped: {detail or 'unreadable'}")
                        continue
                    clip_key = "c" + sha[:12]
                    existing = index.get(sha)
                    if existing and str(existing.get("clip_key")) == clip_key:
                        clips_skipped_existing += 1
                        clip_rows.append(build_clip_row(
                            path=path, source_root=source_dir, game=game, info=info, times=times,
                            sha=sha, clip_key=clip_key, status="skipped",
                            status_detail="skipped_existing", result=None, wall_s=None,
                        ))
                        print(f"    skipped_existing: {clip_key}")
                        continue
                    if args.dry_run:
                        print(f"    dry-run: would extract {clip_key}")
                        clip_rows.append(build_clip_row(
                            path=path, source_root=source_dir, game=game, info=info, times=times,
                            sha=sha, clip_key=clip_key, status="ok", status_detail="dry_run",
                            result=None, wall_s=None,
                        ))
                        new_placed += 1
                        continue

                    fs_root.mkdir(parents=True, exist_ok=True)
                    frames_root.mkdir(parents=True, exist_ok=True)
                    stage = stage_root / clip_key
                    dest = fs_root / game / source / clip_key
                    rel_dir = f"{game}/{source}/{clip_key}"
                    t0 = time.perf_counter()
                    try:
                        result = extract_clip(
                            tools, path, info, recipe, clip_key,
                            stage, frames_root, fs_root,
                            use_gpu=bool(gpu_status and gpu_status.available and not gpu_stopped),
                            decode=decode,
                        )
                    except (ExtractError, OSError, RuntimeError) as exc:
                        detail = sanitize_text(
                            (str(exc) or type(exc).__name__).splitlines()[0], data_root, path.parent,
                        )[:300]
                        clips_failed += 1
                        clip_rows.append(build_clip_row(
                            path=path, source_root=source_dir, game=game, info=info, times=times,
                            sha=sha, clip_key=clip_key, status="failed", status_detail=detail,
                            result=None, wall_s=None,
                        ))
                        print(f"    failed: {detail}")
                        continue
                    wall = time.perf_counter() - t0
                    try:
                        place_clip(frames_root, dest)
                        row = build_clip_row(
                            path=path, source_root=source_dir, game=game, info=info, times=times,
                            sha=sha, clip_key=clip_key, status="ok", status_detail="",
                            result=result, wall_s=wall,
                        )
                        write_clip_json(dest, row)
                        index[sha] = {
                            "clip_key": clip_key,
                            "pack_id": f"personal:{run_id}",
                            "game": game,
                            "source": source,
                            "rel_dir": rel_dir,
                        }
                        save_index(fs_root, index)
                    except (OSError, MakeSourcesError) as exc:
                        shutil.rmtree(dest, ignore_errors=True)
                        if (frames_root / clip_key).exists():
                            shutil.rmtree(frames_root / clip_key, ignore_errors=True)
                        detail = sanitize_text(
                            (str(exc) or type(exc).__name__).splitlines()[0], data_root,
                        )[:300]
                        clips_failed += 1
                        clip_rows.append(build_clip_row(
                            path=path, source_root=source_dir, game=game, info=info, times=times,
                            sha=sha, clip_key=clip_key, status="failed", status_detail=detail,
                            result=None, wall_s=None,
                        ))
                        print(f"    failed: {detail}")
                        continue

                    clip_rows.append(row)
                    frame_rows.extend(frame_rows_for_clip(result, rel_dir))
                    clips_ok += 1
                    new_placed += 1
                    input_bytes += row["file_bytes"]
                    input_duration_s += float(info.duration_s)
                    slots_total += result.slots
                    images_total += len(result.images)
                    x264_core = x264_core or result.x264_core
                    print(f"    ok: {clip_key} ({result.slots} slots, {result.low_encoder or 'no degraded tier'})")
                    if result.gpu_fallback:
                        gpu_streak += 1
                        print(f"    warning: GPU encode failed, redone with libx264: {result.gpu_fallback}")
                        if gpu_streak >= GPU_MAX_FAILURES and not gpu_stopped:
                            gpu_stopped = result.gpu_fallback
                            print(f"warning: GPU encode failed on {gpu_streak} clips in a row; the rest of this run uses libx264")
                    elif result.low_encoder == gpu.GPU_ENCODER:
                        gpu_streak = 0
                if args.limit is not None and new_placed >= args.limit:
                    break
            if args.limit is not None and new_placed >= args.limit:
                break
    finally:
        if tmp_run.exists():
            shutil.rmtree(tmp_run, ignore_errors=True)
        tmp = fs_root / "_tmp"
        if tmp.is_dir() and not any(tmp.iterdir()):
            tmp.rmdir()

    if args.dry_run:
        print(
            f"dry-run: videos={videos_found} would_extract={new_placed} "
            f"skipped_existing={clips_skipped_existing} failed={clips_failed}"
        )
        if any_hard_refuse or clips_failed:
            return EXIT_FAIL
        return EXIT_OK

    personal = fs_root / "_personal" / run_id
    personal.mkdir(parents=True, exist_ok=True)
    write_table(clip_rows, CLIP_COLUMNS, personal / "clips.csv", personal / "clips.json")
    write_table(frame_rows, FRAME_COLUMNS, personal / "frames.csv", personal / "frames.json")
    manifest = {
        "schema": SCHEMA_PERSONAL_RUN,
        "run_id": run_id,
        "created_utc": utc_now_iso(),
        "tool": {
            "name": "gfc-make-sources",
            "version": __version__,
            "source_commit": source_commit(),
        },
        "recipe": recipe.to_manifest(),
        "ffmpeg": {
            "ffmpeg_version": version_line(tools.ffmpeg),
            "ffprobe_version": version_line(tools.ffprobe),
            "build": tools.origin,
            "x264_core": x264_core,
        },
        "input": {
            "videos_found": videos_found,
            "clips_ok": clips_ok,
            "clips_failed": clips_failed,
            "clips_skipped_existing": clips_skipped_existing,
            "input_bytes": input_bytes,
            "input_duration_s": round(input_duration_s, 1),
        },
        "encoder": {**encoder_summary(gpu_status, gpu_stopped, clip_rows),
                    "decode": decode.summary() if decode is not None else "cpu (--cpu)"},
        "output": {
            "tiers": list(recipe.tiers),
            "frame_mode": "native",
            "slots": slots_total,
            "images": images_total,
        },
        "timing": {"wall_s": round(time.perf_counter() - started, 1)},
    }
    atomic_write_json(personal / "run_manifest.json", manifest)
    print(
        f"Done: ok={clips_ok} skipped_existing={clips_skipped_existing} "
        f"failed={clips_failed} -> frame_sources/_personal/{run_id}/"
    )
    if any_hard_refuse or clips_failed:
        return EXIT_FAIL
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
