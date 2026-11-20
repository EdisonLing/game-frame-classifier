"""Local keep/skip preview page for channel sampling."""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .sample import SampleCandidate

PAGE_PATH = Path(__file__).with_name("preview.html")


def thumbnail_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _payload(candidates: list[SampleCandidate]) -> dict[str, Any]:
    items = []
    for i, c in enumerate(candidates):
        items.append(
            {
                "i": i,
                "id": c.video_id,
                "title": c.title,
                "duration_s": c.duration_s,
                "url": c.url,
                "thumb": thumbnail_url(c.video_id),
                "on": True,
            }
        )
    return {"items": items}


def run_preview(
    candidates: list[SampleCandidate],
    *,
    open_browser: bool = True,
    port: int = 0,
) -> list[str]:
    """Open the preview page; block until Enter/submit. Return kept video ids."""
    if not candidates:
        return []

    result: dict[str, list[str]] = {"kept": [c.video_id for c in candidates]}
    done = threading.Event()
    state = _payload(candidates)

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

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                body = PAGE_PATH.read_bytes()
                self._send(200, body, "text/html; charset=utf-8")
                return
            if path == "/api/state":
                self._json(200, state)
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "bad json"})
                return
            if path == "/api/submit":
                kept = data.get("kept")
                if not isinstance(kept, list):
                    self._json(400, {"error": "kept must be a list"})
                    return
                ids = [str(x) for x in kept]
                valid = {c.video_id for c in candidates}
                result["kept"] = [i for i in ids if i in valid]
                self._json(200, {"ok": True})
                done.set()
                threading.Thread(target=httpd.shutdown, daemon=True).start()
                return
            self._json(404, {"error": "not found"})

    httpd: ThreadingHTTPServer | None = None
    if port == 0:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    else:
        for candidate in range(port, port + 50):
            try:
                httpd = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
                break
            except OSError:
                continue
        if httpd is None:
            raise OSError(f"no free port near {port}")

    bound = httpd.server_address[1]
    url = f"http://127.0.0.1:{bound}/"
    print(f"sample preview: {url}  ({len(candidates)} videos)", flush=True)
    print("  Digits 1-9,0 toggle; [ ] pages; Enter submits. Toggled-off are skipped.", flush=True)
    if open_browser:
        webbrowser.open(url)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    done.wait()
    httpd.server_close()
    return result["kept"]
