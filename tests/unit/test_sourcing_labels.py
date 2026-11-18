"""Label hints and name normalisation (Frame Export Kit spec §9, §4.2)."""

import pytest

from game_frame_classifier.sourcing.labels import (
    MIXED_OTHER_NAME,
    OTHER,
    classify_mixed_filename,
    label_hints,
    normalize_handle,
    normalize_other_name,
    parse_title_timestamp_v1,
)


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


@pytest.mark.parametrize(
    "filename,title",
    [
        ("Counter-Strike-Global-Offensive__2022-04-26__21-46-23.mp4", "Counter-Strike-Global-Offensive"),
        ("VALORANT__2023-01-13__20-24-43.mp4", "VALORANT"),
        ("Dead by Daylight__2023-08-16__17-34-04.mp4", "Dead by Daylight"),
        ("Desktop__2024-01-01__12-00-00.mkv", "Desktop"),
        ("Tom-Clancy's-Rainbow-Six-Siege__2024-01-14__23-42-42.mp4", "Tom-Clancy's-Rainbow-Six-Siege"),
    ],
)
def test_parse_title_timestamp_v1_ok(filename, title):
    assert parse_title_timestamp_v1(filename) == title


@pytest.mark.parametrize(
    "filename",
    [
        "VALORANT 2023.01.13 - 20.24.43.mp4",
        "clip.mp4",
        "VALORANT__2023-01-13.mp4",
        "VALORANT__2023-01-13__20-24.mp4",
        "__2023-01-13__20-24-43.mp4",
        "no-date__only-one-part.mp4",
    ],
)
def test_parse_title_timestamp_v1_rejects(filename):
    assert parse_title_timestamp_v1(filename) is None


@pytest.mark.parametrize(
    "filename,game",
    [
        ("VALORANT__2023-01-13__20-24-43.mp4", "Valorant"),
        ("Counter-Strike-Global-Offensive__2022-04-26__21-46-23.mp4", "CS2"),
        ("cs2__2022-04-26__21-46-23.mp4", "CS2"),
        ("League-of-Legends__2022-04-26__21-46-23.mp4", "League_of_Legends"),
        ("Minecraft__2022-04-26__21-46-23.mp4", "Minecraft"),
        ("Overwatch__2022-04-26__21-46-23.mp4", "Overwatch_2"),
        ("Marvel-Rivals__2022-04-26__21-46-23.mp4", "Marvel_Rivals"),
    ],
)
def test_classify_mixed_filename_target_games(filename, game):
    result = classify_mixed_filename(filename)
    assert result.game == game
    assert result.detail == ""
    assert result.title


def test_classify_mixed_filename_other():
    result = classify_mixed_filename("Project-Zomboid__2022-12-13__00-59-15.mp4")
    assert result.game == OTHER
    assert result.detail == ""
    assert result.title == "Project-Zomboid"
    assert MIXED_OTHER_NAME == "mixed_other"


def test_classify_mixed_filename_unsupported():
    result = classify_mixed_filename("VALORANT 2023.01.13 - 20.24.43.mp4")
    assert result.game == ""
    assert result.detail == "unsupported_mixed_filename_format"


def test_classify_mixed_filename_conflict():
    result = classify_mixed_filename("minecraft-and-valorant__2022-04-26__21-46-23.mp4")
    assert result.game == ""
    assert result.detail == "mixed_label_conflict"
    assert result.title == "minecraft-and-valorant"
