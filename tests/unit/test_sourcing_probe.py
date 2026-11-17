"""ffprobe JSON interpretation (friend-pack spec §5.2)."""

import copy

import pytest

from game_frame_classifier.sourcing.probe import ProbeError, choose_stream, info_from_probe


def sample():
    return {
        "streams": [
            {
                "index": 0, "codec_type": "video", "codec_name": "h264", "profile": "High",
                "width": 1920, "height": 1080, "pix_fmt": "yuv420p",
                "avg_frame_rate": "60/1", "r_frame_rate": "60/1", "sample_aspect_ratio": "1:1",
                "color_transfer": "bt709", "disposition": {"attached_pic": 0},
            },
            {"index": 1, "codec_type": "audio", "codec_name": "aac"},
            {
                "index": 2, "codec_type": "video", "codec_name": "mjpeg", "width": 3000, "height": 3000,
                "avg_frame_rate": "0/0", "r_frame_rate": "90000/1", "disposition": {"attached_pic": 1},
            },
        ],
        "format": {
            "filename": "<path>/clip.mp4",
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "123.5",
            "start_time": "0.000000",
            "bit_rate": "16200000",
            "tags": {"creation_time": "2026-11-02T21:14:08.000000Z", "encoder": "Lavf61.7.100"},
        },
    }


def with_stream(**changes):
    data = sample()
    data["streams"][0].update(changes)
    return data


def test_basic_fields_and_cover_art_ignored():
    data = sample()
    original = copy.deepcopy(data)
    info = info_from_probe(data)
    assert info.stream_index == 0
    assert (info.width, info.height) == (1920, 1080)
    assert info.nominal_fps == 60 and not info.vfr and not info.hdr and not info.even_crop
    assert info.audio_streams == 1 and info.bitrate_bps == 16200000 and info.bit_depth == 8
    assert info.encoder_tag == "Lavf61.7.100"
    assert info.container_creation_raw == "2026-11-02T21:14:08.000000Z"
    assert "filename" not in info.raw["format"]
    assert data == original


def test_hdr_detected():
    assert info_from_probe(with_stream(color_transfer="smpte2084")).hdr


def test_odd_dimensions_flag_even_crop():
    assert info_from_probe(with_stream(width=1365)).even_crop


def test_vfr_and_nominal_fps():
    info = info_from_probe(with_stream(avg_frame_rate="1095/23"))
    assert info.vfr
    assert info.nominal_fps == pytest.approx(1095 / 23)


def test_nominal_fps_fallback_to_60():
    assert info_from_probe(with_stream(avg_frame_rate="0/0", r_frame_rate="1000/1")).nominal_fps == 60.0


def test_ten_bit_depth():
    assert info_from_probe(with_stream(pix_fmt="yuv420p10le")).bit_depth == 10


def test_rotation_from_side_data():
    assert info_from_probe(with_stream(side_data_list=[{"rotation": -90}])).rotation == -90


def test_no_video_stream():
    data = sample()
    data["streams"] = data["streams"][1:]
    with pytest.raises(ProbeError) as excinfo:
        info_from_probe(data)
    assert excinfo.value.detail == "no_video"


def test_choose_stream_tie_takes_lowest_index():
    streams = [
        {"index": 3, "codec_type": "video", "width": 640, "height": 360},
        {"index": 1, "codec_type": "video", "width": 640, "height": 360},
    ]
    assert choose_stream(streams)["index"] == 1
