"""Pad-to-16:9 and scale filter (D27)."""

import json
from pathlib import Path

import pytest

from game_frame_classifier.sourcing.derive import derive_filter, pad_dims
from game_frame_classifier.sourcing.recipe import recipe_from_dict

ROOT = Path(__file__).resolve().parents[2]
RECIPE = recipe_from_dict(json.loads((ROOT / "config" / "recipe.json").read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "w,h,expected",
    [
        (1920, 1080, None),
        (1366, 768, None),
        (2560, 1440, None),
        (2560, 1080, (2560, 1440)),
        (3440, 1440, (3440, 1936)),
        (1280, 960, (1708, 960)),
        (1440, 1080, (1920, 1080)),
        (1920, 1200, (2134, 1200)),
    ],
)
def test_pad_dims(w, h, expected):
    assert pad_dims(w, h, 0.01) == expected


def test_filter_without_pad():
    assert derive_filter(1920, 1080, RECIPE) == "scale=256:144:flags=bicubic"


def test_filter_letterbox():
    assert derive_filter(2560, 1080, RECIPE) == "pad=2560:1440:0:180:black,scale=256:144:flags=bicubic"


def test_filter_pillarbox():
    assert derive_filter(1440, 1080, RECIPE) == "pad=1920:1080:240:0:black,scale=256:144:flags=bicubic"
