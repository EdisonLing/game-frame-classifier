"""ffprobe a clip and pick its video stream (friend-pack spec §5.2)."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ffbin import FFTools, ToolError, run_capture

HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})


class ProbeError(RuntimeError):
    """Probe failed; `detail` is the clip status detail (unreadable / no_video)."""

    def __init__(self, detail: str, message: str = "") -> None:
        super().__init__(message or detail)
        self.detail = detail


@dataclass(frozen=True)
class ProbeInfo:
    stream_index: int
    duration_s: float
    start_time_s: float
    container: str
    video_codec: str
    profile: str
    pix_fmt: str
    bit_depth: int
    bitrate_bps: int | None
    encoder_tag: str
    width: int
    height: int
    sar: str
    rotation: int
    avg_fps: float
    r_fps: float
    nominal_fps: float
    vfr: bool
    color_range: str
    color_space: str
    color_transfer: str
    color_primaries: str
    hdr: bool
    even_crop: bool
    audio_streams: int
    container_creation_raw: str
    raw: dict[str, Any]


def _rate(text: Any) -> float:
    num, _, den = str(text).partition("/")
    try:
        n, d = float(num), float(den or 1)
    except ValueError:
        return 0.0
    return n / d if d else 0.0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def choose_stream(streams: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Largest non-cover-art video stream; lowest index on ties."""
    videos = [
        s for s in streams
        if s.get("codec_type") == "video"
        and int((s.get("disposition") or {}).get("attached_pic", 0)) != 1
        and int(s.get("width") or 0) > 0
        and int(s.get("height") or 0) > 0
    ]
    if not videos:
        return None
    return max(videos, key=lambda s: (int(s["width"]) * int(s["height"]), -int(s.get("index", 0))))


def _bit_depth(stream: dict[str, Any]) -> int:
    raw = str(stream.get("bits_per_raw_sample") or "")
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    pix = str(stream.get("pix_fmt") or "")
    for depth in (16, 14, 12, 10, 9):
        if f"p{depth}" in pix:
            return depth
    return 8


def _rotation(stream: dict[str, Any]) -> int:
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return int(round(_float(side["rotation"])))
    tag = (stream.get("tags") or {}).get("rotate")
    return int(round(_float(tag))) if tag is not None else 0


def info_from_probe(data: dict[str, Any]) -> ProbeInfo:
    """Build ProbeInfo from ffprobe JSON; the stored copy drops format.filename."""
    raw = copy.deepcopy(data)
    fmt = raw.get("format") or {}
    fmt.pop("filename", None)
    streams = raw.get("streams") or []
    stream = choose_stream(streams)
    if stream is None:
        raise ProbeError("no_video")
    avg = _rate(stream.get("avg_frame_rate"))
    r = _rate(stream.get("r_frame_rate"))
    nominal = avg if 10 <= avg <= 240 else (r if 10 <= r <= 240 else 60.0)
    tags = {str(k).lower(): v for k, v in (fmt.get("tags") or {}).items()}
    stream_tags = {str(k).lower(): v for k, v in (stream.get("tags") or {}).items()}
    bitrate = str(fmt.get("bit_rate") or "")
    width, height = int(stream["width"]), int(stream["height"])
    transfer = str(stream.get("color_transfer") or "")
    return ProbeInfo(
        stream_index=int(stream.get("index", 0)),
        duration_s=_float(fmt.get("duration")) or _float(stream.get("duration")),
        start_time_s=_float(fmt.get("start_time")),
        container=str(fmt.get("format_name") or ""),
        video_codec=str(stream.get("codec_name") or ""),
        profile=str(stream.get("profile") or ""),
        pix_fmt=str(stream.get("pix_fmt") or ""),
        bit_depth=_bit_depth(stream),
        bitrate_bps=int(bitrate) if bitrate.isdigit() else None,
        encoder_tag=str(tags.get("encoder") or stream_tags.get("encoder") or ""),
        width=width,
        height=height,
        sar=str(stream.get("sample_aspect_ratio") or "1:1"),
        rotation=_rotation(stream),
        avg_fps=avg,
        r_fps=r,
        nominal_fps=nominal,
        vfr=stream.get("avg_frame_rate") != stream.get("r_frame_rate"),
        color_range=str(stream.get("color_range") or ""),
        color_space=str(stream.get("color_space") or ""),
        color_transfer=transfer,
        color_primaries=str(stream.get("color_primaries") or ""),
        hdr=transfer in HDR_TRANSFERS,
        even_crop=width % 2 == 1 or height % 2 == 1,
        audio_streams=sum(1 for s in streams if s.get("codec_type") == "audio"),
        container_creation_raw=str(tags.get("creation_time") or ""),
        raw=raw,
    )


def probe_file(path: Path, tools: FFTools, timeout: float = 120) -> ProbeInfo:
    try:
        proc = run_capture(
            [tools.ffprobe, "-v", "error", "-protocol_whitelist", "file",
             "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", path],
            timeout=timeout,
        )
    except ToolError as exc:
        raise ProbeError("unreadable", str(exc)) from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ProbeError("unreadable", proc.stderr.strip()[-300:])
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        raise ProbeError("unreadable", "ffprobe output is not JSON") from exc
    if not isinstance(data, dict):
        raise ProbeError("unreadable", "ffprobe output is not an object")
    return info_from_probe(data)
