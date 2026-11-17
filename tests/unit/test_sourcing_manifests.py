"""Clip and frame table writers."""

import csv
import json

import pytest

from game_frame_classifier.sourcing.manifests import CLIP_COLUMNS, FRAME_COLUMNS, blank_clip_row, write_table


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_blank_row_has_every_column():
    row = blank_clip_row()
    assert tuple(row) == CLIP_COLUMNS
    assert row["aliases"] == []


def test_write_table_csv_and_json(tmp_path):
    rows = [{"image_id": "c1:b000000:full", "crf": 0, "bucket": 0, "width": 640, "sha256": "ab"}]
    write_table(rows, FRAME_COLUMNS, tmp_path / "f.csv", tmp_path / "f.json")
    parsed = read_csv(tmp_path / "f.csv")
    assert parsed[0]["image_id"] == "c1:b000000:full" and parsed[0]["tier"] == ""
    data = json.loads((tmp_path / "f.json").read_text(encoding="utf-8"))
    assert list(data[0]) == list(FRAME_COLUMNS) and data[0]["width"] == 640


def test_lists_and_bools(tmp_path):
    row = blank_clip_row()
    row.update(aliases=["a.mp4", "b.mp4"], vfr=True, hdr=False)
    write_table([row], CLIP_COLUMNS, tmp_path / "c.csv", tmp_path / "c.json")
    parsed = read_csv(tmp_path / "c.csv")[0]
    assert parsed["aliases"] == "a.mp4|b.mp4" and parsed["vfr"] == "true" and parsed["hdr"] == "false"
    data = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))[0]
    assert data["aliases"] == ["a.mp4", "b.mp4"] and data["vfr"] is True


def test_unknown_column_rejected(tmp_path):
    with pytest.raises(ValueError):
        write_table([{"nope": 1}], FRAME_COLUMNS, tmp_path / "x.csv", tmp_path / "x.json")
