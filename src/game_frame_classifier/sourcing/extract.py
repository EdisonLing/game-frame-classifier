"""Extract tier stills for one clip with the bucket_v1 sampler (Frame Export Kit spec §5.3-5.8)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import gpu
from .derive import derive_dir
from .ffbin import FFTools, ToolError, run_ffmpeg
from .hashing import jpeg_size, sha256_file
from .probe import ProbeInfo
from .recipe import Recipe
from .sampler import expected_slots, offset_s, pair_tiers, parse_showinfo, select_expr

TONEMAP = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)
EVEN_CROP = "crop=trunc(iw/2)*2:trunc(ih/2)*2"
X264 = "libx264"


class ExtractError(RuntimeError):
    """A tier could not be extracted or aligned."""


@dataclass(frozen=True)
class ImageRecord:
    image_id: str
    slot_id: str
    clip_key: str
    tier: str
    crf: int
    bucket: int
    target_time_s: float
    pts_time_s: float
    rel_path: str
    width: int
    height: int
    bytes: int
    sha256: str
    encoder: str  # "" for full, else libx264 or the GPU encoder
    encoder_rc: str  # "" for full, else e.g. crf45 (x264) or qp51 (GPU)


@dataclass(frozen=True)
class ClipResult:
    clip_key: str
    tonemapped: bool
    even_cropped: bool
    expected_slots: int
    slots: int
    unpaired_dropped: int
    max_align_err_s: float
    x264_core: str
    images: list[ImageRecord]
    low_encoder: str = ""  # encoder of the crf tiers: libx264, the GPU encoder, "mixed" or ""
    gpu_fallback: str = ""  # why the GPU encode was redone on the CPU; "" if it wasn't


def pre_filters(info: ProbeInfo) -> list[str]:
    chain = []
    if info.hdr:
        chain.append(TONEMAP)
    if info.even_crop:
        chain.append(EVEN_CROP)
    return chain


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


class _Progress:
    def __init__(self, steps: int, callback: Callable[[float], None] | None) -> None:
        self.steps = max(1, steps)
        self.done = 0
        self.callback = callback

    def part(self, fraction: float) -> None:
        if self.callback is not None:
            self.callback(min(1.0, (self.done + fraction) / self.steps))

    def finish_step(self) -> None:
        self.done += 1
        self.part(0.0)


def encode_crf(
    tools: FFTools,
    src: Path,
    info: ProbeInfo,
    recipe: Recipe,
    crf: int,
    out_path: Path,
    stderr_path: Path,
    on_progress: Callable[[float], None] | None = None,
    *,
    gpu_qp: int | None = None,
) -> None:
    """Re-encode src at x264 CRF crf, or on the GPU at constant QP gpu_qp when given (D28)."""
    args: list[object] = [
        tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-y",
        "-progress", "pipe:1",
    ]
    if gpu_qp is not None:
        args += gpu.hw_input_args()
    args += [
        "-protocol_whitelist", "file", "-i", src,
        "-map", f"0:{info.stream_index}", "-an", "-sn", "-dn",
    ]
    filters = pre_filters(info) + (list(gpu.GPU_FILTERS) if gpu_qp is not None else [])
    if filters:
        args += ["-vf", ",".join(filters)]
    if gpu_qp is not None:
        fps = max(info.r_fps, info.avg_fps, info.nominal_fps)
        args += gpu.encode_args(gpu_qp, info.width, info.height, fps)
    else:
        args += ["-c:v", X264, "-preset", recipe.x264_preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
    args += ["-fps_mode", "passthrough", out_path]
    run_ffmpeg(args, stderr_path=stderr_path, duration_s=info.duration_s, on_progress=on_progress)


def extract_tier(
    tools: FFTools,
    src: Path,
    info: ProbeInfo,
    recipe: Recipe,
    out_dir: Path,
    stderr_path: Path,
    *,
    apply_pre: bool,
    genpts: bool = False,
    on_progress: Callable[[float], None] | None = None,
) -> list[float]:
    """Write %06d.jpg (one per bucket) into out_dir; return each image's actual pts_time."""
    off = offset_s(info.nominal_fps)
    filters = (pre_filters(info) if apply_pre else []) + [
        f"select='{select_expr(recipe.interval_s, off)}'",
        "showinfo",
    ]
    args: list[object] = [
        tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "info", "-nostats", "-y",
        "-progress", "pipe:1",
    ]
    if genpts:
        args += ["-fflags", "+genpts"]
    args += [
        "-protocol_whitelist", "file", "-i", src,
        "-map", f"0:{info.stream_index}" if apply_pre else "0:v:0",
        "-an", "-sn", "-dn", "-vf", ",".join(filters), "-fps_mode", "passthrough",
        "-c:v", "mjpeg", "-q:v", str(recipe.jpeg_qscale), "-start_number", "0",
        "-f", "image2", out_dir / "%06d.jpg",
    ]
    run_ffmpeg(args, stderr_path=stderr_path, duration_s=info.duration_s, on_progress=on_progress)
    times = parse_showinfo(stderr_path.read_text(encoding="utf-8", errors="replace"))
    count = len(list(out_dir.glob("*.jpg")))
    if count != len(times):
        raise ExtractError(f"{count} images but {len(times)} timestamps")
    return times


