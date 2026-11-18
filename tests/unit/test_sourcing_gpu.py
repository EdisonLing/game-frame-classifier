"""GPU encode helpers: adapter name, error summaries, level pinning, path scrubbing (D28)."""

from pathlib import Path

from game_frame_classifier.sourcing import gpu


def test_adapter_name_from_verbose_log():
    log = "[D3D12VA @ 00000202d90e1b40] Using device 1002:7550 (AMD Radeon RX 9070 XT).\nother"
    assert gpu.adapter_name(log) == "AMD Radeon RX 9070 XT"
    assert gpu.adapter_name("nothing here") == ""


def test_error_line_joins_the_encoders_own_messages():
    log = "\n".join([
        "[h264 @ 0001] Failed setup for format d3d11: hwaccel initialisation returned error.",
        "[h264_d3d12va @ 0002] Driver does not support requested features. ValidationFlags: 0x200",
        "[h264_d3d12va @ 0002]   - Resolution not supported",
        "[vost#0:0/h264_d3d12va @ 0003] [enc:h264_d3d12va @ 0004] Error while opening encoder",
        "Exiting with exit code -22",
    ])
    assert gpu.error_line(log) == (
        "Driver does not support requested features. ValidationFlags: 0x200 / Resolution not supported"
    )


def test_error_line_skips_decode_fallback_notices():
    log = "\n".join([
        "[h264 @ 01] Failed setup for format d3d11: hwaccel initialisation returned error.",
        "[vost#0:0 @ 02] Unknown encoder 'h264_nope'",
        "Error opening output files: Encoder not found",
    ])
    assert gpu.error_line(log) == "Unknown encoder 'h264_nope'"
    assert gpu.error_line("") == "no error output"


def test_level_pinned_only_above_level_52():
    assert "-level" not in gpu.encode_args(51, 1920, 1080, 60)
    assert "-level" not in gpu.encode_args(51, 3840, 2160, 60)
    assert gpu.encode_args(51, 3840, 2160, 120)[-2:] == ["-level", "5.2"]
    assert gpu.encode_args(51, 3440, 1440, 144)[-2:] == ["-level", "5.2"]
    assert gpu.encode_args(51)[:8] == [
        "-c:v", gpu.GPU_ENCODER, "-rc_mode", "CQP", "-qp", "51", "-bf", "0",
    ]


def test_encode_args_disables_b_frames():
    args = gpu.encode_args(51, 1280, 720, 30)
    assert args[args.index("-bf") + 1] == "0"


def test_scrub_removes_probe_and_profile_paths(monkeypatch):
    monkeypatch.setenv("USERPROFILE", r"C:\Users\Someone")
    probe = Path(r"D:\tools\GFC\output\_work\gpu_probe_abc")
    text = r"D:\tools\GFC\output\_work\gpu_probe_abc\probe.mp4: failed; c:/users/someone/x"
    assert gpu._scrub(text, probe) == r"<probe>\probe.mp4: failed; %USERPROFILE%/x"
