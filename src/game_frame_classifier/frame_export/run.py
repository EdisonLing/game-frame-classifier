"""Process selected clips with resume, then write manifests and the zip (spec §5.8, §6)."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from game_frame_classifier.sourcing import SCHEMA_PACK
from game_frame_classifier.sourcing.extract import extract_clip
from game_frame_classifier.sourcing.ffbin import FFTools, version_line
from game_frame_classifier.sourcing.gpu import GPU_ENCODER, DecodeCheck, GpuStatus
from game_frame_classifier.sourcing.hashing import sha256_file
from game_frame_classifier.sourcing.labels import OTHER, label_hints
from game_frame_classifier.sourcing.manifests import (
    CLIP_COLUMNS,
    FRAME_COLUMNS,
    blank_clip_row,
    write_json,
    write_table,
)
from game_frame_classifier.sourcing.packzip import write_pack_zip
from game_frame_classifier.sourcing.recipe import Recipe
from game_frame_classifier.sourcing.sampler import expected_slots
from game_frame_classifier.sourcing.timeinfo import host_timezone

from . import SOURCE_COMMIT, __version__, paths, settings
from .scan import ScanItem

PIXEL_BYTES = 0.15
COMPACT_IMAGE_BYTES = 15_000
DISK_FACTOR = 2.2
SECONDS_PER_MP_SECOND = 0.1
X264_TIER_WORK = 0.75
GPU_TIER_WORK = 0.65
GPU_MAX_FAILURES = 3  # clips in a row whose GPU encode failed before the run stops trying the GPU


class DiskSpaceError(RuntimeError):
    """Not enough free disk space to continue safely."""


@dataclass
class RunContext:
    root: Path
    items: list[ScanItem]
    recipe: Recipe
    tools: FFTools
    user: settings.UserSettings
    game: str
    other_name: str
    gpu: GpuStatus | None = None  # None: the GPU was not tried (--cpu or recipe encoder x264)
    gpu_stopped: str = ""  # set when repeated GPU failures switched the rest of the run to the CPU
    decode: DecodeCheck | None = None  # None: decode on the CPU (--cpu); else per-codec GPU decode check

    @property
    def selected(self) -> list[ScanItem]:
        return [it for it in self.items if it.status == "selected"]

    @property
    def use_gpu(self) -> bool:
        return self.gpu is not None and self.gpu.available and not self.gpu_stopped


def _replace_ci(text: str, old: str, new: str) -> str:
    for variant in {old, old.replace("\\", "/")}:
        text = re.sub(re.escape(variant), lambda _m: new, text, flags=re.IGNORECASE)
    return text


class RunLog:
    """Timestamped log with the input folder, tool folder and profile path replaced."""

    def __init__(self, path: Path, input_root: Path) -> None:
        self.path = paths.ensure_inside_home(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._replacements = [
            (str(input_root), "<input>"),
            (str(paths.app_home().resolve()), "<tool>"),
        ]
        profile = os.environ.get("USERPROFILE", "")
        if profile:
            self._replacements.append((profile, "%USERPROFILE%"))

    def sanitize(self, text: str) -> str:
        for old, new in self._replacements:
            text = _replace_ci(text, old, new)
        return text

    def write(self, message: str) -> None:
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {self.sanitize(message)}\n"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)


def fmt_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    if minutes < 1:
        return "under 1 min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def fmt_bytes(n: float) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.0f} MB"
    return f"{n / 1024:.0f} KB"


def estimate_bytes(items: list[ScanItem], recipe: Recipe) -> int:
    total = 0.0
    for it in items:
        images = expected_slots(it.info.duration_s, recipe.interval_s, it.info.nominal_fps) * len(recipe.tiers)
        per_image = COMPACT_IMAGE_BYTES if recipe.frame_mode == "compact" else PIXEL_BYTES * it.info.width * it.info.height
        total += images * per_image
    return int(total)


def estimate_seconds(items: list[ScanItem], recipe: Recipe, gpu: bool = False) -> float:
    """Measured on a fast 8-core: about 0.1 s per footage second per megapixel at 60 fps (x264)."""
    tier_work = GPU_TIER_WORK if gpu else X264_TIER_WORK
    work = 0.25 * (1 if recipe.include_full else 0) + tier_work * len(recipe.crf_list)
    total = 0.0
    for it in items:
        megapixels = it.info.width * it.info.height / 1e6
        fps_factor = min(4.0, max(0.5, it.info.nominal_fps / 60))
        total += it.info.duration_s * megapixels * fps_factor * SECONDS_PER_MP_SECOND * work
    return total


def run_key(ctx: RunContext) -> str:
    text = "|".join([
        str(ctx.root.resolve()).casefold(), ctx.game, ctx.other_name,
        ctx.recipe.recipe_id, ctx.recipe.frame_mode, ",".join(ctx.recipe.tiers),
    ])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def work_dir(ctx: RunContext) -> Path:
    return paths.ensure_inside_home(paths.output_dir() / "_work" / run_key(ctx))


def load_state(work: Path) -> dict[str, Any] | None:
    path = work / "run.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("pack_id"), str) or not isinstance(data.get("notes"), dict):
        return None
    return data


def new_state(notes: dict[str, Any]) -> dict[str, Any]:
    return {"pack_id": str(uuid.uuid4()), "created_utc": settings.utc_now_iso(), "notes": notes}


def save_state(work: Path, state: dict[str, Any]) -> None:
    settings.atomic_write_json(work / "run.json", state)


def pack_dir(work: Path, state: dict[str, Any]) -> Path:
    return work / "pack" / f"gfc_pack_{state['pack_id'][:8]}"


def load_done(work: Path, pack: Path, item: ScanItem) -> dict[str, Any] | None:
    path = work / "done" / f"{item.quick_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        images = data["result"]["images"]
        complete = all((pack / img["rel_path"]).is_file() for img in images)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return data if complete else None


def _cleanup_clip(work: Path, frames_root: Path, clip_key: str) -> None:
    if not clip_key:
        return
    for folder in (work / "stage" / clip_key, frames_root / clip_key):
        if folder.exists():
            shutil.rmtree(paths.ensure_inside_home(folder))


def process(
    ctx: RunContext,
    work: Path,
    state: dict[str, Any],
    log: RunLog,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Extract every selected clip not already done; returns (done, failed) keyed by quick id."""
    pack = pack_dir(work, state)
    frames_root = pack / "frames"
    probe_dir = pack / "probe"
    for folder in (frames_root, probe_dir, work / "done", work / "stage"):
        paths.ensure_inside_home(folder).mkdir(parents=True, exist_ok=True)
    done: dict[str, dict[str, Any]] = {}
    failed: dict[str, str] = {}
    todo: list[ScanItem] = []
    for it in ctx.selected:
        data = load_done(work, pack, it)
        if data is not None:
            done[it.quick_id] = data
        else:
            todo.append(it)
    if done:
        print(f"Already done in an earlier run: {len(done)} clips.")
    remaining_s = sum(it.info.duration_s for it in todo)
    started = time.perf_counter()
    footage_done = 0.0
    gpu_streak = 0
    for n, it in enumerate(todo, 1):
        need = estimate_bytes([it], ctx.recipe) * DISK_FACTOR
        free = shutil.disk_usage(work).free
        if free < need:
            raise DiskSpaceError(
                f"Not enough free disk space: the next clip needs about {fmt_bytes(need)}, {fmt_bytes(free)} free."
            )
        label = it.path.name if len(it.path.name) <= 48 else it.path.name[:45] + "..."
        if footage_done > 0:
            eta = "ETA " + fmt_duration((time.perf_counter() - started) / footage_done * remaining_s)
        else:
            eta = "ETA after the first clip"
        prefix = f"[{n:>3}/{len(todo)}] {label:<48}"

        def show(fraction: float, prefix: str = prefix, eta: str = eta) -> None:
            print(f"\r{prefix} {int(fraction * 100):>3}%  {eta}   ", end="", flush=True)

        show(0.0)
        log.write(f"clip start {it.relpath}")
        t0 = time.perf_counter()
        clip_key = ""
        try:
            sha = sha256_file(it.path)
            clip_key = "c" + sha[:12]
            result = extract_clip(
                ctx.tools, it.path, it.info, ctx.recipe, clip_key,
                work / "stage" / clip_key, frames_root, pack, show, use_gpu=ctx.use_gpu, decode=ctx.decode,
            )
        except KeyboardInterrupt:
            _cleanup_clip(work, frames_root, clip_key)
            print()
            raise
        except Exception as exc:  # noqa: BLE001 - one bad clip must not stop the run
            _cleanup_clip(work, frames_root, clip_key)
            message = str(exc) or type(exc).__name__
            failed[it.quick_id] = log.sanitize(message.splitlines()[0])[:300]
            log.write(f"clip failed {it.relpath}: {message}\n{getattr(exc, 'stderr_tail', '')}")
            print(f"\r{prefix} failed (details in run_log.txt)          ")
            remaining_s -= it.info.duration_s
            continue
        wall = time.perf_counter() - t0
        write_json(it.info.raw, probe_dir / f"{clip_key}.json")
        data = {"clip_key": clip_key, "clip_sha256": sha, "wall_s": round(wall, 1), "result": asdict(result)}
        data["result"]["gpu_fallback"] = log.sanitize(result.gpu_fallback)  # ffmpeg errors can name the clip's path
        settings.atomic_write_json(work / "done" / f"{it.quick_id}.json", data)
        done[it.quick_id] = data
        footage_done += it.info.duration_s
        remaining_s -= it.info.duration_s
        log.write(f"clip ok {it.relpath} slots={result.slots} wall={wall:.1f}s encoder={result.low_encoder} decoder={result.decoder}")
        print(f"\r{prefix} 100%  {result.slots} slots                    ")
        if result.gpu_fallback:
            gpu_streak += 1
            log.write(f"gpu fallback {it.relpath}: {result.gpu_fallback}")
            print("      WARNING: the graphics card encode failed on this clip, so it was redone on the CPU (slower).")
            if gpu_streak >= GPU_MAX_FAILURES and ctx.use_gpu:
                ctx.gpu_stopped = result.gpu_fallback
                log.write(f"gpu stopped after {gpu_streak} failed clips in a row")
                print(f"      WARNING: the graphics card encode failed {gpu_streak} times in a row, so the rest of")
                print("      this run uses the CPU (slower, and your PC stays busier). Details are in run_log.txt.")
        elif result.low_encoder == GPU_ENCODER:
            gpu_streak = 0
    return done, failed