def read_x264_core(path: Path) -> str:
    """x264 build string (e.g. 'x264 - core 165 r3222 b35605a') from an encoded file."""
    with open(path, "rb") as f:
        data = f.read(65536)
    start = data.find(b"x264 - core ")
    if start < 0:
        return ""
    end = data.find(b" - H.264", start)
    chunk = data[start:end] if end > 0 else data[start:start + 64]
    return chunk.decode("ascii", "replace").strip()


def _extract_with_retry(
    tools: FFTools,
    src: Path,
    info: ProbeInfo,
    recipe: Recipe,
    out_dir: Path,
    log_path: Path,
    apply_pre: bool,
    progress: _Progress,
) -> list[float]:
    times = extract_tier(tools, src, info, recipe, out_dir, log_path, apply_pre=apply_pre, on_progress=progress.part)
    if not times and info.duration_s > 0:
        _reset_dir(out_dir)
        times = extract_tier(
            tools, src, info, recipe, out_dir, log_path,
            apply_pre=apply_pre, genpts=True, on_progress=progress.part,
        )
    if not times:
        raise ExtractError("no_timestamps")
    progress.finish_step()
    return times


def _lines_up(times: list[float], ref: list[float], tolerance: float) -> bool:
    return len(times) == len(ref) and all(abs(a - b) <= tolerance for a, b in zip(times, ref))


@dataclass(frozen=True)
class _TierEncode:
    times: list[float]
    encoder: str
    encoder_rc: str
    gpu_fallback: str
    x264_core: str


def _degraded_tier(
    tools: FFTools,
    src: Path,
    info: ProbeInfo,
    recipe: Recipe,
    tier: str,
    stage: Path,
    progress: _Progress,
    gpu_qp: int | None,
    ref_times: list[float] | None,
) -> _TierEncode:
    """Encode then extract one crf tier, on the GPU when gpu_qp is given.

    A GPU attempt that fails in any way (ffmpeg error, no frames, timestamps that don't
    line up with the full tier) is thrown away and the tier is redone with libx264.
    """
    crf = int(tier[3:])
    out_dir = stage / tier
    tmp = stage / f"tmp_{tier}.mp4"
    encode_log = stage / f"encode_{tier}.log"
    extract_log = stage / f"{tier}.log"
    reason = ""
    if gpu_qp is not None:
        mark = progress.done
        try:
            encode_crf(tools, src, info, recipe, crf, tmp, encode_log, progress.part, gpu_qp=gpu_qp)
            progress.finish_step()
            times = _extract_with_retry(tools, tmp, info, recipe, out_dir, extract_log, False, progress)
            if ref_times is not None and not _lines_up(times, ref_times, 0.5 / info.nominal_fps):
                raise ExtractError(
                    f"GPU output has {len(times)} samples that don't line up with the original's {len(ref_times)}"
                )
            tmp.unlink()
            return _TierEncode(times, gpu.GPU_ENCODER, f"qp{gpu_qp}", "", "")
        except (ToolError, ExtractError, OSError) as exc:
            tail = getattr(exc, "stderr_tail", "")
            reason = (gpu.error_line(tail) if tail else "") or gpu.first_line(str(exc)) or type(exc).__name__
            progress.done = mark
            _reset_dir(out_dir)
            tmp.unlink(missing_ok=True)
    encode_crf(tools, src, info, recipe, crf, tmp, encode_log, progress.part)
    progress.finish_step()
    times = _extract_with_retry(tools, tmp, info, recipe, out_dir, extract_log, False, progress)
    core = read_x264_core(tmp)
    tmp.unlink()
    return _TierEncode(times, X264, f"crf{crf}", reason, core)


