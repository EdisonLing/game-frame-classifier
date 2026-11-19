"""Unit tests for gfc-derive-frames helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from game_frame_classifier.derive_frames import (
    CLIPS_INDEX_COLUMNS,
    SLOTS_COLUMNS,
    build_clip_row,
    build_slot_rows,
    find_clips,
    parse_frame_bucket,
    pair_slots,
    plan_clip,
    public_examples_ok,
    rebuild_tables_from_disk,
    source_kind,
    write_indexes,
)
from game_frame_classifier.sourcing.recipe import load_recipe
from tests.helpers.derive_frames_fixtures import (
    ROOT,
    clip_key_for,
    write_clip_tree,
    write_index_entry,
    write_pack_manifest,
)

RECIPE = load_recipe(ROOT / "config" / "recipe.json")


def test_parse_frame_bucket():
    assert parse_frame_bucket("cabcdef012345_full_b000012.jpg", "cabcdef012345", "full") == 12
    assert parse_frame_bucket("cabcdef012345_crf45_b000000.jpg", "cabcdef012345", "crf45") == 0
    assert parse_frame_bucket("cabcdef012345_full_b000012.jpg", "cabcdef012345", "crf45") is None
    assert parse_frame_bucket("other_full_b000012.jpg", "cabcdef012345", "full") is None
    assert parse_frame_bucket("not-a-frame.jpg", "cabcdef012345", "full") is None


def test_pair_slots_with_unpaired():
    full = {0: Path("a"), 1: Path("b"), 2: Path("c")}
    low = {1: Path("d"), 2: Path("e"), 3: Path("f")}
    paired, unpaired = pair_slots("ckey", full, "crf45", low)
    assert paired == [1, 2]
    assert unpaired == 2


def test_pair_slots_quick_mode():
    full = {0: Path("a"), 5: Path("b")}
    paired, unpaired = pair_slots("ckey", full, "", None)
    assert paired == [0, 5]
    assert unpaired == 0


@pytest.mark.parametrize(
    "source,kind",
    [
        ("contributor_alex", "contributor"),
        ("friend_bob", "contributor"),
        ("public_twitch", "public"),
        ("tester", "personal"),
    ],
)
def test_source_kind(source, kind):
    assert source_kind(source) == kind


def test_public_examples_ok_personal():
    assert public_examples_ok("personal", None) is True


def test_public_examples_ok_consenting(tmp_path):
    fs = tmp_path / "frame_sources"
    write_pack_manifest(fs, "pack-yes", public_examples=True)
    manifest = json.loads((fs / "_packs" / "pack-yes" / "pack_manifest.json").read_text(encoding="utf-8"))
    assert public_examples_ok("contributor", manifest) is True


def test_public_examples_ok_non_consenting(tmp_path):
    fs = tmp_path / "frame_sources"
    write_pack_manifest(fs, "pack-no", public_examples=False)
    manifest = json.loads((fs / "_packs" / "pack-no" / "pack_manifest.json").read_text(encoding="utf-8"))
    assert public_examples_ok("contributor", manifest) is False


def test_public_examples_ok_unknown_contributor():
    assert public_examples_ok("contributor", None) is False
    assert public_examples_ok("public", None) is False


def test_plan_clip_pairs_and_counts_unpaired(tmp_path):
    fs = tmp_path / "frame_sources"
    sha = "a" * 64
    key = clip_key_for(sha)
    write_clip_tree(
        fs,
        game="Valorant",
        source="contributor_alex",
        clip_sha256=sha,
        width=1920,
        height=1080,
        buckets=[0, 1],
        extra_files=[("full", f"{key}_full_b000099.jpg", 99)],
    )
    # low tier missing bucket 99 → unpaired
    ref = find_clips(fs)[0]
    plan = plan_clip(ref, RECIPE)
    assert plan.skip_reason == ""
    assert plan.buckets == [0, 1]
    assert plan.unpaired == 1
    assert plan.low_tier == "crf45"


def test_plan_clip_quick_mode(tmp_path):
    fs = tmp_path / "frame_sources"
    sha = "b" * 64
    write_clip_tree(
        fs,
        game="CS2",
        source="contributor_bob",
        clip_sha256=sha,
        width=1920,
        height=1080,
        buckets=[0, 2],
        tiers=("full",),
        low_encoder="",
    )
    plan = plan_clip(find_clips(fs)[0], RECIPE)
    assert plan.skip_reason == ""
    assert plan.low_tier == ""
    assert plan.buckets == [0, 2]


def test_plan_clip_missing_full_excluded(tmp_path):
    fs = tmp_path / "frame_sources"
    sha = "c" * 64
    write_clip_tree(
        fs,
        game="Minecraft",
        source="personal_x",
        clip_sha256=sha,
        width=640,
        height=360,
        buckets=[0],
        tiers=("crf45",),
    )
    plan = plan_clip(find_clips(fs)[0], RECIPE)
    assert plan.skip_reason == "missing full tier"


def test_table_rows_sorted_and_paths_relative(tmp_path):
    fs = tmp_path / "frame_sources"
    data_root = tmp_path
    sha1 = "1" * 64
    sha2 = "2" * 64
    write_clip_tree(
        fs, game="Valorant", source="contributor_z", clip_sha256=sha2,
        width=256, height=144, buckets=[3, 1],
    )
    write_clip_tree(
        fs, game="Valorant", source="a_source", clip_sha256=sha1,
        width=256, height=144, buckets=[2],
    )
    # Pretend derived frames exist
    for ref in find_clips(fs):
        plan = plan_clip(ref, RECIPE)
        out = data_root / "frames" / ref.game / ref.source / ref.clip_key
        for tier in ("full", "crf45"):
            for bucket in plan.buckets:
                p = out / tier / f"{ref.clip_key}_{tier}_b{bucket:06d}.jpg"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"x")
        write_index_entry(
            fs, clip_sha256=str(plan.clip["clip_sha256"]), clip_key=ref.clip_key,
            pack_id="personal:run1" if ref.source == "a_source" else "pack-1",
            game=ref.game, source=ref.source,
        )
    write_pack_manifest(fs, "pack-1", public_examples=True)

    clip_rows, slot_rows, skips = rebuild_tables_from_disk(data_root, fs, RECIPE)
    assert skips == []
    assert [r["source"] for r in clip_rows] == ["a_source", "contributor_z"]
    assert [(r["clip_key"], int(r["bucket"])) for r in slot_rows] == sorted(
        [(r["clip_key"], int(r["bucket"])) for r in slot_rows],
        key=lambda t: (t[0], t[1]),
    )
    for row in slot_rows:
        assert not row["path_full"].startswith("/")
        assert "\\" not in row["path_full"]
        assert row["path_full"].startswith("frames/")
        assert row["path_low"].startswith("frames/")

    write_indexes(data_root, clip_rows, slot_rows)
    with open(data_root / "manifests" / "clips_index.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert list(reader.fieldnames) == list(CLIPS_INDEX_COLUMNS)
        rows = list(reader)
    assert rows[0]["source_kind"] == "personal"
    assert rows[0]["origin"] == "personal:run1"
    assert rows[0]["public_examples_ok"] == "true"
    assert rows[1]["source_kind"] == "contributor"
    assert rows[1]["origin"] == "pack-1"
    assert rows[1]["public_examples_ok"] == "true"

    with open(data_root / "manifests" / "slots.csv", encoding="utf-8") as f:
        assert list(csv.DictReader(f).fieldnames) == list(SLOTS_COLUMNS)


def test_build_slot_rows_quick_mode_empty_path_low(tmp_path):
    fs = tmp_path / "frame_sources"
    sha = "d" * 64
    write_clip_tree(
        fs, game="Overwatch_2", source="contributor_x", clip_sha256=sha,
        width=1920, height=1080, buckets=[0], tiers=("full",), low_encoder="",
    )
    plan = plan_clip(find_clips(fs)[0], RECIPE)
    rows = build_slot_rows(plan, RECIPE)
    assert len(rows) == 1
    assert rows[0]["path_low"] == ""
    assert rows[0]["path_full"].endswith("_full_b000000.jpg")
    assert rows[0]["target_time_s"] == 0.0

    clip_row = build_clip_row(plan, RECIPE, origin="pack-q", examples_ok=False, derive_id="x")
    assert clip_row["low_tier"] == ""
    assert "low_encoder" in clip_row


def test_other_tree_is_indexed_with_name_and_special_paths(tmp_path):
    fs = tmp_path / "frame_sources"
    sha = "e" * 64
    write_clip_tree(
        fs,
        game="Other",
        other_name="Apex_Legends",
        source="contributor_x",
        clip_sha256=sha,
        width=256,
        height=144,
        buckets=[0],
    )
    ref = find_clips(fs, game="Other")[0]
    assert ref.game == "Other"
    assert ref.other_name == "Apex_Legends"
    plan = plan_clip(ref, RECIPE)
    clip = build_clip_row(plan, RECIPE, origin="pack-other", examples_ok=False, derive_id="x")
    slots = build_slot_rows(plan, RECIPE)
    assert clip["game"] == "Other"
    assert clip["other_name"] == "Apex_Legends"
    assert clip["content_type"] == ""
    assert clip["content_type_origin"] == ""
    assert "content_type" in CLIPS_INDEX_COLUMNS
    assert list(CLIPS_INDEX_COLUMNS).index("content_type") == list(CLIPS_INDEX_COLUMNS).index("other_name") + 1
    assert slots[0]["other_name"] == "Apex_Legends"
    assert slots[0]["path_full"].startswith(
        "frames/_other/Apex_Legends/contributor_x/"
    )