def clip_row(
    it: ScanItem,
    ctx: RunContext,
    done: dict[str, Any] | None,
    failed: str | None,
) -> dict[str, Any]:
    row = blank_clip_row()
    row["quick_id"] = it.quick_id
    row["original_filename"] = "" if it.detail == "steam_recording" else it.path.name
    row["original_relpath"] = it.relpath
    row["aliases"] = list(it.aliases)
    row["file_bytes"] = it.file_bytes
    if done is not None:
        row["status"], row["status_detail"] = "ok", ""
    elif failed is not None:
        row["status"], row["status_detail"] = "failed", failed
    else:
        row["status"], row["status_detail"] = "skipped", it.detail or "not_processed"
    if it.times is not None:
        t = it.times
        row.update(
            file_mtime_utc=t.file_mtime_utc,
            file_mtime_local=t.file_mtime_local,
            file_created_utc=t.file_created_utc,
            container_creation_utc=t.container_creation_utc,
            filename_datetime_local=t.filename_datetime_local,
            recorded_start_utc=t.recorded_start_utc,
            recorded_start_source=t.recorded_start_source,
        )
    if it.info is not None:
        i = it.info
        row.update(
            duration_s=round(i.duration_s, 3),
            start_time_s=round(i.start_time_s, 6),
            container=i.container,
            video_codec=i.video_codec,
            profile=i.profile,
            pix_fmt=i.pix_fmt,
            bit_depth=i.bit_depth,
            bitrate_bps="" if i.bitrate_bps is None else i.bitrate_bps,
            encoder_tag=i.encoder_tag,
            width=i.width,
            height=i.height,
            sar=i.sar,
            rotation=i.rotation,
            avg_fps=round(i.avg_fps, 3),
            r_fps=round(i.r_fps, 3),
            nominal_fps=round(i.nominal_fps, 3),
            vfr=i.vfr,
            color_range=i.color_range,
            color_space=i.color_space,
            color_transfer=i.color_transfer,
            color_primaries=i.color_primaries,
            hdr=i.hdr,
            audio_streams=i.audio_streams,
        )
    hints = label_hints(f"{ctx.root.name}/{it.relpath}")
    row["label_hint"] = "|".join(sorted(hints))
    row["label_hint_conflict"] = bool(hints) and ctx.game not in hints
    if done is not None:
        r = done["result"]
        row.update(
            clip_key=done["clip_key"],
            clip_sha256=done["clip_sha256"],
            tonemapped=r["tonemapped"],
            even_cropped=r["even_cropped"],
            expected_slots=r["expected_slots"],
            slots=r["slots"],
            unpaired_dropped=r["unpaired_dropped"],
            max_align_err_s=r["max_align_err_s"],
            x264_core=r["x264_core"],
            low_encoder=r.get("low_encoder", ""),
            gpu_fallback=r.get("gpu_fallback", ""),
            wall_s=done["wall_s"],
        )
    return row


