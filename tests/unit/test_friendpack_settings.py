"""Tool-folder confinement, user/history files, run log sanitising and formatting."""

import json

import pytest

from game_frame_classifier.friendpack import paths, settings
from game_frame_classifier.friendpack.paths import UnsafePathError
from game_frame_classifier.friendpack.run import RunLog, fmt_bytes, fmt_duration


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "tool"
    h.mkdir()
    monkeypatch.setattr(paths, "app_home", lambda: h)
    return h


def test_ensure_inside_home_accepts_children(home):
    target = home / "output" / "x.zip"
    assert paths.ensure_inside_home(target) == target.resolve()


@pytest.mark.parametrize("rel", ["../elsewhere.json", "output/../../elsewhere.json"])
def test_ensure_inside_home_rejects_escape(home, rel):
    with pytest.raises(UnsafePathError):
        paths.ensure_inside_home(home / rel)


def test_atomic_write_refuses_outside(home, tmp_path):
    with pytest.raises(UnsafePathError):
        settings.atomic_write_json(tmp_path / "elsewhere.json", {})
    assert not (tmp_path / "elsewhere.json").exists()


def test_user_round_trip(home):
    user = settings.new_user("alex", False)
    settings.save_user(user)
    data = json.loads((home / "config" / "user.json").read_text(encoding="utf-8"))
    assert list(data)[0] == "schema" and data["schema"] == "gfc.user/1" and data["handle"] == "alex"
    assert settings.load_user() == user
    assert not (home / "config" / "user.json.tmp").exists()


def test_user_without_consent_is_ignored(home):
    (home / "config").mkdir()
    (home / "config" / "user.json").write_text(
        json.dumps({"schema": "gfc.user/1", "contributor_id": "x", "handle": "alex", "consent_data_use": False}),
        encoding="utf-8",
    )
    assert settings.load_user() is None


def test_history_round_trip(home):
    assert settings.load_history() == {}
    settings.save_history({"abc": {"game": "CS2"}})
    assert settings.load_history() == {"abc": {"game": "CS2"}}


def test_run_log_hides_paths(home, tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    monkeypatch.setenv("USERPROFILE", str(profile))
    root = profile / "Videos" / "VALORANT"
    log = RunLog(home / "output" / "run_log.txt", root)
    forward = str(root).replace("\\", "/")
    log.write(f"a {root}\\x.mp4 b {forward}/y.mp4 c {profile}\\AppData d {home.resolve()}\\bin")
    text = (home / "output" / "run_log.txt").read_text(encoding="utf-8")
    assert "<input>\\x.mp4" in text and "<input>/y.mp4" in text
    assert "%USERPROFILE%\\AppData" in text and "<tool>\\bin" in text
    assert str(tmp_path) not in text


@pytest.mark.parametrize(
    "seconds,text",
    [(10, "under 1 min"), (60, "1 min"), (3600, "1 h 0 min"), (10800, "3 h 0 min"), (5400, "1 h 30 min")],
)
def test_fmt_duration(seconds, text):
    assert fmt_duration(seconds) == text


@pytest.mark.parametrize(
    "n,text",
    [(512 * 1024, "512 KB"), (5 << 20, "5 MB"), (int(1.5 * (1 << 30)), "1.5 GB")],
)
def test_fmt_bytes(n, text):
    assert fmt_bytes(n) == text
