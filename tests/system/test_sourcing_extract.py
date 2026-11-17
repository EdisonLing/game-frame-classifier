"""Extraction on synthetic clips: CFR, VFR with offset, odd size, HDR, AV1, cover art, compact."""

import json
import shutil
from pathlib import Path

import pytest

from game_frame_classifier.sourcing import extract as extract_mod
from game_frame_classifier.sourcing import gpu
from game_frame_classifier.sourcing.derive import derive_dir
from game_frame_classifier.sourcing.extract import extract_clip
from game_frame_classifier.sourcing.ffbin import find_tools
from game_frame_classifier.sourcing.hashing import jpeg_size, sha256_file
from game_frame_classifier.sourcing.probe import probe_file
from game_frame_classifier.sourcing.recipe import recipe_from_dict
from tests.helpers.ffmpeg_fixtures import (
    encoder_available,
    make_attached_pic_video,
    make_hdr_pq_video,
    make_testsrc_video,
    make_vfr_offset_video,
    requires_ffmpeg,
    requires_gpu,
)

ROOT = Path(__file__).resolve().parents[2]
KEY = "c0123456789ab"


def recipe(**overrides):
    data = json.loads((ROOT / "config" / "recipe.json").read_text(encoding="utf-8"))
    return recipe_from_dict(data, overrides)


def run_extract(base: Path, video: Path, r, use_gpu: bool = False):
    tools = find_tools()
    info = probe_file(video, tools)
    pack = base / "pack"
    result = extract_clip(tools, video, info, r, KEY, base / "stage", pack / "frames", pack, use_gpu=use_gpu)
    return info, result, pack


@requires_ffmpeg
def test_cfr_clip_two_tiers(tmp_path):
    video = make_testsrc_video(tmp_path / "cfr.mp4", duration_s=12)
    _, res, pack = run_extract(tmp_path, video, recipe())
    assert (res.slots, res.expected_slots, res.unpaired_dropped) == (3, 3, 0)
    assert res.max_align_err_s <= 0.001
    assert sorted({i.bucket for i in res.images}) == [0, 1, 2]
    assert {i.tier for i in res.images} == {"full", "crf45"}
    assert res.x264_core.startswith("x264 - core")
    assert (res.low_encoder, res.gpu_fallback) == ("libx264", "")
    assert {(i.tier, i.encoder, i.encoder_rc) for i in res.images} == {("full", "", ""), ("crf45", "libx264", "crf45")}
    for img in res.images:
        path = pack / img.rel_path
        assert path.name == f"{KEY}_{img.tier}_b{img.bucket:06d}.jpg"
        assert jpeg_size(path) == (img.width, img.height) == (640, 360)
        assert sha256_file(path) == img.sha256 and path.stat().st_size == img.bytes
        assert img.slot_id == f"{KEY}:b{img.bucket:06d}" and img.image_id == f"{img.slot_id}:{img.tier}"
    assert not (tmp_path / "stage").exists()


@requires_ffmpeg
def test_vfr_clip_with_gap_and_start_offset(tmp_path):
    video = make_vfr_offset_video(tmp_path / "vfr.mp4")
    info, res, _ = run_extract(tmp_path, video, recipe())
    assert info.start_time_s > 2.0
    assert res.slots == 5
    assert res.max_align_err_s <= 0.5 / info.nominal_fps
    full = {i.bucket: i.pts_time_s for i in res.images if i.tier == "full"}
    assert sorted(full) == [0, 1, 2, 3, 4]
    assert full[2] == pytest.approx(10.916667, abs=0.002)
    assert full[4] == pytest.approx(20.016667, abs=0.002)


@requires_ffmpeg
def test_odd_dimensions_are_even_cropped(tmp_path):
    video = make_testsrc_video(
        tmp_path / "odd.mkv", duration_s=6, width=641, height=361,
        pix_fmt="yuv444p", codec_args=("-c:v", "ffv1"),
    )
    info, res, _ = run_extract(tmp_path, video, recipe())
    assert info.even_crop and res.even_cropped and res.slots == 2
    assert {(i.width, i.height) for i in res.images} == {(640, 360)}


@requires_ffmpeg
@pytest.mark.skipif(not encoder_available("libx265"), reason="ffmpeg has no libx265")
def test_hdr_clip_is_tonemapped(tmp_path):
    video = make_hdr_pq_video(tmp_path / "hdr.mp4")
    info, res, _ = run_extract(tmp_path, video, recipe())
    assert info.hdr and res.tonemapped and res.slots == 2