def encoder_summary(ctx: RunContext, done: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Which encoder made the degraded tiers, and why the CPU was used if it was (D28)."""
    encoders = [d["result"].get("low_encoder", "") for d in done.values()]
    gpu = ctx.gpu
    return {
        "requested": "cpu" if gpu is None else "gpu",
        "gpu_encoder": GPU_ENCODER,
        "gpu_available": bool(gpu and gpu.available),
        "gpu_adapter": gpu.adapter if gpu else "",
        "gpu_unavailable_reason": gpu.reason if gpu else "",
        "gpu_stopped_reason": ctx.gpu_stopped,
        "clips_gpu": encoders.count(GPU_ENCODER),
        "clips_cpu": encoders.count("libx264"),
        "clips_mixed": encoders.count("mixed"),
        "clips_gpu_fallback": sum(1 for d in done.values() if d["result"].get("gpu_fallback")),
        "decode": ctx.decode.summary() if ctx.decode is not None else "cpu (--cpu)",
    }


def _os_string() -> str:
    get_version = getattr(sys, "getwindowsversion", None)
    if get_version is not None:
        v = get_version()
        return f"Windows-{v.major}.{v.minor}.{v.build}"
    return f"{platform.system()}-{platform.release()}"


def _zip_name(ctx: RunContext, out: Path) -> Path:
    """A zip path in out that neither it nor its .part file exists yet (never overwrites)."""
    game_part = f"{OTHER}-{ctx.other_name}" if ctx.game == OTHER else ctx.game
    stem = f"GFC_{game_part}_{ctx.user.handle}_{datetime.now().strftime('%Y%m%d-%H%M')}"
    candidate = out / f"{stem}.zip"
    k = 2
    while candidate.exists() or candidate.with_name(candidate.name + ".part").exists():
        candidate = out / f"{stem}-{k}.zip"
        k += 1
    return candidate


def finalize(
    ctx: RunContext,
    work: Path,
    state: dict[str, Any],
    done: dict[str, dict[str, Any]],
    failed: dict[str, str],
    log: RunLog,
    budget_min: int,
    make_zip: bool,
    zip_dir: Path,
) -> Path:
    """Write tables and manifest; zip into zip_dir, record history and delete the work dir (unless make_zip is False).

    zip_dir is the tool's output folder, or the existing folder the user named with --output.
    """
    pack = pack_dir(work, state)
    frames_root, probe_dir = pack / "frames", pack / "probe"
    ok_keys = {d["clip_key"] for d in done.values()}
    for child in list(frames_root.iterdir()):
        if child.name not in ok_keys:
            shutil.rmtree(paths.ensure_inside_home(child))
    for child in list(probe_dir.iterdir()):
        if child.stem not in ok_keys:
            paths.ensure_inside_home(child).unlink()
    rows: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    for it in ctx.items:
        d = done.get(it.quick_id) if it.status == "selected" else None
        f = failed.get(it.quick_id) if it.status == "selected" else None
        rows.append(clip_row(it, ctx, d, f))
        if d is not None:
            images.extend(d["result"]["images"])
    write_table(rows, CLIP_COLUMNS, pack / "clips.csv", pack / "clips.json")
    write_table(images, FRAME_COLUMNS, pack / "frames.csv", pack / "frames.json")
    log.write(f"run done ok={len(done)} failed={len(failed)}")
    shutil.copyfile(log.path, pack / "run_log.txt")
    files = [p for p in pack.rglob("*") if p.is_file() and p.name != "pack_manifest.json"]
    ok_items = [it for it in ctx.items if it.status == "selected" and it.quick_id in done]
    over = [it for it in ctx.items if it.detail == "over_budget"]
    selected_s = sum(it.info.duration_s for it in ctx.items if it.status == "selected")
    x264 = next((d["result"]["x264_core"] for d in done.values() if d["result"]["x264_core"]), "")
    manifest = {
        "schema": SCHEMA_PACK,
        "pack_id": state["pack_id"],
        "created_utc": settings.utc_now_iso(),
        "tool": {"name": "gfc-frame-export", "version": __version__, "source_commit": SOURCE_COMMIT},
        "recipe": ctx.recipe.to_manifest(),
        "ffmpeg": {
            "ffmpeg_version": version_line(ctx.tools.ffmpeg),
            "ffprobe_version": version_line(ctx.tools.ffprobe),
            "build": ctx.tools.origin,
            "x264_core": x264,
        },
        "encoder": encoder_summary(ctx, done),
        "host": {
            "os": _os_string(),
            "cpu_count": os.cpu_count() or 0,
            "python": platform.python_version(),
            **host_timezone(),
        },
        "contributor": {
            "handle": ctx.user.handle,
            "contributor_id": ctx.user.contributor_id,
            "consent": {
                "data_use": ctx.user.consent_data_use,
                "public_examples": ctx.user.consent_public_examples,
                "acknowledged_utc": ctx.user.consent_utc,
            },
        },
        "game": {"label": ctx.game, "other_name": ctx.other_name or None},
        "notes": state["notes"],
        "input": {
            "files_seen": len(ctx.items),
            "videos_found": sum(1 for it in ctx.items if it.detail not in ("not_video", "path_too_long", "steam_recording")),
            "clips_ok": len(ok_items),
            "clips_failed": len(failed),
            "clips_skipped": sum(1 for it in ctx.items if it.status == "skipped"),
            "input_bytes": sum(it.file_bytes for it in ok_items),
            "input_duration_s": round(sum(it.info.duration_s for it in ok_items), 1),
            "footage_budget_min": budget_min,
            "eligible_duration_s": round(selected_s + sum(it.info.duration_s for it in over), 1),
            "selected_duration_s": round(selected_s, 1),
            "over_budget_clips": len(over),
        },
        "output": {
            "tiers": list(ctx.recipe.tiers),
            "quality_mode": "both" if ctx.recipe.crf_list else "quick",
            "frame_mode": ctx.recipe.frame_mode,
            "slots": sum(d["result"]["slots"] for d in done.values()),
            "images": len(images),
            "file_count": len(files),
            "uncompressed_bytes": sum(p.stat().st_size for p in files),
        },
        "timing": {"wall_s": round(sum(d["wall_s"] for d in done.values()), 1)},
    }
    write_json(manifest, pack / "pack_manifest.json")
    if not make_zip:
        return pack
    zip_path = _zip_name(ctx, zip_dir)
    write_pack_zip(pack, zip_path)
    history = settings.load_history()
    now = settings.utc_now_iso()
    for it in ok_items:
        history[it.quick_id] = {
            "clip_sha256": done[it.quick_id]["clip_sha256"],
            "pack_id": state["pack_id"],
            "game": ctx.game,
            "packed_utc": now,
        }
    settings.save_history(history)
    shutil.rmtree(paths.ensure_inside_home(work))
    return zip_path
