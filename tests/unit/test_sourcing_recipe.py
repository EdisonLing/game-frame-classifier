"""Recipe validation (friend-pack spec §4.1)."""

import json
from pathlib import Path

import pytest

from game_frame_classifier.sourcing.recipe import RecipeError, load_recipe, parse_crf_list, recipe_from_dict

ROOT = Path(__file__).resolve().parents[2]


def base() -> dict:
    return json.loads((ROOT / "config" / "recipe.json").read_text(encoding="utf-8"))


def test_repo_recipe_loads_with_spec_defaults():
    r = recipe_from_dict(base())
    assert r.interval_s == 5.0
    assert r.tiers == ("full", "crf45")
    assert r.frame_mode == "native"
    assert r.footage_budget_min == 180
    assert r.jpeg_qscale == 2
    assert r.compact_size == (256, 144)
    assert ".mp4" in r.video_extensions
    assert r.games[0] == "Valorant"


@pytest.mark.parametrize(
    "value,expected",
    [("45", (45,)), ("45,38", (38, 45)), (" 38 , 45 ,45", (38, 45)), ([45, "38"], (38, 45)), ("", ())],
)
def test_parse_crf_list(value, expected):
    assert parse_crf_list(value) == expected


@pytest.mark.parametrize("value", ["45.5", "abc", [True], "0", "52", 45])
def test_parse_crf_list_rejects(value):
    with pytest.raises(RecipeError):
        parse_crf_list(value)


def test_no_tiers_rejected():
    d = base()
    d["include_full"] = False
    d["crf_list"] = ""
    with pytest.raises(RecipeError, match="no tiers"):
        recipe_from_dict(d)


def test_unknown_field_rejected():
    d = base()
    d["intervall_s"] = 5
    with pytest.raises(RecipeError, match="unknown field"):
        recipe_from_dict(d)


def test_missing_field_rejected():
    d = base()
    del d["games"]
    with pytest.raises(RecipeError, match="missing field"):
        recipe_from_dict(d)


@pytest.mark.parametrize(
    "key,value",
    [
        ("interval_s", 0.1),
        ("interval_s", True),
        ("jpeg_qscale", 1),
        ("frame_mode", "tiny"),
        ("x264_preset", "turbo"),
        ("footage_budget_min", -1),
        ("compact_size", [255, 144]),
        ("video_extensions", ["mp4"]),
        ("games", ["Valorant", "Other"]),
    ],
)
def test_invalid_values(key, value):
    d = base()
    d[key] = value
    with pytest.raises(RecipeError):
        recipe_from_dict(d)


def test_question_default_must_be_a_choice():
    d = base()
    d["questions"]["all"][0]["default"] = "maybe"
    with pytest.raises(RecipeError):
        recipe_from_dict(d)


def test_overrides_apply():
    r = recipe_from_dict(base(), {"frame_mode": "compact", "footage_budget_min": 0})
    assert r.frame_mode == "compact" and r.footage_budget_min == 0


def test_manifest_snapshot():
    m = recipe_from_dict(base()).to_manifest()
    assert m["sampler"] == "bucket_v1"
    assert m["crf_list"] == [45]
    assert m["tiers"] == ["full", "crf45"]
    assert m["schema"] == "gfc.recipe/1"


def test_load_recipe_bad_json(tmp_path):
    p = tmp_path / "recipe.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(RecipeError, match="not valid JSON"):
        load_recipe(p)
