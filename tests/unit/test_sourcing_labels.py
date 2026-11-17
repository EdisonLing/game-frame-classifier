"""Label hints and name normalisation (Frame Export Kit spec §9, §4.2)."""

import pytest

from game_frame_classifier.sourcing.labels import label_hints, normalize_handle, normalize_other_name


@pytest.mark.parametrize(
    "text,expected",
    [
        ("D:/Videos/VALORANT/x.mp4", {"Valorant"}),
        ("League of Legends 2026.mp4", {"League_of_Legends"}),
        ("lol_clip.mp4", {"League_of_Legends"}),
        ("lollipop.mp4", set()),
        ("Counter-strike 2/clip.mp4", {"CS2"}),
        ("cs2_ace.mp4", {"CS2"}),
        ("Overwatch/x.mp4", {"Overwatch_2"}),
        ("Marvel Rivals/x.mp4", {"Marvel_Rivals"}),
        ("clip_730_20261102_211408.mp4", {"CS2"}),
        ("clip_2767030_20261102_211408.mp4", {"Marvel_Rivals"}),
        ("minecraft and valorant.mp4", {"Minecraft", "Valorant"}),
        ("gameplay.mp4", set()),
    ],
)
def test_label_hints(text, expected):
    assert label_hints(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [("Alex Smith-Jones!", "alex_smith_jones"), ("   ", ""), ("__x__", "x"), ("a" * 30, "a" * 24)],
)
def test_normalize_handle(text, expected):
    assert normalize_handle(text) == expected


@pytest.mark.parametrize("text,expected", [("Apex Legends", "Apex_Legends"), ("Rocket League!", "Rocket_League")])
def test_normalize_other_name(text, expected):
    assert normalize_other_name(text) == expected
