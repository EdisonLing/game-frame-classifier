"""Footage budget selection (spread_days_v1)."""

from datetime import datetime, timezone

from game_frame_classifier.sourcing.budget import Candidate, select_within_budget


def utc_day(value):
    return value.date()


def c(key, minutes, day, hour=12):
    return Candidate(key, minutes * 60.0, datetime(2026, 10, day, hour, tzinfo=timezone.utc))


def test_under_budget_takes_all_in_recording_order():
    assert select_within_budget([c("b", 30, 2), c("a", 30, 1)], 3600, utc_day) == (["a", "b"], [])


def test_zero_budget_takes_all():
    assert select_within_budget([c("a", 300, 1), c("b", 300, 2)], 0, utc_day) == (["a", "b"], [])


def test_round_robin_across_days():
    cands = [c("a1", 30, 1), c("a2", 30, 1, 13), c("a3", 30, 1, 14), c("b1", 30, 2), c("c1", 30, 3)]
    assert select_within_budget(cands, 90 * 60, utc_day) == (["a1", "b1", "c1"], ["a2", "a3"])


def test_skips_clip_that_does_not_fit_and_keeps_going():
    cands = [c("big", 100, 1), c("small", 20, 2), c("mid", 50, 3)]
    assert select_within_budget(cands, 75 * 60, utc_day) == (["small", "mid"], ["big"])


def test_every_clip_longer_than_budget_takes_shortest():
    assert select_within_budget([c("x", 300, 1), c("y", 200, 2)], 180 * 60, utc_day) == (["y"], ["x"])


def test_deterministic_for_any_input_order():
    cands = [c(f"k{i:02d}", 10 + i, 1 + i % 4, 10 + i % 7) for i in range(30)]
    assert select_within_budget(cands, 120 * 60, utc_day) == select_within_budget(
        list(reversed(cands)), 120 * 60, utc_day
    )
