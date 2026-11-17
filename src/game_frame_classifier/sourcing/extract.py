"""Extract tier stills for one clip with the bucket_v1 sampler (Frame Export Kit spec §5.3-5.8)."""

from __future__ import annotations

import shutil
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import gpu
from .derive import derive_dir
from .ffbin import FFTools, ToolError, run_capture, run_ffmpeg
from .hashing import jpeg_size, sha256_file
from .probe import ProbeInfo
from .recipe import Recipe
from .sampler import bucket_of, expected_slots, offset_s, pair_tiers, parse_showinfo, select_expr

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
    decoder: str = ""  # how the source was decoded: the GPU decoder or "cpu"
    source_keyint_s: float | None = None  # median keyframe interval of the source (first 30 s); None = unknown
    extract_method: str = ""  # "seek" (one seek per sample, low tier from windows) or "pass" (whole-video passes)


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
    hw_decode: bool = False,
    window: tuple[float, float] | None = None,
    force_keys: list[float] | None = None,
) -> None:
    """Re-encode src at x264 CRF crf, or on the GPU at constant QP gpu_qp when given (D28).

    hw_decode decodes src on the GPU; it is independent of which encoder is used.
    window = (start_s, duration_s) encodes only that part, starting with a fresh keyframe.
    force_keys puts a keyframe at each of these times (whole-video encode of a long-GOP source,
    so each sample still sits low_window_s after a keyframe, as it would in a window).
    """
    args: list[object] = [
        tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-y",
        "-progress", "pipe:1",
    ]
    if hw_decode:
        args += gpu.hw_decode_args()
    if gpu_qp is not None:
        args += gpu.hw_encode_device_args()
    if window is not None:
        args += ["-ss", f"{window[0]:.6f}", "-t", f"{window[1]:.6f}"]
    args += [
        "-protocol_whitelist", "file", "-i", src,
        "-map", f"0:{info.stream_index}", "-an", "-sn", "-dn",
    ]
    filters = pre_filters(info) + (list(gpu.GPU_FILTERS) if gpu_qp is not None else [])
    if filters:
        args += ["-vf", ",".join(filters)]
    fps = max(info.r_fps, info.avg_fps, info.nominal_fps)
    gop = round(recipe.low_gop_s * fps) if recipe.low_gop_s > 0 else 0
    if gpu_qp is not None:
        args += gpu.encode_args(gpu_qp, info.width, info.height, fps, gop)
    else:
        args += ["-c:v", X264, "-preset", recipe.x264_preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
        if gop > 0:
            args += ["-g", str(gop)]
    if force_keys:
        args += ["-force_key_frames", ",".join(f"{max(0.0, k):.6f}" for k in force_keys)]
    args += ["-fps_mode", "passthrough", out_path]
    run_ffmpeg(
        args, stderr_path=stderr_path, duration_s=window[1] if window else info.duration_s, on_progress=on_progress,
    )


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
    hw_decode: bool = False,
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
    if hw_decode:
        args += gpu.hw_decode_args()
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
    hw_decode: bool = False,
) -> list[float]:
    times = extract_tier(
        tools, src, info, recipe, out_dir, log_path,
        apply_pre=apply_pre, on_progress=progress.part, hw_decode=hw_decode,
    )
    if not times and info.duration_s > 0:
        _reset_dir(out_dir)
        times = extract_tier(
            tools, src, info, recipe, out_dir, log_path,
            apply_pre=apply_pre, genpts=True, on_progress=progress.part, hw_decode=hw_decode,
        )
    if not times:
        raise ExtractError("no_timestamps")
    progress.finish_step()
    return times


_PAST_END = ("Nothing was written", "before EOF", "Output file is empty")


