"""Vendor-neutral GPU video encode (Direct3D 12) and decode (D3D11VA), each with its own check (D28).

D3D12 video encode works on NVIDIA, AMD and Intel through the normal graphics
driver (Windows 11). It is tried once at startup by encoding a short test clip and
checking the frame count and the picture; anything unexpected means libx264.

GPU decode is checked separately, per codec: the first frames of a real clip are
decoded on the GPU and on the CPU, and the GPU is used for that codec only when the
pixels are identical. Decode and encode never disable each other.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .ffbin import FFTools, ToolError, run_capture

GPU_ENCODER = "h264_d3d12va"
HW_DEVICE = "d3d12va"
# GPU decode, used for every ffmpeg call on a codec that passed DecodeCheck (bit-exact
# with CPU decode; ffmpeg also falls back to software decode by itself when it can't).
GPU_DECODE = "d3d11va"
DECODE_CHECK_FRAMES = 8
# Lowest acceptable PSNR (dB) of a GPU-encoded picture against its source. QP 51 lands
# far above this on real footage; a broken encoder (green, black or garbled frames) far below.
MIN_PSNR_DB = 18.0
# Appended to the -vf chain: CPU frames (after tone-map / crop) are uploaded to the GPU.
GPU_FILTERS = ("format=nv12", "hwupload")
# H.264 level 5.2 allows 2,073,600 macroblocks per second (e.g. 4K60). Above that no level
# fits, and drivers refuse to open the encoder (4K120, 3440x1440 at 144 fps), so the level is
# pinned to 5.2. The level is only a label for decoders; it doesn't change constant-QP output.
LEVEL_52_MBPS = 2_073_600
PROBE_FRAMES = 30
PROBE_TIMEOUT_S = 90
_PROBE_SOURCE = f"testsrc2=s=1280x720:r=30:d={PROBE_FRAMES / 30:g}"
_ADAPTER = re.compile(r"Using device [0-9a-fA-F]{4}:[0-9a-fA-F]{4} \((.+?)\)\.?\s*$", re.MULTILINE)


@dataclass(frozen=True)
class GpuStatus:
    available: bool
    adapter: str = ""
    reason: str = ""  # why it is not available; empty when available


def adapter_name(log: str) -> str:
    """Graphics card name from ffmpeg's verbose device line, or ''."""
    match = _ADAPTER.search(log)
    return match.group(1).strip()[:100] if match else ""


def first_line(text: str, limit: int = 200) -> str:
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    return lines[0][:limit] if lines else ""


_CONTEXT = re.compile(r"^(?:\[[^\]]*\]\s*)+")  # "[vost#0:0 @ 0000029b...] " prefixes
_ERRORISH = re.compile(r"error|fail|not found|unsupported|not supported|cannot|invalid|unknown", re.IGNORECASE)


def error_line(text: str) -> str:
    """The most telling line of an ffmpeg log for a failed GPU encode.

    The encoder's own messages if it logged any (e.g. "Resolution not supported"), else
    the first error-like line. Notices that GPU decode fell back to the CPU are skipped:
    ffmpeg carries on in software after them, so they are never the cause.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("Exiting with")]
    encoder = [_CONTEXT.sub("", ln).lstrip("- ") for ln in lines if f"[{GPU_ENCODER} @" in ln]
    if encoder:
        return " / ".join(encoder)[:200]
    errors = [ln for ln in lines if _ERRORISH.search(ln) and "hwaccel" not in ln and "Failed setup for format" not in ln]
    pick = errors[0] if errors else (lines[-1] if lines else "no error output")
    return _CONTEXT.sub("", pick).lstrip("- ")[:200]


def hw_decode_args() -> list[str]:
    """ffmpeg options before -i to decode the input on the GPU."""
    return ["-hwaccel", GPU_DECODE]


def hw_encode_device_args() -> list[str]:
    """ffmpeg options before -i that open the D3D12 device the GPU encoder uploads to."""
    return ["-init_hw_device", f"{HW_DEVICE}=gpu", "-filter_hw_device", "gpu"]


_PSNR = re.compile(r"PSNR y:\S+ u:\S+ v:\S+ average:(\S+)")


def psnr_db(tools: FFTools, a: Path | str, b: Path | str, *, a_lavfi: bool = False) -> float:
    """Average PSNR of b against a (inf when identical); raises ToolError when ffmpeg can't compare."""
    first: list[object] = ["-f", "lavfi", "-i", a] if a_lavfi else ["-i", a]
    proc = run_capture([
        tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "info", "-nostats",
        *first, "-i", b, "-lavfi", "[1:v][0:v]psnr", "-f", "null", "-",
    ], timeout=120)
    found = _PSNR.findall(proc.stderr)
    if proc.returncode != 0 or not found:
        raise ToolError(f"psnr failed: {error_line(proc.stderr)}", proc.returncode, proc.stderr[-2000:])
    return float("inf") if found[-1] == "inf" else float(found[-1])


def pictures_ok(tools: FFTools, pairs: list[tuple[Path, Path]]) -> tuple[bool, str]:
    """True when every GPU still is close enough to its full-tier still (same slot)."""
    for ref, test in pairs:
        db = psnr_db(tools, ref, test)
        if db < MIN_PSNR_DB:
            return False, f"GPU picture check failed on {test.name}: {db:.1f} dB (minimum {MIN_PSNR_DB:g})"
    return True, ""


