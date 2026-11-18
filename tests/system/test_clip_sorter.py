"""System test: sheets, HTTP API, apply into data/raw/ and _archive/."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from game_frame_classifier.clip_sorter.apply import plan, run
from game_frame_classifier.clip_sorter.scan import scan
from game_frame_classifier.clip_sorter.server import Session, make_handler
from game_frame_classifier.clip_sorter.sheets import SheetWorker, make_sheet, sheet_path
from game_frame_classifier.sourcing.ffbin import find_tools
from game_frame_classifier.sourcing.recipe import load_recipe
from tests.helpers.ffmpeg_fixtures import make_testsrc_video, requires_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "config" / "recipe.json"


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


@requires_ffmpeg
def test_sheet_is_3x2_960x360(tmp_path):
    clip_path = make_testsrc_video(tmp_path / "c.mp4", duration_s=3.0, width=640, height=360)
    tools = find_tools()
    recipe = load_recipe(RECIPE)
    clips = scan(tmp_path, recipe, tools, {})
    out = tmp_path / "sheet.jpg"
    make_sheet(tools, clips[0], out)
    img = Image.open(out)
    assert img.size == (960, 360)


@requires_ffmpeg
def test_server_decide_undo_and_apply(tmp_path):
    folder = tmp_path / "inbox"
    data_root = tmp_path / "data"
    session_dir = data_root / "sorting" / "sys"
    session_dir.mkdir(parents=True)
    make_testsrc_video(folder / "a_label.mp4", duration_s=2.5)
    make_testsrc_video(folder / "b_trash.mp4", duration_s=2.5)
    make_testsrc_video(folder / "c_other.mp4", duration_s=2.5)
    tools = find_tools()
    recipe = load_recipe(RECIPE)
    clips = scan(folder, recipe, tools, {})
    assert [c.rel_path for c in clips] == ["a_label.mp4", "b_trash.mp4", "c_other.mp4"]

    worker = SheetWorker(tools, session_dir, threads=2)
    worker.start(clips, 0)
    deadline = time.time() + 30
    while time.time() < deadline:
        if sheet_path(session_dir, clips[0].quick_id).is_file():
            break
        time.sleep(0.2)
    assert sheet_path(session_dir, clips[0].quick_id).is_file()

    session = Session(session_dir, clips, worker)
    handler = make_handler(session)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        state = _get(f"{base}/api/state")
        assert len(state["clips"]) == 3
        assert state["games"][0] == "Valorant"

        r = _post(f"{base}/api/decide", {"i": 0, "decision": "label", "game": "Valorant"})
        assert r["decision"] == "label"
        assert r["game"] == "Valorant"
        assert r["current"] == 1

        _post(f"{base}/api/decide", {"i": 1, "decision": "trash"})
        state = _get(f"{base}/api/state")
        assert state["clips"][1]["decision"] == "trash"

        state = _post(f"{base}/api/undo", {})
        assert not state["clips"][1]["decision"]
        _post(f"{base}/api/decide", {"i": 1, "decision": "trash"})
        _post(
            f"{base}/api/decide",
            {"i": 2, "decision": "label", "game": "Other", "other_name": "desktop"},
        )

        qid = clips[0].quick_id
        with urllib.request.urlopen(f"{base}/sheet/{qid}.jpg", timeout=10) as resp:
            assert resp.headers.get_content_type() == "image/jpeg"
            assert len(resp.read()) > 100
    finally:
        httpd.shutdown()
        worker.stop()

    actions = plan(session_dir, folder, clips, "tester", data_root)
    report = run(actions, dry_run=False)
    assert (data_root / "raw" / "Valorant" / "tester" / "a_label.mp4").is_file()
    assert (data_root / "raw" / "_other" / "desktop" / "tester" / "c_other.mp4").is_file()
    assert (folder / "_archive" / "b_trash.mp4").is_file()
    assert report["counts"]["copied"] == 2
    assert report["counts"]["trashed"] == 1
