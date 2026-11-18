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
    expand_holdout_sources,
    load_config,
    resolve_source_groups,
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


def test_other_label_holdout_and_name_report(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [
        {"game": "Other", "other_name": name, "source": source,
         "recorded_start_utc": f"2026-01-0{day}T00:00:00Z"}
        for name, source, day in (
            ("desktop", "a", 1),
            ("desktop", "b", 2),
            ("Apex_Legends", "a", 3),
            ("Apex_Legends", "b", 4),
        )
    ]
    write_split_inputs(data, clips)
    config = write_split_config(tmp_path / "split.json", holdout_other=["desktop"])
    run_split(data, config)
    out = data / "manifests/splits/v1"
    test_rows = _read(out / "test_source.csv")
    assert {(row["other_name"], row["source"]) for row in test_rows} == {
        ("desktop", "a"), ("desktop", "b"),
    }
    assert {row["label"] for row in test_rows} == {"6"}
    report = _read(out / "other_names.csv")
    assert any(row["other_name"] == "desktop" and row["split"] == "test_source" for row in report)

    write_split_config(config, holdout_other=["desktop", "Apex_Legends"])
    with pytest.raises(SplitterError, match="holdout_other") as caught:
        run_split(data, config)
    assert caught.value.exit_code == 1


def test_other_holdout_can_carry_a_mixed_session_without_ledger_conflict(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [
        {"game": "Other", "other_name": name, "source": "same_source",
         "recorded_start_utc": "2026-01-01T00:00:00Z"}
        for name in ("desktop", "Apex_Legends")
    ]
    write_split_inputs(data, clips)
    config = write_split_config(tmp_path / "split.json", holdout_other=["desktop"])
    run_split(data, config)
    run_split(data, config)
    assert {
        row["other_name"]
        for row in _read(data / "manifests/splits/v1/test_source.csv")
    } == {"desktop", "Apex_Legends"}


def _train(source, count):
    return [{"game": "Valorant", "split": "train", "source": source, "slot_id": f"{source}{i}", "clip_key": source, "session": source} for i in range(count)]


def test_source_cap_default_and_infeasible_cap() -> None:
    slots = _train("a", 8) + _train("b", 2) + [dict(_train("c", 1)[0], split="val")]
    kept, dropped = _apply_source_cap(slots, 360, 1.0)
    assert kept == slots and dropped == []
    # Two train sources: 0.1 is below 1/2, and the median of two counts is their mean, so no
    # share cap applies with fewer than three groups.
    kept, dropped = _apply_source_cap(slots, 360, 0.1)
    assert kept == slots and dropped == []
    # Three train sources: capped at the median count (5), deterministically.
    slots3 = slots + _train("d", 5)
    kept, dropped = _apply_source_cap(slots3, 360, 0.1)
    assert sum(row["source"] == "a" for row in kept) == 5 and len(dropped) == 3
    assert sum(row["source"] == "b" for row in kept) == 2
    assert any(row["split"] == "val" for row in kept)
    assert _apply_source_cap(slots3, 360, 0.1)[1] == dropped


def test_median_fallback_ignores_one_tiny_source() -> None:
    # 1/15 with three sources: capped at the median (40), not at the one-clip source's 3.
    slots = _train("big", 100) + _train("mid", 40) + _train("tiny", 3)
    kept, dropped = _apply_source_cap(slots, 360, 1 / 15)
    count = lambda src: sum(row["source"] == src for row in kept)
    assert (count("big"), count("mid"), count("tiny")) == (40, 40, 3)
    assert {row["reason"] for row in dropped} == {"source_cap"}


def test_train_frame_cap_per_source_leaves_other_splits() -> None:
    slots = _train("a", 30) + _train("b", 10) + [dict(row, split="test_session") for row in _train("c", 50)]
    kept, dropped = _apply_source_cap(slots, 360, 1.0, 12)
    count = lambda src: sum(row["source"] == src for row in kept)
    assert (count("a"), count("b"), count("c")) == (12, 10, 50)
    assert len(dropped) == 18
    # A tighter share cap still applies after the frame cap (0.5 of 22 -> a trimmed to b's 10).
    kept, _ = _apply_source_cap(slots, 360, 0.5, 12)
    assert sum(row["source"] == "a" for row in kept) == 10


def test_raising_the_cap_brings_slots_back(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [{"source": src, "recorded_start_utc": f"2026-01-0{day}T00:00:00Z"} for src, days in (("me", range(1, 9)), ("friend", range(1, 3)), ("pal", range(1, 4))) for day in days]
    write_split_inputs(data, clips, slots_per_clip=10)
    out = data / "manifests/splits/v1"
    run_split(data, write_split_config(tmp_path / "tight.json", max_source_share=1 / 15))
    tight = {row["slot_id"] for row in _read(out / "train.csv")}
    run_split(data, write_split_config(tmp_path / "open.json", max_source_share=1.0))
    open_ = {row["slot_id"] for row in _read(out / "train.csv")}
    assert tight < open_
    assert (data / "manifests/slots_clean.csv").is_file()


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


def _used(out):
    return {row["slot_id"]: row for split in ("train", "val", "test_session", "test_source") for row in _read(out / f"{split}.csv")}


def test_source_limits_blanket_and_override_are_nested(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [{"source": src, "recorded_start_utc": f"2026-01-0{day}T00:00:00Z"} for src in ("me", "friend") for day in range(1, 6)]
    write_split_inputs(data, clips, slots_per_clip=10)
    out = data / "manifests/splits/v1"
    used = {}
    for name, limit, override in (("all", 0, {}), ("wide", 30, {}), ("tight", 12, {}), ("mine", 12, {"me": 40})):
        run_split(data, write_split_config(tmp_path / f"{name}.json", max_slots_per_source=limit, source_slots=override), reset=True)
        used[name] = _used(out)
    per_source = lambda rows, src: sum(row["source"] == src for row in rows.values())
    assert per_source(used["all"], "me") == per_source(used["all"], "friend") == 50
    assert per_source(used["wide"], "me") == per_source(used["wide"], "friend") == 30
    assert per_source(used["tight"], "friend") == 12
    assert (per_source(used["mine"], "me"), per_source(used["mine"], "friend")) == (40, 12)
    assert set(used["tight"]) <= set(used["wide"]) <= set(used["all"])
    reasons = {row["reason"] for row in _read(out / "unused.csv")}
    assert reasons == {"source_limit"}


def test_source_limits_are_validated_and_optional(tmp_path) -> None:
    config = json.loads(write_split_config(tmp_path / "old.json").read_text(encoding="utf-8"))
    config.pop("max_slots_per_source", None)
    (tmp_path / "old.json").write_text(json.dumps(config), encoding="utf-8")
    assert load_config(tmp_path / "old.json")["max_slots_per_source"] == 0
    assert load_config(tmp_path / "old.json")["source_groups"] == {}
    with pytest.raises(SplitterError, match="whole numbers"):
        load_config(write_split_config(tmp_path / "bad.json", source_slots={"me": -1}))
    with pytest.raises(SplitterError, match="whole numbers"):
        load_config(write_split_config(tmp_path / "bad2.json", max_slots_per_source=1.5))


def test_source_groups_reject_duplicate_and_name_collision(tmp_path) -> None:
    with pytest.raises(SplitterError, match="is in source_groups") as dup:
        load_config(write_split_config(
            tmp_path / "dup.json",
            source_groups={"person_a": ["tester", "tester_oldpc"], "other": ["tester"]},
        ))
    assert dup.value.exit_code == 2
    with pytest.raises(SplitterError, match="reuses a source name") as named:
        resolve_source_groups({"tester": ["tester", "tester_oldpc"]}, {"tester", "tester_oldpc"})
    assert named.value.exit_code == 2
    with pytest.raises(SplitterError, match="non-empty list"):
        load_config(write_split_config(tmp_path / "empty.json", source_groups={"person_a": []}))
    mapping = resolve_source_groups({"person_a": ["tester", "tester_oldpc"]}, {"tester", "tester_oldpc", "friend"})
    assert mapping == {"tester": "person_a", "tester_oldpc": "person_a", "friend": "friend"}


def test_source_cap_per_group_share_and_median() -> None:
    # Without grouping: three sources, 0.5 share with k=3 keeps everyone (each already <= 0.5).
    slots = _train("tester", 40) + _train("tester_oldpc", 40) + _train("friend", 20)
    kept, dropped = _apply_source_cap(slots, 360, 0.5)
    assert dropped == [] and kept == slots
    # Same footage, two sources as one person: k=2 groups, 0.5 share thins the pair to friend's 20.
    mapping = {"tester": "person_a", "tester_oldpc": "person_a", "friend": "friend"}
    kept, dropped = _apply_source_cap(slots, 360, 0.5, source_to_group=mapping)
    assert sum(row["source"] in {"tester", "tester_oldpc"} for row in kept) == 20
    assert sum(row["source"] == "friend" for row in kept) == 20
    assert {row["reason"] for row in dropped} == {"source_cap"}
    # 1/15 with two groups (pair + friend): below three groups no share cap applies.
    kept, dropped = _apply_source_cap(slots, 360, 1 / 15, source_to_group=mapping)
    assert kept == slots and dropped == []
    # A third group brings the median fallback back: counts 80, 20, 30 -> median 30.
    slots3 = slots + _train("pal", 30)
    kept, dropped = _apply_source_cap(slots3, 360, 1 / 15, source_to_group=mapping)
    assert sum(row["source"] in {"tester", "tester_oldpc"} for row in kept) == 30
    assert sum(row["source"] == "friend" for row in kept) == 20
    assert len(dropped) == 50


def test_train_frame_cap_and_nested_raising_per_group() -> None:
    slots = _train("tester", 30) + _train("tester_oldpc", 30) + _train("friend", 10)
    mapping = {"tester": "person_a", "tester_oldpc": "person_a", "friend": "friend"}
    kept, dropped = _apply_source_cap(slots, 360, 1.0, 25, source_to_group=mapping)
    assert sum(row["source"] in {"tester", "tester_oldpc"} for row in kept) == 25
    assert sum(row["source"] == "friend" for row in kept) == 10
    assert len(dropped) == 35
    tight_ids = {row["slot_id"] for row in kept}
    kept_open, _ = _apply_source_cap(slots, 360, 1.0, 50, source_to_group=mapping)
    open_ids = {row["slot_id"] for row in kept_open}
    assert tight_ids < open_ids
    assert sum(row["source"] in {"tester", "tester_oldpc"} for row in kept_open) == 50


def test_holdout_by_group_and_half_listed_error(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [
        {"source": src, "recorded_start_utc": f"2026-01-0{day}T00:00:00Z"}
        for src in ("tester", "tester_oldpc", "friend")
        for day in range(1, 5)
    ]
    write_split_inputs(data, clips)
    groups = {"person_a": ["tester", "tester_oldpc"]}
    run_split(data, write_split_config(
        tmp_path / "group.json",
        source_groups=groups,
        holdout_sources={"Valorant": ["person_a"]},
    ))
    out = data / "manifests/splits/v1"
    for split in ("train", "val", "test_session"):
        assert all(row["source"] not in {"tester", "tester_oldpc"} for row in _read(out / f"{split}.csv"))
    assert {row["source"] for row in _read(out / "test_source.csv")} == {"tester", "tester_oldpc"}
    with pytest.raises(SplitterError, match="would be split") as half:
        expand_holdout_sources(
            {"Valorant": ["tester"]},
            resolve_source_groups(groups, {"tester", "tester_oldpc", "friend"}),
        )
    assert half.value.exit_code == 1
    with pytest.raises(SplitterError, match="would be split"):
        run_split(data, write_split_config(
            tmp_path / "half.json",
            source_groups=groups,
            holdout_sources={"Valorant": ["tester"]},
        ))


def test_source_group_tables_and_empty_groups_match_ungrouped(tmp_path) -> None:
    clips = [
        {"source": src, "recorded_start_utc": f"2026-01-0{day}T00:00:00Z"}
        for src in ("tester", "tester_oldpc", "friend")
        for day in range(1, 4)
    ]
    plain = tmp_path / "plain"
    grouped = tmp_path / "grouped"
    write_split_inputs(plain, [dict(clip) for clip in clips])
    write_split_inputs(grouped, [dict(clip) for clip in clips])
    run_split(plain, write_split_config(tmp_path / "plain.json", max_source_share=1.0))
    run_split(grouped, write_split_config(
        tmp_path / "grouped.json",
        max_source_share=1.0,
        source_groups={"person_a": ["tester", "tester_oldpc"]},
    ))
    plain_out, grouped_out = plain / "manifests/splits/v1", grouped / "manifests/splits/v1"
    # Empty grouping leaves assignment identical to the default (no source_groups key needed).
    empty = tmp_path / "empty"
    write_split_inputs(empty, [dict(clip) for clip in clips])
    run_split(empty, write_split_config(tmp_path / "empty.json", max_source_share=1.0, source_groups={}))
    for split in ("train", "val", "test_session", "test_source"):
        plain_ids = {row["slot_id"] for row in _read(plain_out / f"{split}.csv")}
        empty_ids = {row["slot_id"] for row in _read(empty / "manifests/splits/v1" / f"{split}.csv")}
        assert plain_ids == empty_ids
    sources = _read(grouped_out / "sources.csv")
    assert all("group" in row for row in sources)
    by_source = {row["source"]: row["group"] for row in sources if row["game"] == "Valorant" and row["split"] == "train"}
    assert by_source["tester"] == by_source["tester_oldpc"] == "person_a"
    assert by_source["friend"] == "friend"
    counts = _read(grouped_out / "counts.csv")
    train = next(row for row in counts if row["game"] == "Valorant" and row["split"] == "train")
    assert int(train["sources"]) == 3 and int(train["groups"]) == 2
    summary = json.loads((grouped_out / "summary.json").read_text(encoding="utf-8"))
    assert summary["source_groups"]["person_a"] == ["tester", "tester_oldpc"]