@requires_ffmpeg
@pytest.mark.skipif(not encoder_available("libsvtav1"), reason="ffmpeg has no libsvtav1")
def test_av1_clip(tmp_path):
    video = make_testsrc_video(tmp_path / "av1.mp4", duration_s=12, codec_args=("-c:v", "libsvtav1", "-preset", "12"))
    info, res, _ = run_extract(tmp_path, video, recipe())
    assert info.video_codec == "av1" and res.slots == 3


@requires_ffmpeg
def test_cover_art_stream_is_ignored(tmp_path):
    video = make_attached_pic_video(tmp_path / "cover.mp4", tmp_path)
    info, res, _ = run_extract(tmp_path, video, recipe())
    assert info.stream_index == 0 and (info.width, info.height) == (640, 360)
    assert res.slots == 2


@requires_ffmpeg
def test_compact_mode_matches_pipeline_derive(tmp_path):
    video = make_testsrc_video(tmp_path / "v.mp4", duration_s=12, width=1280, height=720)
    _, native, native_pack = run_extract(tmp_path / "n", video, recipe())
    _, compact, _ = run_extract(tmp_path / "c", video, recipe(frame_mode="compact"))
    assert {(i.width, i.height) for i in compact.images} == {(256, 144)}
    for tier in ("full", "crf45"):
        seq = tmp_path / f"seq_{tier}"
        seq.mkdir()
        natives = sorted((i for i in native.images if i.tier == tier), key=lambda i: i.bucket)
        for k, img in enumerate(natives):
            shutil.copyfile(native_pack / img.rel_path, seq / f"{k:06d}.jpg")
        derive_dir(find_tools(), seq, tmp_path / f"derived_{tier}", recipe())
        compacts = sorted((i for i in compact.images if i.tier == tier), key=lambda i: i.bucket)
        derived = [sha256_file(tmp_path / f"derived_{tier}" / f"{k:06d}.jpg") for k in range(len(compacts))]
        assert derived == [i.sha256 for i in compacts]


@requires_gpu
def test_gpu_encodes_the_crf_tier_at_constant_qp(tmp_path):
    video = make_vfr_offset_video(tmp_path / "vfr.mp4")
    _, cpu, _ = run_extract(tmp_path / "cpu", video, recipe())
    info, res, pack = run_extract(tmp_path / "gpu", video, recipe(), use_gpu=True)
    assert (res.low_encoder, res.gpu_fallback, res.x264_core) == (gpu.GPU_ENCODER, "", "")
    assert {(i.tier, i.encoder, i.encoder_rc) for i in res.images} == {
        ("full", "", ""), ("crf45", gpu.GPU_ENCODER, "qp51"),
    }
    assert (res.slots, res.unpaired_dropped) == (cpu.slots, 0)
    assert [i.pts_time_s for i in res.images] == [i.pts_time_s for i in cpu.images]
    full = {i.sha256 for i in res.images if i.tier == "full"}
    assert full == {i.sha256 for i in cpu.images if i.tier == "full"}  # full tier never touches the GPU
    assert not (tmp_path / "gpu" / "stage").exists()


@requires_ffmpeg
def test_gpu_failure_redoes_the_tier_on_the_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu, "GPU_ENCODER", "h264_no_such_encoder")
    progress: list[float] = []
    tools = find_tools()
    video = make_testsrc_video(tmp_path / "cfr.mp4", duration_s=12)
    info = probe_file(video, tools)
    pack = tmp_path / "pack"
    res = extract_clip(
        tools, video, info, recipe(), KEY, tmp_path / "stage", pack / "frames", pack, progress.append, use_gpu=True,
    )
    assert res.low_encoder == "libx264" and res.x264_core.startswith("x264 - core")
    assert res.gpu_fallback  # the reason is recorded (wording depends on the machine)
    assert (res.slots, res.unpaired_dropped) == (3, 0)
    assert {i.encoder_rc for i in res.images if i.tier == "crf45"} == {"crf45"}
    assert progress[-1] == 1.0 and not (tmp_path / "stage").exists()


@requires_gpu
def test_gpu_output_that_does_not_line_up_is_redone_on_the_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(extract_mod, "_lines_up", lambda *a: False)
    video = make_testsrc_video(tmp_path / "cfr.mp4", duration_s=12)
    _, res, _ = run_extract(tmp_path, video, recipe(), use_gpu=True)
    assert res.low_encoder == "libx264"
    assert "don't line up" in res.gpu_fallback
    assert res.slots == 3


@requires_gpu
def test_unsupported_resolution_falls_back(tmp_path):
    video = make_testsrc_video(tmp_path / "wide.mp4", duration_s=6, width=8192, height=1080)
    _, res, _ = run_extract(tmp_path, video, recipe(), use_gpu=True)
    assert res.low_encoder == "libx264" and res.gpu_fallback
    assert res.slots == 2
