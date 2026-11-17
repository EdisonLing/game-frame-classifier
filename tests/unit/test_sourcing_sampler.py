"""bucket_v1 sampler math, showinfo parsing and tier pairing."""

import pytest

from game_frame_classifier.sourcing.sampler import (
    bucket_of,
    expected_slots,
    offset_s,
    pair_tiers,
    parse_showinfo,
    select_expr,
)

OFF60 = offset_s(60)
TOL60 = 0.5 / 60


def test_offset_is_half_a_frame_and_clamped():
    assert OFF60 == 0.008333
    assert offset_s(1000) == 0.002
    assert offset_s(5) == 0.05


def test_select_expr_text():
    assert select_expr(5, 0.008333) == (
        "gte(t\\,0)*(isnan(prev_selected_t)"
        "+gt(floor((t+0.008333)/5)\\,floor((prev_selected_t+0.008333)/5)))"
    )


@pytest.mark.parametrize(
    "pts,bucket",
    [(0.0, 0), (4.983333, 0), (4.995, 1), (5.0, 1), (10.916667, 2), (-0.001, 0)],
)
def test_bucket_of(pts, bucket):
    assert bucket_of(pts, 5, OFF60) == bucket


@pytest.mark.parametrize(
    "duration,fps,expected",
    [(12.0, 30, 3), (10.0, 30, 2), (21.0, 30, 5), (0.5, 30, 1), (0.0, 30, 0)],
)
def test_expected_slots(duration, fps, expected):
    assert expected_slots(duration, 5, fps) == expected


SAMPLE = (
    "[Parsed_showinfo_1 @ 00000266383de600] n:   0 pts:      0 pts_time:0       "
    "duration:      1 duration_time:0.0333333 fmt:yuvj420p\n"
    "[Parsed_showinfo_1 @ 00000266383de600]   color_range:pc color_space:bt709\n"
    "frame=    2 fps=0.0 q=2.0 size=N/A time=00:00:05.01\n"
    "[Parsed_showinfo_3 @ 00000266383de600] n:   1 pts:    150 pts_time:5.016667 duration:      1\n"
)


def test_parse_showinfo():
    assert parse_showinfo(SAMPLE) == [0.0, 5.016667]


def test_identical_tiers_pair_by_order():
    p = pair_tiers({"full": [0.0, 5.0, 10.0], "crf45": [0.0, 5.0, 10.0]}, 5, OFF60, TOL60)
    assert p.mode == "index"
    assert [s.bucket for s in p.slots] == [0, 1, 2]
    assert p.unpaired_dropped == 0
    assert p.max_align_err_s == 0.0


def test_small_rounding_still_pairs_by_order():
    p = pair_tiers({"full": [0.0, 10.916667], "crf45": [0.0, 10.917]}, 5, OFF60, TOL60)
    assert p.mode == "index"
    assert p.max_align_err_s == pytest.approx(0.000333, abs=1e-6)


def test_missing_bucket_falls_back_to_bucket_pairing():
    p = pair_tiers({"full": [0.0, 5.0, 10.0, 15.0], "crf45": [0.0, 5.0, 15.0]}, 5, OFF60, TOL60)
    assert p.mode == "bucket"
    assert [s.bucket for s in p.slots] == [0, 1, 3]
    assert p.unpaired_dropped == 1
    assert p.slots[2].indices == {"full": 3, "crf45": 2}


def test_duplicate_bucket_is_dropped():
    p = pair_tiers({"full": [0.0, 0.5]}, 5, OFF60, TOL60)
    assert [s.bucket for s in p.slots] == [0]
    assert p.unpaired_dropped == 1
