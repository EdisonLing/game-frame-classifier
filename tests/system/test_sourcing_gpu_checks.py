"""Separate GPU decode check, GPU picture check and the ffmpeg stall timeout (D28)."""

import os
import time
from pathlib import Path

import pytest

from game_frame_classifier.sourcing import gpu
from game_frame_classifier.sourcing.extract import extract_clip
from game_frame_classifier.sourcing.ffbin import ToolError, find_tools, run_ffmpeg
from game_frame_classifier.sourcing.probe import probe_file
from tests.helpers.ffmpeg_fixtures import make_testsrc_video, requires_ffmpeg, requires_gpu
from tests.system.test_sourcing_extract import KEY, recipe

windows_only = pytest.mark.skipif(os.name != "nt", reason="GPU decode is only used on Windows")


def _still(tools, path: Path, source: str) -> Path:
    import subprocess

    subprocess.run(
        [str(tools.ffmpeg), "-v", "error", "-y", "-f", "lavfi", "-i", source, "-frames:v", "1", str(path)],
        check=True,
    )
    return path


@requires_ffmpeg
def test_stall_timeout_stops_ffmpeg_that_makes_no_progress(tmp_path):
    tools = find_tools()
    # Real-time input whose only output frame comes after 60 s: no progress for the first minute.
    args = [
        tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:1",
        "-re", "-f", "lavfi", "-i", "testsrc=s=64x36:r=5:d=120",
        "-vf", "select='gte(t,60)'", "-f", "null", "-",
    ]
    t0 = time.monotonic()
    with pytest.raises(ToolError, match="no progress"):
        run_ffmpeg(args, stderr_path=tmp_path / "err.log", stall_s=2)
    assert time.monotonic() - t0 < 20


@requires_ffmpeg
def test_stall_timeout_leaves_a_progressing_ffmpeg_alone(tmp_path):
    tools = find_tools()
    args = [
        tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:1",
        "-re", "-f", "lavfi", "-i", "testsrc=s=64x36:r=10:d=4", "-f", "null", "-",
    ]
    run_ffmpeg(args, stderr_path=tmp_path / "err.log", stall_s=2)


@requires_ffmpeg
def test_picture_check_accepts_the_same_picture_and_rejects_a_wrong_one(tmp_path):
    tools = find_tools()
    a = _still(tools, tmp_path / "a.jpg", "testsrc2=s=320x180")
    green = _still(tools, tmp_path / "green.jpg", "color=c=green:s=320x180")
    assert gpu.psnr_db(tools, a, a) == float("inf")
    assert gpu.pictures_ok(tools, [(a, a)]) == (True, "")
    ok, why = gpu.pictures_ok(tools, [(a, a), (a, green)])
    assert not ok and "green.jpg" in why


def test_decode_check_runs_once_per_codec_and_bit_depth(monkeypatch):
    calls = []

    def fake(tools, src, stream_index, bit_depth, fps=30.0):
        calls.append((src, bit_depth))
        return (src.name != "bad.mp4", "" if src.name != "bad.mp4" else "differs")

    monkeypatch.setattr(gpu, "_check_decode", fake)
    check = gpu.DecodeCheck()
    assert check.allowed(None, Path("a.mp4"), 0, "h264", 8, 1920, 1080)
    assert check.allowed(None, Path("b.mp4"), 0, "h264", 8, 1920, 1080)
    assert not check.allowed(None, Path("bad.mp4"), 0, "av1", 10, 3840, 2160)
    assert len(calls) == 2
    assert check.summary() == {"av1:10bit:3840x2160": "cpu: differs", "h264:8bit:1920x1080": "gpu"}


@requires_ffmpeg
@windows_only
def test_gpu_decode_gives_identical_full_tier_images(tmp_path, monkeypatch):
    """The training data must not depend on whether a PC could decode on the GPU."""
    monkeypatch.setattr(gpu, "DECODE_MIN_SPEEDUP", 0.0)  # use GPU decode even where the CPU is faster
    tools = find_tools()
    video = make_testsrc_video(tmp_path / "clip.mp4", duration_s=12)
    info = probe_file(video, tools)
    r = recipe()
    hashes = {}
    for name, decode in (("cpu", None), ("gpu", gpu.DecodeCheck())):
        base = tmp_path / name
        res = extract_clip(tools, video, info, r, KEY, base / "stage", base / "frames", base, decode=decode)
        hashes[name] = sorted((i.tier, i.bucket, i.sha256) for i in res.images)
        if decode is not None and "gpu" not in decode.summary().values():
            pytest.skip(f"GPU decode not available here: {decode.summary()}")
        assert res.decoder == (gpu.GPU_DECODE if decode is not None else "cpu")
    assert hashes["gpu"] == hashes["cpu"]


@requires_ffmpeg
@requires_gpu
def test_gpu_picture_failure_redoes_the_tier_on_the_cpu(tmp_path, monkeypatch):
    tools = find_tools()
    video = make_testsrc_video(tmp_path / "clip.mp4", duration_s=12)
    info = probe_file(video, tools)
    monkeypatch.setattr(gpu, "pictures_ok", lambda tools, pairs: (False, "GPU picture check failed on x.jpg"))
    res = extract_clip(
        tools, video, info, recipe(), KEY, tmp_path / "stage", tmp_path / "frames", tmp_path,
        use_gpu=True, decode=gpu.DecodeCheck(),
    )
    assert res.low_encoder == "libx264"
    assert "picture check" in res.gpu_fallback
    assert {(i.tier, i.encoder) for i in res.images} == {("full", ""), ("crf45", "libx264")}


@requires_ffmpeg
@requires_gpu
def test_gpu_tier_passes_the_picture_check_on_real_content(tmp_path):
    tools = find_tools()
    video = make_testsrc_video(tmp_path / "clip.mp4", duration_s=12)
    info = probe_file(video, tools)
    res = extract_clip(
        tools, video, info, recipe(), KEY, tmp_path / "stage", tmp_path / "frames", tmp_path,
        use_gpu=True, decode=gpu.DecodeCheck(),
    )
    assert (res.low_encoder, res.gpu_fallback) == (gpu.GPU_ENCODER, "")


@requires_ffmpeg
@requires_gpu
def test_self_test_rejects_a_wrong_picture(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu, "psnr_db", lambda *a, **k: 5.0)
    status = gpu.detect_gpu(find_tools(), tmp_path / "probe")
    assert not status.available and "picture is wrong" in status.reason



@requires_ffmpeg
@windows_only
def test_decode_check_prefers_the_cpu_when_the_gpu_is_not_faster(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu, "DECODE_MIN_SPEEDUP", 1000.0)
    tools = find_tools()
    video = make_testsrc_video(tmp_path / "clip.mp4", duration_s=3)
    ok, why = gpu._check_decode(tools, video, 0, 8)
    assert not ok and ("faster" in why or "differs" in why or "only used" in why)
