"""Vendor-neutral GPU video encode via Direct3D 12 (D28), with a startup self-test.

D3D12 video encode works on NVIDIA, AMD and Intel through the normal graphics
driver (Windows 11). The kit tries it once at startup by encoding a short test
clip and checking the result; anything unexpected means "use libx264 instead".
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
# The encode input is decoded on the GPU as well (bit-exact, and ffmpeg falls back to
# software decode by itself when the GPU can't decode a codec). Keeps the CPU mostly idle.
GPU_DECODE = "d3d11va"
# Appended to the -vf chain: CPU frames (after tone-map / crop) are uploaded to the GPU.
GPU_FILTERS = ("format=nv12", "hwupload")
# H.264 level 5.2 allows 2,073,600 macroblocks per second (e.g. 4K60). Above that no level
# fits, and drivers refuse to open the encoder (4K120, 3440x1440 at 144 fps), so the level is
# pinned to 5.2. The level is only a label for decoders; it doesn't change constant-QP output.
LEVEL_52_MBPS = 2_073_600
PROBE_FRAMES = 30
PROBE_TIMEOUT_S = 90
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


def hw_input_args() -> list[str]:
    """ffmpeg options before -i for a GPU encode."""
    return ["-hwaccel", GPU_DECODE, "-init_hw_device", f"{HW_DEVICE}=gpu", "-filter_hw_device", "gpu"]


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
        "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30:d={PROBE_FRAMES / 30:g}",
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
    return GpuStatus(True, adapter)