def extract_clip(
    tools: FFTools,
    src: Path,
    info: ProbeInfo,
    recipe: Recipe,
    clip_key: str,
    stage: Path,
    frames_root: Path,
    rel_root: Path,
    on_progress: Callable[[float], None] | None = None,
    *,
    use_gpu: bool = False,
) -> ClipResult:
    """All tiers for one clip into frames_root/<clip_key>/<tier>/; stage is scratch space.

    use_gpu encodes the crf tiers on the GPU at recipe.gpu_qp, falling back to libx264
    per tier; the result says which encoder made each tier and why any fallback happened.
    """
    tiers = recipe.tiers
    progress = _Progress(sum(1 if t == "full" else 2 for t in tiers), on_progress)
    clip_dir = frames_root / clip_key
    try:
        _reset_dir(stage)
        times: dict[str, list[float]] = {}
        encodes: dict[str, _TierEncode] = {}
        for tier in tiers:
            out_dir = stage / tier
            out_dir.mkdir()
            if tier == "full":
                times[tier] = _extract_with_retry(tools, src, info, recipe, out_dir, stage / "full.log", True, progress)
                continue
            qp = recipe.gpu_qp.get(int(tier[3:])) if use_gpu else None
            enc = _degraded_tier(tools, src, info, recipe, tier, stage, progress, qp, times.get("full"))
            encodes[tier] = enc
            times[tier] = enc.times
        off = offset_s(info.nominal_fps)
        pairing = pair_tiers(times, recipe.interval_s, off, 0.5 / info.nominal_fps)
        if not pairing.slots:
            raise ExtractError("no complete slots across tiers")
        if recipe.frame_mode == "compact":
            for tier in tiers:
                derived = stage / f"{tier}_compact"
                derive_dir(tools, stage / tier, derived, recipe)
                shutil.rmtree(stage / tier)
                derived.rename(stage / tier)
        if clip_dir.exists():
            shutil.rmtree(clip_dir)
        images: list[ImageRecord] = []
        for slot in pairing.slots:
            slot_id = f"{clip_key}:b{slot.bucket:06d}"
            for tier in tiers:
                dst = clip_dir / tier / f"{clip_key}_{tier}_b{slot.bucket:06d}.jpg"
                dst.parent.mkdir(parents=True, exist_ok=True)
                (stage / tier / f"{slot.indices[tier]:06d}.jpg").replace(dst)
                width, height = jpeg_size(dst)
                images.append(ImageRecord(
                    image_id=f"{slot_id}:{tier}",
                    slot_id=slot_id,
                    clip_key=clip_key,
                    tier=tier,
                    crf=0 if tier == "full" else int(tier[3:]),
                    bucket=slot.bucket,
                    target_time_s=round(slot.bucket * recipe.interval_s, 6),
                    pts_time_s=round(slot.pts[tier], 6),
                    rel_path=dst.relative_to(rel_root).as_posix(),
                    width=width,
                    height=height,
                    bytes=dst.stat().st_size,
                    sha256=sha256_file(dst),
                    encoder=encodes[tier].encoder if tier in encodes else "",
                    encoder_rc=encodes[tier].encoder_rc if tier in encodes else "",
                ))
        shutil.rmtree(stage)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(clip_dir, ignore_errors=True)
        raise
    return ClipResult(
        clip_key=clip_key,
        tonemapped=info.hdr,
        even_cropped=info.even_crop,
        expected_slots=expected_slots(info.duration_s, recipe.interval_s, info.nominal_fps),
        slots=len(pairing.slots),
        unpaired_dropped=pairing.unpaired_dropped,
        max_align_err_s=pairing.max_align_err_s,
        x264_core=next((e.x264_core for e in encodes.values() if e.x264_core), ""),
        images=images,
        low_encoder=_summary(e.encoder for e in encodes.values()),
        gpu_fallback=next((e.gpu_fallback for e in encodes.values() if e.gpu_fallback), ""),
    )


def _summary(encoders: Iterable[str]) -> str:
    found = set(encoders)
    if len(found) > 1:
        return "mixed"
    return found.pop() if found else ""