def grab_still(
    tools: FFTools,
    src: Path,
    info: ProbeInfo,
    recipe: Recipe,
    at_s: float,
    out_jpg: Path,
    stderr_path: Path,
    *,
    stream_map: str,
    apply_pre: bool,
    hw_decode: bool = False,
) -> float | None:
    """Write the first frame at or after at_s as out_jpg; return its time, or None past the end.

    The input is seeked accurately (ffmpeg decodes from the keyframe before at_s and drops
    earlier frames), so this picks the same frame, with the same pixels, as the bucket_v1
    select pass over the whole video, while decoding at most one keyframe interval.
    """
    filters = ["select='gte(t\\,0)'"] + (pre_filters(info) if apply_pre else []) + ["showinfo"]
    args: list[object] = [
        tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "info", "-nostats", "-y",
        "-progress", "pipe:1",
    ]
    if hw_decode:
        args += gpu.hw_decode_args()
    args += [
        "-ss", f"{at_s:.6f}", "-protocol_whitelist", "file", "-i", src,
        "-map", stream_map, "-an", "-sn", "-dn", "-vf", ",".join(filters), "-frames:v", "1",
        "-fps_mode", "passthrough", "-c:v", "mjpeg", "-q:v", str(recipe.jpeg_qscale), out_jpg,
    ]
    try:
        run_ffmpeg(args, stderr_path=stderr_path)
    except ToolError as exc:
        if not out_jpg.is_file() and any(s in (exc.stderr_tail or "") for s in _PAST_END):
            return None
        raise
    times = parse_showinfo(stderr_path.read_text(encoding="utf-8", errors="replace"))
    if not out_jpg.is_file() or not times:
        return None
    return round(at_s + times[0], 6)


def seek_tier(
    tools: FFTools,
    src: Path,
    info: ProbeInfo,
    recipe: Recipe,
    out_dir: Path,
    log_path: Path,
    progress: _Progress,
    *,
    hw_decode: bool = False,
    index: SourceIndex | None = None,
) -> list[float]:
    """Full tier by one seek per bucket: %06d.jpg in out_dir, the same frames as extract_tier.

    With the source's packet index, each seek goes straight to the frame the sampler picks
    (the first frame at or after the bucket start). Recorders often put a keyframe there, and
    a seek just before it would decode the whole previous group of pictures (4K120: 1.1 s
    against 0.4 s per sample). The frame that comes back is checked; on any mismatch that
    bucket is redone with the plain seek, so the result is always the sampler's frame.
    """
    off = offset_s(info.nominal_fps)
    n = expected_slots(info.duration_s, recipe.interval_s, info.nominal_fps)
    if n <= 0:
        raise ExtractError("no_duration")
    quarter = 0.25 / info.nominal_fps
    times: list[float] = []
    for b in range(n):
        out = out_dir / f"{len(times):06d}.jpg"
        thr = max(0.0, b * recipe.interval_s - off)
        exact = None
        if index is not None:
            i = index.first_at_or_after(thr)
            if i is not None and bucket_of(index.times[i], recipe.interval_s, off) == b:
                exact = index.times[i]
        got = None
        if exact is not None and exact > thr:
            got = grab_still(
                tools, src, info, recipe, exact, out, log_path,
                stream_map=f"0:{info.stream_index}", apply_pre=True, hw_decode=hw_decode,
            )
            if got is None or abs(got - exact) > quarter:
                got = None
        if got is None:
            got = grab_still(
                tools, src, info, recipe, thr, out, log_path,
                stream_map=f"0:{info.stream_index}", apply_pre=True, hw_decode=hw_decode,
            )
        progress.part((b + 1) / n)
        if got is None:
            continue
        if bucket_of(got, recipe.interval_s, off) != b:  # bucket b has no frames (a gap); the frame belongs to a later one
            out.unlink()
            continue
        times.append(got)
    if not times:
        raise ExtractError("no_timestamps")
    progress.finish_step()
    return times


