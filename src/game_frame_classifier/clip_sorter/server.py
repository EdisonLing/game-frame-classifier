"""Local ThreadingHTTPServer for the clip sorter page and JSON API."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from game_frame_classifier.sourcing.labels import GAMES, OTHER, normalize_other_name

from .scan import Clip
from .sheets import SheetWorker, sheet_path
from .store import append, first_undecided, last_decision_quick_id, other_names, replay

PAGE_PATH = Path(__file__).with_name("page.html")
VALID_DECISIONS = frozenset({"label", "disabled", "trash", "skip"})


class Session:
    def __init__(
        self,
        session_dir: Path,
        clips: list[Clip],
        worker: SheetWorker,
    ) -> None:
        self.session_dir = Path(session_dir)
        self.clips = clips
        self.worker = worker
        self.lock = threading.Lock()
        self.current = first_undecided(clips, replay(session_dir))


def _clip_payload(session: Session, i: int, state: dict[str, dict[str, Any]]) -> dict[str, Any]:
    clip = session.clips[i]
    entry = state.get(clip.quick_id) or {}
    decision = entry.get("decision") or ""
    if decision == "skip":
        decision = ""  # skip is undecided for the UI
    ready = sheet_path(session.session_dir, clip.quick_id).is_file()
    return {
        "i": i,
        "rel_path": clip.rel_path,
        "duration_s": clip.duration_s,
        "width": clip.width,
        "height": clip.height,
        "problem": clip.problem,
        "suggestion": clip.suggestion,
        "other_name": entry.get("other_name") or clip.other_name,
        "origin": clip.suggestion_origin,
        "decision": decision,
        "game": entry.get("game") or "",
        "sheet_ready": ready,
        "quick_id": clip.quick_id,
    }


def build_state(session: Session) -> dict[str, Any]:
    state = replay(session.session_dir)
    return {
        "clips": [_clip_payload(session, i, state) for i in range(len(session.clips))],
        "games": list(GAMES),
        "other_names": other_names(state),
        "current": session.current,
    }


def make_handler(session: Session) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload: Any) -> None:
            data = json.dumps(payload).encode("utf-8")
            self._send(code, data, "application/json; charset=utf-8")

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError("invalid JSON") from exc
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            return data

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/":
                body = PAGE_PATH.read_bytes()
                self._send(200, body, "text/html; charset=utf-8")
                return
            if path == "/api/state":
                with session.lock:
                    self._json(200, build_state(session))
                return
            if path.startswith("/sheet/") and path.endswith(".jpg"):
                qid = path[len("/sheet/") : -len(".jpg")]
                if not qid or "/" in qid or "\\" in qid or ".." in qid:
                    self._send(404, b"not found", "text/plain")
                    return
                img = sheet_path(session.session_dir, qid)
                if not img.is_file():
                    self._send(404, b"not found", "text/plain")
                    return
                self._send(200, img.read_bytes(), "image/jpeg")
                return
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                data = self._read_json()
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            if path == "/api/decide":
                self._decide(data)
                return
            if path == "/api/undo":
                self._undo()
                return
            if path == "/api/open":
                self._open(data)
                return
            if path == "/api/current":
                self._current(data)
                return
            self._json(404, {"error": "not found"})

        def _decide(self, data: dict[str, Any]) -> None:
            try:
                i = int(data["i"])
            except (KeyError, TypeError, ValueError):
                self._json(400, {"error": "i required"})
                return
            if i < 0 or i >= len(session.clips):
                self._json(400, {"error": "i out of range"})
                return
            decision = str(data.get("decision") or "")
            if decision not in VALID_DECISIONS:
                self._json(400, {"error": "invalid decision"})
                return
            game = str(data.get("game") or "")
            other_name = str(data.get("other_name") or "")
            clip = session.clips[i]
            if decision == "label":
                if clip.problem:
                    self._json(400, {"error": "clip has a problem and cannot be labelled"})
                    return
                if game == OTHER:
                    other_name = normalize_other_name(other_name)
                    if not other_name:
                        self._json(400, {"error": "other_name required"})
                        return
                elif game not in GAMES:
                    self._json(400, {"error": "invalid game"})
                    return
                else:
                    other_name = ""
            else:
                game = ""
                other_name = ""
            with session.lock:
                append(
                    session.session_dir,
                    clip.quick_id,
                    clip.rel_path,
                    decision,
                    game=game,
                    other_name=other_name,
                )
                # advance to next clip
                nxt = i + 1
                if nxt >= len(session.clips):
                    nxt = first_undecided(session.clips, replay(session.session_dir))
                session.current = nxt
                session.worker.prioritise(session.current)
                state = replay(session.session_dir)
                payload = _clip_payload(session, i, state)
                payload["current"] = session.current
                self._json(200, payload)

        def _undo(self) -> None:
            with session.lock:
                qid = last_decision_quick_id(session.session_dir)
                if not qid:
                    self._json(400, {"error": "nothing to undo"})
                    return
                clip = next((c for c in session.clips if c.quick_id == qid), None)
                rel = clip.rel_path if clip else ""
                append(session.session_dir, qid, rel, "undo")
                state = replay(session.session_dir)
                if clip is not None:
                    session.current = session.clips.index(clip)
                    session.worker.prioritise(session.current)
                self._json(200, build_state(session) if True else state)

        def _open(self, data: dict[str, Any]) -> None:
            try:
                i = int(data["i"])
            except (KeyError, TypeError, ValueError):
                self._json(400, {"error": "i required"})
                return
            if i < 0 or i >= len(session.clips):
                self._json(400, {"error": "i out of range"})
                return
            path = session.clips[i].path
            try:
                if os.name == "nt":
                    os.startfile(path)  # type: ignore[attr-defined]
                elif sys_platform_is_darwin():
                    subprocess.Popen(["open", str(path)], stdin=subprocess.DEVNULL)
                else:
                    subprocess.Popen(["xdg-open", str(path)], stdin=subprocess.DEVNULL)
            except OSError as exc:
                self._json(500, {"error": str(exc)})
                return
            self._json(200, {"ok": True})

        def _current(self, data: dict[str, Any]) -> None:
            try:
                i = int(data["i"])
            except (KeyError, TypeError, ValueError):
                self._json(400, {"error": "i required"})
                return
            if i < 0 or i >= len(session.clips):
                self._json(400, {"error": "i out of range"})
                return
            with session.lock:
                session.current = i
                session.worker.prioritise(i)
            self._json(200, {"current": i})

    return Handler


def sys_platform_is_darwin() -> bool:
    return os.name == "posix" and sys_uname_system() == "Darwin"


def sys_uname_system() -> str:
    import platform

    return platform.system()


def serve(
    session: Session,
    clips: list[Clip],
    worker: SheetWorker,
    port: int,
    open_browser: bool,
) -> None:
    """Bind 127.0.0.1:port (or next free if port taken when port!=0) and serve forever."""
    # session already carries clips/worker; keep signature as in the build instructions
    _ = clips, worker
    handler = make_handler(session)
    bound_port = port
    httpd: ThreadingHTTPServer | None = None
    if port == 0:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        bound_port = httpd.server_address[1]
    else:
        for candidate in range(port, port + 50):
            try:
                httpd = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
                bound_port = candidate
                break
            except OSError:
                continue
        if httpd is None:
            raise OSError(f"no free port near {port}")
    url = f"http://127.0.0.1:{bound_port}/"
    print(f"clip sorter: {url}  ({len(session.clips)} clips)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…", flush=True)
    finally:
        httpd.shutdown()
        worker.stop()
