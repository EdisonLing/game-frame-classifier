"""Unit tests for session grouping, stable assignment, caps and tiers."""

from __future__ import annotations

import csv
import json
from collections import defaultdict

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
    clips = [{"source": "a", "recorded_start_utc": f"2026-01-01T0{i}:00:00Z"} for i in range(5)]
    clips.extend({"source": "b", "recorded_start_utc": f"2026-01-02T0{i}:00:00Z"} for i in range(2))
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


def _read(path):
    with path.open(encoding="utf-8") as file:
        return list(csv.DictReader(file))


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _forty_sessions():
    return [{"source": "a", "recorded_start_utc": f"2026-01-{1 + i // 20:02d}T{i % 20:02d}:00:00Z"} for i in range(40)]


def test_greedy_fill_approaches_targets_and_is_seeded(tmp_path) -> None:
    splits = {}
    for seed in (360, 361):
        data = tmp_path / f"data{seed}"
        write_split_inputs(data, _forty_sessions(), slots_per_clip=5)
        run_split(data, write_split_config(tmp_path / f"split{seed}.json", seed=seed))
        splits[seed] = {row["clip_key"]: row["split"] for row in _read(data / "manifests/splits/v1/ledger.csv")}
    shares = {name: list(splits[360].values()).count(name) / 40 for name in ("train", "val", "test_session")}
    assert shares == pytest.approx({"train": 0.70, "val": 0.15, "test_session": 0.15}, abs=0.03)
    again = tmp_path / "again"
    write_split_inputs(again, _forty_sessions(), slots_per_clip=5)
    run_split(again, write_split_config(tmp_path / "again.json"))
    assert {row["clip_key"]: row["split"] for row in _read(again / "manifests/splits/v1/ledger.csv")} == splits[360]
    assert splits[361] != splits[360]


