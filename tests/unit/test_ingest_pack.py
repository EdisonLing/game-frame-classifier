"""Unit tests for ingest path helpers and recipe_diff."""

import json
from pathlib import Path

import pytest

from game_frame_classifier.ingest_pack import (
    IngestError,
    clip_dest,
    ensure_under,
    recipe_diff,
    rel_dir_for,
    source_dir_name,
)


def test_source_dir_name():
    assert source_dir_name("alex") == "contributor_alex"


def test_clip_dest_and_rel(tmp_path):
    fs = tmp_path / "frame_sources"
    assert clip_dest(fs, "Valorant", "", "alex", "c0123456789ab") == fs / "Valorant" / "contributor_alex" / "c0123456789ab"
    assert clip_dest(fs, "Other", "Apex_Legends", "alex", "c0123456789ab") == (
        fs / "_other" / "Apex_Legends" / "contributor_alex" / "c0123456789ab"
    )
    assert rel_dir_for("Valorant", "", "bob", "c0123456789ab") == "Valorant/contributor_bob/c0123456789ab"
    assert rel_dir_for("Other", "Apex_Legends", "bob", "c0123456789ab") == (
        "_other/Apex_Legends/contributor_bob/c0123456789ab"
    )


def test_ensure_under_rejects_escape(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(IngestError):
        ensure_under(root, tmp_path / "outside")


def test_recipe_diff_detects_change():
    a = {"recipe_id": "a", "interval_s": 5, "questions": []}
    b = {"recipe_id": "b", "interval_s": 5, "questions": []}
    assert recipe_diff(a, b) == ["recipe_id: expected 'a', pack 'b'"]
    assert recipe_diff(a, a) == []
