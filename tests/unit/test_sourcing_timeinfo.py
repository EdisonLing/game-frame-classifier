"""Recording-time evidence (Frame Export Kit spec §5.2b)."""

import os
from datetime import datetime, timezone

import pytest

from game_frame_classifier.sourcing.timeinfo import (
    iso_utc,
    local_to_utc,
    parse_container_time,
    parse_filename_time,
    recording_times,
)

NOW = datetime(2026, 11, 16, 12, 0, 0)
NOW_UTC = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)
MTIME = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
NVIDIA_NAME = "VALORANT/VALORANT 2026.09.29 - 20.00.00.mp4"


@pytest.mark.parametrize(
    "relpath,expected",
    [
        ("VALORANT/VALORANT 2026.11.02 - 21.14.08.03.DVR.mp4", datetime(2026, 11, 2, 21, 14, 8)),
        ("2026-11-02 21-14-08.mkv", datetime(2026, 11, 2, 21, 14, 8)),
        ("Replay 2026-11-02_21-14-08.mp4", datetime(2026, 11, 2, 21, 14, 8)),
        ("VALORANT_replay_2026.11.07-23.36.mp4", datetime(2026, 11, 7, 23, 36, 0)),
        ("clip_730_20261102_211408.mp4", datetime(2026, 11, 2, 21, 14, 8)),
        ("Medal_20261102-211408.mp4", datetime(2026, 11, 2, 21, 14, 8)),
        ("2025-01-01/VALORANT 2026.11.02 - 21.14.08.mp4", datetime(2026, 11, 2, 21, 14, 8)),
    ],
)
def test_filename_patterns(relpath, expected):
    found = parse_filename_time(relpath, NOW)
    assert found is not None
    assert found.value == expected
    assert found.has_time


def test_folder_date_only():
    found = parse_filename_time("clips/2026-11-02/gameplay.mp4", NOW)
    assert found is not None
    assert found.value == datetime(2026, 11, 2)
    assert not found.has_time


@pytest.mark.parametrize(
    "relpath",
    ["2026-13-45 10-00-00.mp4", "2031-01-01 10-00-00.mp4", "2009-05-01 10-00-00.mp4", "gameplay.mp4"],
)
def test_filename_rejects(relpath):
    assert parse_filename_time(relpath, NOW) is None


def test_container_time_utc():
    assert parse_container_time("2026-11-02T21:14:08.000000Z", NOW_UTC) == datetime(
        2026, 11, 2, 21, 14, 8, tzinfo=timezone.utc
    )


def test_container_time_with_offset():
    assert parse_container_time("2026-11-02 21:14:08+02:00", NOW_UTC) == datetime(
        2026, 11, 2, 19, 14, 8, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    "raw",
    ["", "1970-01-01T00:00:00.000000Z", "1904-01-01 00:00:00", "2031-01-01T00:00:00Z", "garbage"],
)
def test_container_time_rejects(raw):
    assert parse_container_time(raw, NOW_UTC) is None


@pytest.mark.parametrize("value", [datetime(2026, 1, 15, 12, 0), datetime(2026, 7, 15, 12, 0)])
def test_local_to_utc_round_trip_across_dst(value):
    assert local_to_utc(value).astimezone().replace(tzinfo=None) == value


def _clip(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    ts = MTIME.timestamp()
    os.utime(path, (ts, ts))
    return path


def test_recording_time_prefers_container(tmp_path):
    t = recording_times(_clip(tmp_path), NVIDIA_NAME, "2026-09-30T08:00:00.000000Z", 60.0, NOW)
    assert t.recorded_start_source == "container"
    assert t.recorded_start_utc == "2026-09-30T08:00:00Z"
    assert t.container_creation_utc == "2026-09-30T08:00:00Z"
    assert t.filename_datetime_local.startswith("2026-09-29T20:00:00")
    assert t.file_mtime_utc == "2026-10-01T12:00:00Z"


def test_recording_time_falls_back_to_filename(tmp_path):
    t = recording_times(_clip(tmp_path), NVIDIA_NAME, "", 60.0, NOW)
    assert t.recorded_start_source == "filename"
    assert t.recorded_start_utc == iso_utc(local_to_utc(datetime(2026, 9, 29, 20, 0, 0)))


def test_recording_time_falls_back_to_mtime(tmp_path):
    t = recording_times(_clip(tmp_path), "clips/2026-09-28/gameplay.mp4", "1970-01-01T00:00:00.000000Z", 60.0, NOW)
    assert t.recorded_start_source == "mtime"
    assert t.recorded_start_utc == "2026-10-01T11:59:00Z"
    assert t.filename_datetime_local == "2026-09-28"
    assert t.container_creation_utc == ""