def test_new_sessions_are_filled_against_all_existing_assignments(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [{"source": "a", "recorded_start_utc": f"2026-01-01T{i * 2:02d}:00:00Z"} for i in range(8)]
    write_split_inputs(data, clips)
    config = write_split_config(tmp_path / "split.json")
    run_split(data, config)
    ledger = data / "manifests/splits/v1/ledger.csv"
    rows = _read(ledger)
    for row in rows:
        row["split"] = "train"
    _write(ledger, rows)
    clips.extend({"source": "a", "recorded_start_utc": f"2026-01-03T{i * 2:02d}:00:00Z"} for i in range(2))
    write_split_inputs(data, clips)
    run_split(data, config)
    new = {row["clip_key"]: row["split"] for row in _read(ledger)}
    assert {new[clips[8]["clip_key"]], new[clips[9]["clip_key"]]} == {"val", "test_session"}


def test_reset_is_draft_only(tmp_path) -> None:
    data = tmp_path / "data"
    write_split_inputs(data, [{"source": "a", "recorded_start_utc": "2026-01-01T00:00:00Z"}])
    config = write_split_config(tmp_path / "split.json")
    run_split(data, config)
    run_split(data, config, reset=True)
    (data / "manifests/splits/v1/freeze.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SplitterError, match="frozen") as caught:
        run_split(data, config, reset=True)
    assert caught.value.exit_code == 1


def test_holdout_source_only_in_test_source(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [{"source": src, "recorded_start_utc": f"2026-01-0{day}T00:00:00Z"} for src in ("a", "held") for day in range(1, 6)]
    write_split_inputs(data, clips)
    run_split(data, write_split_config(tmp_path / "split.json", holdout_sources={"Valorant": ["held"]}))
    out = data / "manifests/splits/v1"
    for split in ("train", "val", "test_session"):
        assert all(row["source"] != "held" for row in _read(out / f"{split}.csv"))
    assert {row["source"] for row in _read(out / "test_source.csv")} == {"held"}


def _train(source, count):
    return [{"game": "Valorant", "split": "train", "source": source, "slot_id": f"{source}{i}", "clip_key": source, "session": source} for i in range(count)]


def test_source_cap_default_and_infeasible_cap() -> None:
    slots = _train("a", 8) + _train("b", 2) + [dict(_train("c", 1)[0], split="val")] * 1
    kept, dropped = _apply_source_cap(slots, 360, 1.0)
    assert kept == slots and dropped == []
    # Two train sources: a cap of 0.1 is raised to 1/2.
    kept, dropped = _apply_source_cap(slots, 360, 0.1)
    assert sum(row["source"] == "a" for row in kept) == 2 and len(dropped) == 6
    assert any(row["split"] == "val" for row in kept)
    assert _apply_source_cap(slots, 360, 0.1)[1] == dropped


def test_tiers_do_not_change_when_clips_are_added(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [{"source": "a", "recorded_start_utc": f"2026-01-0{day}T00:00:00Z"} for day in range(1, 6)]
    write_split_inputs(data, clips, slots_per_clip=6)
    config = write_split_config(tmp_path / "split.json")
    run_split(data, config)
    out = data / "manifests/splits/v1"
    before = {row["slot_id"]: row["tier"] for split in ("train", "val", "test_session") for row in _read(out / f"{split}.csv")}
    clips.append({"source": "a", "recorded_start_utc": "2026-02-01T00:00:00Z"})
    write_split_inputs(data, clips, slots_per_clip=6)
    run_split(data, config)
    after = {row["slot_id"]: row["tier"] for split in ("train", "val", "test_session") for row in _read(out / f"{split}.csv")}
    assert after.items() >= before.items()
    for key in {slot.split(":")[0] for slot in after}:
        tiers = [tier for slot, tier in after.items() if slot.startswith(key)]
        assert abs(tiers.count("full") - tiers.count("crf45")) <= 1


def test_frozen_bridge_keeps_session_labels_within_one_split(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [{"source": "a", "recorded_start_utc": "2026-01-01T00:00:00Z"}, {"source": "a", "recorded_start_utc": "2026-01-01T01:00:00Z"}]
    write_split_inputs(data, clips)
    config = write_split_config(tmp_path / "split.json")
    run_split(data, config)
    out = data / "manifests/splits/v1"
    rows = _read(out / "ledger.csv")
    rows[0]["split"], rows[1]["split"] = "train", "val"
    _write(out / "ledger.csv", rows)
    (out / "freeze.json").write_text("{}", encoding="utf-8")
    clips.append({"source": "a", "recorded_start_utc": "2026-01-01T00:30:00Z"})
    write_split_inputs(data, clips)
    run_split(data, config)
    assert {row["clip_key"]: row["split"] for row in _read(out / "ledger.csv")} == {row["clip_key"]: row["split"] for row in rows}
    labels = defaultdict(set)
    for split in ("train", "val", "test_session", "test_source"):
        for row in _read(out / f"{split}.csv"):
            labels[row["session"]].add(split)
    assert all(len(splits) == 1 for splits in labels.values())


def test_unknown_game_is_an_input_error(tmp_path) -> None:
    data = tmp_path / "data"
    write_split_inputs(data, [{"game": "Tetris", "recorded_start_utc": ""}])
    with pytest.raises(SplitterError, match="Tetris") as caught:
        run_split(data, write_split_config(tmp_path / "split.json"))
    assert caught.value.exit_code == 2


def test_first_three_sessions_of_a_game_land_in_three_splits(tmp_path) -> None:
    data = tmp_path / "data"
    write_split_inputs(data, [{"source": "a", "recorded_start_utc": f"2026-01-0{day}T00:00:00Z"} for day in range(1, 4)])
    run_split(data, write_split_config(tmp_path / "split.json"))
    assert sorted(row["split"] for row in _read(data / "manifests/splits/v1/ledger.csv")) == ["test_session", "train", "val"]