def window_tier(
    tools: FFTools,
    src: Path,
    info: ProbeInfo,
    recipe: Recipe,
    crf: int,
    ref_times: list[float],
    out_dir: Path,
    stage: Path,
    progress: _Progress,
    *,
    gpu_qp: int | None,
    hw_decode: bool,
    index: SourceIndex | None = None,
) -> tuple[list[float], str]:
    """Degraded tier from short encodes: for each full-tier time, encode recipe.low_window_s
    seconds ending at it (fresh keyframe at the start, like a stream's keyframe interval) and
    keep that frame. Returns the times and the x264 build string ("" on the GPU)."""
    half = 0.5 / info.nominal_fps
    window = stage / "window.mp4"
    encode_log, grab_log = stage / "window_encode.log", stage / "window_grab.log"
    times: list[float] = []
    core = ""
    for k, target in enumerate(ref_times):
        start = max(0.0, target - recipe.low_window_s)
        if index is not None:  # start exactly on a source keyframe at the window start, if there is one
            i = index.first_at_or_after(start - half)
            if i is not None and index.keys[i] and abs(index.times[i] - start) <= half:
                start = index.times[i]
        encode_crf(
            tools, src, info, recipe, crf, window, encode_log,
            gpu_qp=gpu_qp, hw_decode=hw_decode, window=(start, target - start + half),
        )
        if gpu_qp is None and not core:
            core = read_x264_core(window)
        got = grab_still(
            tools, window, info, recipe, max(0.0, target - start - half), out_dir / f"{k:06d}.jpg", grab_log,
            stream_map="0:v:0", apply_pre=False,
        )
        window.unlink(missing_ok=True)
        if got is None:
            raise ExtractError(f"no frame in the window ending at {target:.3f} s")
        times.append(round(start + got, 6))
        progress.part(2 * (k + 1) / len(ref_times))
    progress.done += 2
    progress.part(0.0)
    return times, core


# Seeking pays off while each sample decodes less than one full pass would (about K/2 against
# interval_s per sample); above this many sampling intervals, use whole-video passes instead.
SEEK_MAX_KEYINT = 2.0