class DecodeCheck:
    """Per-codec GPU decode decision for one run; a codec is checked once, on its first clip."""

    def __init__(self) -> None:
        self.results: dict[str, tuple[bool, str]] = {}

    def allowed(self, tools: FFTools, src: Path, stream_index: int, codec: str, bit_depth: int) -> bool:
        key = f"{codec}:{'10bit' if bit_depth > 8 else '8bit'}"
        if key not in self.results:
            self.results[key] = _check_decode(tools, src, stream_index, bit_depth)
        return self.results[key][0]

    def summary(self) -> dict[str, str]:
        """{"h264:8bit": "gpu", "av1:10bit": "cpu: <reason>"} for run records."""
        return {k: ("gpu" if ok else f"cpu: {why}") for k, (ok, why) in sorted(self.results.items())}


def _frame_hashes(tools: FFTools, src: Path, stream_index: int, pix_fmt: str, hw: bool) -> list[str]:
    proc = run_capture([
        tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
        *(hw_decode_args() if hw else []),
        "-protocol_whitelist", "file", "-i", src, "-map", f"0:{stream_index}",
        "-frames:v", str(DECODE_CHECK_FRAMES), "-pix_fmt", pix_fmt, "-f", "framemd5", "-",
    ], timeout=120)
    if proc.returncode != 0:
        raise ToolError(error_line(proc.stderr), proc.returncode, proc.stderr[-2000:])
    return [ln.rsplit(",", 1)[-1].strip() for ln in proc.stdout.splitlines() if ln and not ln.startswith("#")]


def _check_decode(tools: FFTools, src: Path, stream_index: int, bit_depth: int) -> tuple[bool, str]:
    """GPU decode is allowed only when its first frames match CPU decode bit for bit."""
    if os.name != "nt":
        return False, "GPU decoding is only used on Windows"
    pix_fmt = "yuv420p10le" if bit_depth > 8 else "yuv420p"
    try:
        cpu = _frame_hashes(tools, src, stream_index, pix_fmt, hw=False)
        hw = _frame_hashes(tools, src, stream_index, pix_fmt, hw=True)
    except ToolError as exc:
        return False, first_line(str(exc)) or "decode check failed"
    if not cpu:
        return False, "no frames decoded"
    if hw != cpu:
        return False, "GPU decode differs from CPU decode"
    return True, ""


def encode_args(qp: int, width: int = 0, height: int = 0, fps: float = 0.0) -> list[str]:
    """Codec options for a GPU encode at constant QP (frames arrive through GPU_FILTERS)."""
    args = ["-c:v", GPU_ENCODER, "-rc_mode", "CQP", "-qp", str(qp)]
    macroblocks = -(-width // 16) * -(-height // 16)
    if macroblocks * fps > LEVEL_52_MBPS:
        args += ["-level", "5.2"]
    return args


def _scrub(text: str, probe_dir: Path) -> str:
    """Drop local paths (probe folder, user profile) from a reason that goes into the pack."""
    for path, label in ((str(probe_dir), "<probe>"), (os.environ.get("USERPROFILE", ""), "%USERPROFILE%")):
        if path:
            for variant in {path, path.replace("\\", "/")}:
                text = re.sub(re.escape(variant), lambda _m, label=label: label, text, flags=re.IGNORECASE)
    return text


def detect_gpu(tools: FFTools, probe_dir: Path) -> GpuStatus:
    """Encode a short test clip on the GPU into probe_dir (deleted after) and check it; never raises."""
    if os.name != "nt":
        return GpuStatus(False, reason="GPU encoding is only used on Windows")
    probe_dir = Path(probe_dir)
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        status = _probe(tools, probe_dir)
    except OSError as exc:
        status = GpuStatus(False, reason=f"could not run the test encode: {exc.strerror or exc}")
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    return GpuStatus(status.available, status.adapter, _scrub(status.reason, probe_dir))


def _probe(tools: FFTools, tmp: Path) -> GpuStatus:
    """Encode PROBE_FRAMES test frames on the GPU, then check the file has exactly that many."""
    out = tmp / "probe.mp4"
    args: list[object] = [
        tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "verbose", "-nostats", "-y",
        "-init_hw_device", f"{HW_DEVICE}=gpu", "-filter_hw_device", "gpu",
        "-f", "lavfi", "-i", _PROBE_SOURCE,
        "-vf", ",".join(GPU_FILTERS), *encode_args(51), out,
    ]
    try:
        proc = run_capture(args, timeout=PROBE_TIMEOUT_S)
    except ToolError as exc:
        return GpuStatus(False, reason=str(exc))
    adapter = adapter_name(proc.stderr)
    if proc.returncode != 0:
        return GpuStatus(False, adapter, error_line(proc.stderr))
    try:
        check = run_capture([
            tools.ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets",
            "-show_entries", "stream=codec_name,nb_read_packets", "-of", "csv=p=0", out,
        ])
    except ToolError as exc:
        return GpuStatus(False, adapter, str(exc))
    if check.stdout.strip() != f"h264,{PROBE_FRAMES}":
        got = check.stdout.strip() or error_line(check.stderr)
        return GpuStatus(False, adapter, f"test encode came out wrong ({got})")
    try:
        db = psnr_db(tools, _PROBE_SOURCE, out, a_lavfi=True)
    except ToolError as exc:
        return GpuStatus(False, adapter, f"test encode picture check failed: {first_line(str(exc))}")
    if db < MIN_PSNR_DB:
        return GpuStatus(False, adapter, f"test encode picture is wrong ({db:.1f} dB, minimum {MIN_PSNR_DB:g})")
    return GpuStatus(True, adapter)
