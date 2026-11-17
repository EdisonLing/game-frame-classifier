"""Unit tests for split_manifest (NumPy + Pillow)."""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from game_frame_classifier.split_manifest import (
    LABELS,
    SlotRow,
    class_weights,
    image_path,
    load_image_u8,
    load_split,
    split_hashes,
)
from game_frame_classifier.sourcing.labels import GAMES
from tests.helpers.loader_fixtures import (
    build_split_fixture,
    make_slot_dict,
    write_frame_jpeg,
    write_split_csv,
    write_summary,
)


def test_labels_match_games():
    assert LABELS == GAMES
    assert LABELS[0] == "Valorant"
    assert LABELS[5] == "Marvel_Rivals"


def test_load_split_parses_fixture(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=1, splits=("train",))
    rows = load_split(split_dir, "train")
    assert len(rows) == 6
    assert rows[0].game == "Valorant"
    assert rows[0].label == 0
    assert rows[0].path.startswith("frames/")
    assert "/" in rows[0].path
    assert image_path(rows[0], data_root).is_file()


def test_load_split_refuses_test_without_allow(tmp_path):
    _, split_dir = build_split_fixture(
        tmp_path, n_per_game=1, splits=("train", "test_session", "test_source")
    )
    with pytest.raises(PermissionError):
        load_split(split_dir, "test_session")
    with pytest.raises(PermissionError):
        load_split(split_dir, "test_source")
    assert len(load_split(split_dir, "test_session", allow_test=True)) == 6
    assert len(load_split(split_dir, "test_source", allow_test=True)) == 6


def test_label_game_mismatch_raises(tmp_path):
    split_dir = tmp_path / "splits" / "v1"
    row = make_slot_dict(game="Valorant", label=3)
    write_split_csv(split_dir / "train.csv", [row])
    with pytest.raises(ValueError, match="label/game mismatch"):
        load_split(split_dir, "train")


def test_image_path_tier_modes(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=1, splits=("train",))
    rows = load_split(split_dir, "train")
    full_row = next(r for r in rows if r.tier == "full")
    low_row = next(r for r in rows if r.tier == "crf45")

    assert image_path(full_row, data_root, "assigned") == data_root / Path(
        *full_row.path.split("/")
    )
    assert image_path(full_row, data_root, "assigned") == image_path(
        full_row, data_root, "full"
    )
    assert image_path(low_row, data_root, "assigned") == image_path(
        low_row, data_root, "low"
    )
    assert image_path(full_row, data_root, "low") == data_root / Path(
        *full_row.path_low.split("/")
    )
    assert image_path(low_row, data_root, "full") == data_root / Path(
        *low_row.path_full.split("/")
    )


def test_class_weights_known_counts():
    specs = [
        (0, "Valorant", 0),
        (1, "Valorant", 0),
        (2, "Valorant", 0),
        (3, "CS2", 2),
    ]
    slot_rows = []
    for bucket, game, label in specs:
        r = make_slot_dict(
            game=game, label=label, bucket=bucket, clip_key=f"c{bucket:012d}"
        )
        slot_rows.append(
            SlotRow(
                slot_id=r["slot_id"],
                clip_key=r["clip_key"],
                game=r["game"],
                label=r["label"],
                source=r["source"],
                source_kind=r["source_kind"],
                session=r["session"],
                split=r["split"],
                tier=r["tier"],
                path=r["path"],
                path_full=r["path_full"],
                path_low=r["path_low"],
                bucket=r["bucket"],
                target_time_s=float(r["target_time_s"]),
                public_examples_ok=bool(r["public_examples_ok"]),
            )
        )
    w = class_weights(slot_rows)
    assert w.shape == (6,)
    n, k = 4.0, 6.0
    assert w[0] == pytest.approx(n / (k * 3))
    assert w[2] == pytest.approx(n / (k * 1))
    assert w[1] == 0.0
    assert w[3] == 0.0


def test_split_hashes_from_summary(tmp_path):
    split_dir = tmp_path / "v1"
    write_summary(split_dir, {"train": "ab" * 32, "val": "cd" * 32})
    assert split_hashes(split_dir) == {"train": "ab" * 32, "val": "cd" * 32}


def test_load_image_u8_shape_and_dtype(tmp_path):
    path = write_frame_jpeg(tmp_path / "ok.jpg", colour=(10, 20, 30))
    arr = load_image_u8(path)
    assert arr.shape == (144, 256, 3)
    assert arr.dtype == np.uint8


def test_load_image_u8_rejects_wrong_size(tmp_path):
    path = write_frame_jpeg(tmp_path / "bad.jpg", size=(128, 72))
    with pytest.raises(ValueError, match="256x144"):
        load_image_u8(path)


def test_load_image_u8_greyscale_to_rgb(tmp_path):
    path = write_frame_jpeg(tmp_path / "grey.jpg", mode="L", colour=(90, 0, 0))
    arr = load_image_u8(path)
    assert arr.shape == (144, 256, 3)
    assert arr.dtype == np.uint8
    assert (arr[:, :, 0] == arr[:, :, 1]).all()
    assert (arr[:, :, 1] == arr[:, :, 2]).all()