@dataclass(frozen=True)
class SourceIndex:
    """Presentation times (seconds on ffmpeg's start-relative timeline) of every video packet,
    sorted, and which are keyframes. Read from the container without decoding."""

    times: list[float]
    keys: list[bool]

    def keyint_s(self) -> float:
        """Median keyframe interval; inf with at most one keyframe."""
        kts = [x for x, k in zip(self.times, self.keys) if k]
        if len(kts) < 2:
            return float("inf")
        gaps = sorted(b - a for a, b in zip(kts, kts[1:]))
        return round(gaps[len(gaps) // 2], 3)

    def first_at_or_after(self, t: float) -> int | None:
        i = bisect_left(self.times, t - 1e-6)
        return i if i < len(self.times) else None


def source_index(tools: FFTools, src: Path, info: ProbeInfo) -> SourceIndex | None:
    """Packet times and keyframe flags of the video stream (about 0.4 s for 3 min of 4K120)."""
    try:
        proc = run_capture([
            tools.ffprobe, "-v", "error", "-select_streams", str(info.stream_index),
            "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", src,
        ], timeout=600)
    except ToolError:
        return None
    if proc.returncode != 0:
        return None
    rows = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            rows.append((round(float(parts[0]) - info.start_time_s, 6), "K" in parts[1]))
        except ValueError:
            continue
    if not rows:
        return None
    rows.sort()
    return SourceIndex([r[0] for r in rows], [r[1] for r in rows])


def source_keyint_s(tools: FFTools, src: Path, stream_index: int) -> float | None:
    """Median keyframe interval of a file's video stream (inf: at most one keyframe; None: unknown)."""
    from .probe import probe_file

    index = source_index(tools, src, probe_file(src, tools))
    return None if index is None else index.keyint_s()


def _use_seeks(keyint: float | None, recipe: Recipe) -> bool:
    return keyint is not None and keyint <= SEEK_MAX_KEYINT * recipe.interval_s


def _lines_up(times: list[float], ref: list[float], tolerance: float) -> bool:
    return len(times) == len(ref) and all(abs(a - b) <= tolerance for a, b in zip(times, ref))


def _check_pairs(full_dir: Path, low_dir: Path) -> list[tuple[Path, Path]]:
    """First, middle and last (full, low) still pairs; the same file name is the same slot."""
    names = sorted(f.name for f in low_dir.glob("*.jpg"))
    if not names:
        return []
    picks = sorted({names[0], names[len(names) // 2], names[-1]})
    return [(full_dir / n, low_dir / n) for n in picks if (full_dir / n).is_file()]


def _encode_tier(
    tools: FFTools, src: Path, info: ProbeInfo, recipe: Recipe, crf: int, stage: Path, tier: str,
    progress: _Progress, gpu_qp: int | None, hw_decode_src: bool, ref_times: list[float] | None,
    seeks: bool = True,
    index: SourceIndex | None = None,
) -> tuple[list[float], str]:
    """One degraded tier. With low_window_s and the full tier's times: short windows when the
    source seeks cheaply, else the whole video with a keyframe forced low_window_s before each
    sample (the same structure). Returns the times and the x264 build string ("" on the GPU)."""
    out_dir = stage / tier
    tmp = stage / f"tmp_{tier}.mp4"
    mark = progress.done
    try:
        if recipe.low_window_s > 0 and ref_times and seeks:
            return window_tier(
                tools, src, info, recipe, crf, ref_times, out_dir, stage, progress,
                gpu_qp=gpu_qp, hw_decode=hw_decode_src, index=index,
            )
        force = [t - recipe.low_window_s for t in ref_times] if recipe.low_window_s > 0 and ref_times else None
        encode_crf(
            tools, src, info, recipe, crf, tmp, stage / f"encode_{tier}.log", progress.part,
            gpu_qp=gpu_qp, hw_decode=hw_decode_src, force_keys=force,
        )
        progress.finish_step()
        times = _extract_with_retry(tools, tmp, info, recipe, out_dir, stage / f"{tier}.log", False, progress)
        core = read_x264_core(tmp) if gpu_qp is None else ""
        tmp.unlink()
        return times, core
    except BaseException:
        progress.done = mark
        _reset_dir(out_dir)
        tmp.unlink(missing_ok=True)
        (stage / "window.mp4").unlink(missing_ok=True)
        raise


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
    *,
    hw_decode_src: bool = False,
    seeks: bool = True,
    index: SourceIndex | None = None,
) -> _TierEncode:
    """Encode then extract one crf tier, on the GPU when gpu_qp is given.

    A GPU attempt that fails in any way (ffmpeg error, no frames, timestamps that don't
    line up with the full tier, pictures too far from the full tier's) is thrown away and
    the tier is redone with libx264. GPU decode of the source (hw_decode_src) is separate
    from the encoder: the libx264 redo keeps it, and drops it only if the redo itself fails.
    The intermediate H.264 file is always decoded on the CPU: copying its frames back from
    the GPU costs more than the decode (4K120 test: 47 s on the GPU against 18 s on the CPU).
    """
    crf = int(tier[3:])
    out_dir = stage / tier
    reason = ""
    if gpu_qp is not None:
        try:
            times, _ = _encode_tier(
                tools, src, info, recipe, crf, stage, tier, progress, gpu_qp, hw_decode_src, ref_times, seeks, index,
            )
            if ref_times is not None and not _lines_up(times, ref_times, 0.5 / info.nominal_fps):
                raise ExtractError(
                    f"GPU output has {len(times)} samples that don't line up with the original's {len(ref_times)}"
                )
            if ref_times is not None:
                ok, why = gpu.pictures_ok(tools, _check_pairs(stage / "full", out_dir))
                if not ok:
                    raise ExtractError(why)
            return _TierEncode(times, gpu.GPU_ENCODER, f"qp{gpu_qp}", "", "")
        except (ToolError, ExtractError, OSError) as exc:
            tail = getattr(exc, "stderr_tail", "")
            reason = (gpu.error_line(tail) if tail else "") or gpu.first_line(str(exc)) or type(exc).__name__
            _reset_dir(out_dir)
    try:
        times, core = _encode_tier(
            tools, src, info, recipe, crf, stage, tier, progress, None, hw_decode_src, ref_times, seeks, index,
        )
    except (ToolError, ExtractError) as exc:
        if not hw_decode_src:
            raise
        reason = reason or f"GPU decode failed: {gpu.first_line(str(exc))}"
        _reset_dir(out_dir)
        times, core = _encode_tier(
            tools, src, info, recipe, crf, stage, tier, progress, None, False, ref_times, seeks, index,
        )
    return _TierEncode(times, X264, f"crf{crf}", reason, core)


def _full_tier(
    tools: FFTools, src: Path, info: ProbeInfo, recipe: Recipe, out_dir: Path, stage: Path,
    progress: _Progress, hw_decode: bool, seeks: bool = True, index: SourceIndex | None = None,
) -> list[float]:
    """Seek per bucket; for a long-GOP source, or a file that can't be seeked that way, one pass
    over the whole video (the same frames either way)."""
    if not seeks:
        return _extract_with_retry(tools, src, info, recipe, out_dir, stage / "full.log", True, progress, hw_decode)
    mark = progress.done
    try:
        return seek_tier(
            tools, src, info, recipe, out_dir, stage / "full.log", progress, hw_decode=hw_decode, index=index,
        )
    except ExtractError:
        progress.done = mark
        _reset_dir(out_dir)
        return _extract_with_retry(tools, src, info, recipe, out_dir, stage / "full.log", True, progress, hw_decode)


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
    decode: gpu.DecodeCheck | None = None,
) -> ClipResult:
    """All tiers for one clip into frames_root/<clip_key>/<tier>/; stage is scratch space.

    use_gpu encodes the crf tiers on the GPU at recipe.gpu_qp, falling back to libx264
    per tier; the result says which encoder made each tier and why any fallback happened.
    decode (separate from use_gpu) decodes on the GPU for codecs whose GPU decode matched
    CPU decode bit for bit; a GPU decode that fails is redone on the CPU.
    """
    tiers = recipe.tiers
    progress = _Progress(sum(1 if t == "full" else 2 for t in tiers), on_progress)
    clip_dir = frames_root / clip_key
    try:
        _reset_dir(stage)
        times: dict[str, list[float]] = {}
        encodes: dict[str, _TierEncode] = {}
        index = source_index(tools, src, info)
        keyint = None if index is None else index.keyint_s()
        seeks = _use_seeks(keyint, recipe)
        hw_src = bool(decode) and decode.allowed(
            tools, src, info.stream_index, info.video_codec, info.bit_depth, info.width, info.height,
            info.nominal_fps,
        )
        for tier in tiers:
            out_dir = stage / tier
            out_dir.mkdir()
            if tier == "full":
                try:
                    times[tier] = _full_tier(tools, src, info, recipe, out_dir, stage, progress, hw_src, seeks, index)
                except (ToolError, ExtractError):
                    if not hw_src:
                        raise
                    hw_src = False
                    _reset_dir(out_dir)
                    times[tier] = _full_tier(tools, src, info, recipe, out_dir, stage, progress, False, seeks, index)
                continue
            qp = recipe.gpu_qp.get(int(tier[3:])) if use_gpu else None
            enc = _degraded_tier(
                tools, src, info, recipe, tier, stage, progress, qp, times.get("full"),
                hw_decode_src=hw_src, seeks=seeks, index=index,
            )
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
        decoder=gpu.GPU_DECODE if hw_src else "cpu",
        source_keyint_s=None if keyint is None or keyint == float("inf") else keyint,
        extract_method="seek" if seeks else "pass",
    )


def _summary(encoders: Iterable[str]) -> str:
    found = set(encoders)
    if len(found) > 1:
        return "mixed"
    return found.pop() if found else ""
