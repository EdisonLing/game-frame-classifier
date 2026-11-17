"""Unit tests for session grouping, stable assignment, caps and tiers."""

from __future__ import annotations

import csv
import json

import pytest

from game_frame_classifier.dataset_splitter import (
    SplitterError,
    _apply_source_cap,
    build_sessions,
    run_split,
    tier_for_slot,
)
from tests.helpers.splitter_fixtures import write_split_config, write_split_inputs


def test_sessions_handle_overlap_gap_untimed_and_boundaries() -> None:
    clips = [
        {"clip_key": "a", "game": "Valorant", "source": "s", "recorded_start_utc": "2026-01-01T00:00:00Z", "duration_s": "60"},
        {"clip_key": "b", "game": "Valorant", "source": "s", "recorded_start_utc": "2026-01-01T00:30:59Z", "duration_s": "1"},
        {"clip_key": "c", "game": "Valorant", "source": "s", "recorded_start_utc": "2026-01-01T01:01:01Z", "duration_s": "1"},
        {"clip_key": "d", "game": "Valorant", "source": "s", "recorded_start_utc": "", "duration_s": "1"},
        {"clip_key": "e", "game": "CS2", "source": "s", "recorded_start_utc": "2026-01-01T00:00:00Z", "duration_s": "1"},
    ]
    sessions = build_sessions(clips, 30)
    assert [[clip["clip_key"] for clip in session["clips"]] for session in sessions] == [["e"], ["a", "b"], ["c"], ["d"]]


def test_tier_formula_and_quick_slots() -> None:
    values = [tier_for_slot("c000000000001", bucket, "low.jpg") for bucket in range(9)]
    assert abs(values.count("full") - values.count("crf45")) <= 1
    assert tier_for_slot("c000000000001", 0, "") == "full"


def test_rerun_keeps_ledger_assignments_and_holdout(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [{"source": "a", "recorded_start_utc": f"2026-01-01T0{i}:00:00Z"} for i in range(4)]
    clips.append({"source": "held", "recorded_start_utc": "2026-01-01T10:00:00Z"})
    write_split_inputs(data, clips)
    config = write_split_config(tmp_path / "split.json", holdout_sources={"Valorant": ["held"]})
    run_split(data, config)
    ledger = data / "manifests" / "splits" / "v1" / "ledger.csv"
    with ledger.open(encoding="utf-8") as file:
        first = {row["clip_key"]: row["split"] for row in csv.DictReader(file)}
    clips.append({"source": "a", "recorded_start_utc": "2026-01-02T00:00:00Z"})
    write_split_inputs(data, clips)
    run_split(data, config)
    with ledger.open(encoding="utf-8") as file:
        second = {row["clip_key"]: row["split"] for row in csv.DictReader(file)}
    assert second.items() >= first.items()
    assert second[clips[4]["clip_key"]] == "test_source"


def test_policy_conflict_and_source_cap(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [{"source": "a", "recorded_start_utc": f"2026-01-01T0{i}:00:00:00Z"} for i in range(5)]
    clips.extend({"source": "b", "recorded_start_utc": f"2026-01-02T0{i}:00:00:00Z"} for i in range(2))
    write_split_inputs(data, clips, slots_per_clip=6)
    config = write_split_config(tmp_path / "split.json")
    run_split(data, config)
    write_split_config(config, holdout_sources={"Valorant": ["a"]})
    with pytest.raises(SplitterError, match="contradicts"):
        run_split(data, config)
    slots = [
        {"game": "Valorant", "split": "train", "source": "a", "slot_id": f"a{i}", "clip_key": "a", "session": "sa"}
        for i in range(8)
    ] + [
        {"game": "Valorant", "split": "train", "source": "b", "slot_id": f"b{i}", "clip_key": "b", "session": "sb"}
        for i in range(2)
    ]
    kept, dropped = _apply_source_cap(slots, 360, .5)
    assert len(dropped) == 6
    assert {row["reason"] for row in dropped} == {"source_cap"}
    assert sum(row["source"] == "a" for row in kept) == sum(row["source"] == "b" for row in kept)


def test_draft_bridge_reassigns_and_frozen_bridge_is_unused(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [
        {"source": "a", "recorded_start_utc": "2026-01-01T00:00:00Z"},
        {"source": "a", "recorded_start_utc": "2026-01-01T01:00:00Z"},
    ]
    write_split_inputs(data, clips)
    config = write_split_config(tmp_path / "split.json")
    run_split(data, config)
    ledger_path = data / "manifests" / "splits" / "v1" / "ledger.csv"
    rows = list(csv.DictReader(ledger_path.open(encoding="utf-8")))
    rows[0]["split"], rows[1]["split"] = "train", "val"
    with ledger_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    clips.append({"source": "a", "recorded_start_utc": "2026-01-01T00:30:00Z"})
    write_split_inputs(data, clips)
    run_split(data, config)
    assert "bridges_splits" in (data / "manifests" / "splits" / "v1" / "reassigned.csv").read_text(encoding="utf-8")

    frozen_data = tmp_path / "frozen-data"
    frozen_clips = [
        {"source": "a", "recorded_start_utc": "2026-01-01T00:00:00Z"},
        {"source": "a", "recorded_start_utc": "2026-01-01T01:00:00Z"},
    ]
    write_split_inputs(frozen_data, frozen_clips)
    frozen_config = write_split_config(tmp_path / "frozen.json")
    run_split(frozen_data, frozen_config)
    frozen_ledger = frozen_data / "manifests" / "splits" / "v1" / "ledger.csv"
    rows = list(csv.DictReader(frozen_ledger.open(encoding="utf-8")))
    rows[0]["split"], rows[1]["split"] = "train", "val"
    with frozen_ledger.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    (frozen_ledger.parent / "freeze.json").write_text(json.dumps({"test_design": "held-out design"}), encoding="utf-8")
    frozen_clips.append({"source": "a", "recorded_start_utc": "2026-01-01T00:30:00Z"})
    write_split_inputs(frozen_data, frozen_clips)
    run_split(frozen_data, frozen_config)
    assert "bridges_splits" in (frozen_ledger.parent / "unused.csv").read_text(encoding="utf-8")
