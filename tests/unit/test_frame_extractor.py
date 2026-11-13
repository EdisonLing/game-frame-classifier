"""Unit tests for frame extractor pure logic (no ffmpeg required)."""

from __future__ import annotations

import pytest

from game_frame_classifier.frame_extractor import (
    frame_filename,
    planned_timestamps,
)


@pytest.mark.parametrize(
    ("duration", "interval", "expected"),
    [
        (15.0, 5.0, [0.0, 5.0, 10.0]),
        (15.0, 5.0, [0.0, 5.0, 10.0]),  # no frame at exactly duration
        (10.0, 5.0, [0.0, 5.0]),
        (5.0, 5.0, [0.0]),
        (4.9, 5.0, [0.0]),
        (0.0, 5.0, []),
        (20.0, 5.0, [0.0, 5.0, 10.0, 15.0]),
        (11.0, 2.5, [0.0, 2.5, 5.0, 7.5, 10.0]),
    ],
)
def test_planned_timestamps(duration: float, interval: float, expected: list[float]) -> None:
    assert planned_timestamps(duration, interval) == expected


def test_planned_timestamps_rejects_bad_interval() -> None:
    with pytest.raises(ValueError):
        planned_timestamps(10.0, 0.0)
    with pytest.raises(ValueError):
        planned_timestamps(10.0, -1.0)


def test_frame_filename_is_deterministic_and_sortable() -> None:
    a = frame_filename("vid", 0, 0.0, "jpg")
    b = frame_filename("vid", 1, 5.0, "jpg")
    c = frame_filename("vid", 2, 10.0, "jpg")
    assert a == "vid_f00000_t00000000ms.jpg"
    assert b == "vid_f00001_t00005000ms.jpg"
    assert c == "vid_f00002_t00010000ms.jpg"
    assert sorted([c, a, b]) == [a, b, c]


def test_frame_filename_strips_dot_from_ext() -> None:
    assert frame_filename("x", 0, 0.0, ".png").endswith(".png")
