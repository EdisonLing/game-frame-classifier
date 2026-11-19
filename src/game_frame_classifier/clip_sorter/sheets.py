"""Contact-sheet generation and a small background worker."""

from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path

from game_frame_classifier.sourcing.ffbin import FFTools, ToolError, run_capture

from .scan import Clip


def sheet_path(session_dir: Path, quick_id: str) -> Path:
    return session_dir / "sheets" / f"{quick_id}.jpg"


def _blocks_sheet(problem: str) -> bool:
    """no_source is shown on the page but the clip is still viewable."""
    if not problem:
        return False
    return not problem.startswith("no_source")


def make_sheet(tools: FFTools, clip: Clip, out_path: Path) -> None:
    """Six frames at mid-bucket times, tiled 3×2 into out_path."""
    if _blocks_sheet(clip.problem) or clip.duration_s is None or clip.duration_s <= 0:
        raise ValueError(f"cannot make sheet for {clip.rel_path}: {clip.problem or 'no duration'}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = float(clip.duration_s)
    tmp = Path(tempfile.mkdtemp(prefix="gfc_sheet_"))
    try:
        frames: list[Path] = []
        for i in range(1, 7):
            t = duration * (i - 0.5) / 6.0
            frame = tmp / f"f{i}.jpg"
            cmd = [
                tools.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{t:.6f}",
                "-i",
                clip.path,
                "-frames:v",
                "1",
                "-vf",
                "scale=320:-2",
                frame,
            ]
            proc = run_capture(cmd, timeout=120)
            if proc.returncode != 0 or not frame.is_file():
                raise ToolError(
                    f"frame extract failed for {clip.rel_path} at t={t:.3f}",
                    returncode=proc.returncode,
                    stderr_tail=(proc.stderr or "")[-400:],
                )
            frames.append(frame)
        pattern = tmp / "f%d.jpg"
        cmd = [
            tools.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "1",
            "-start_number",
            "1",
            "-i",
            str(pattern),
            "-frames:v",
            "1",
            "-vf",
            "tile=3x2",
            out_path,
        ]
        proc = run_capture(cmd, timeout=60)
        if proc.returncode != 0 or not out_path.is_file():
            raise ToolError(
                f"tile failed for {clip.rel_path}",
                returncode=proc.returncode,
                stderr_tail=(proc.stderr or "")[-400:],
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class SheetWorker:
    """Two-thread worker that builds sheets ahead of the current clip."""

    def __init__(self, tools: FFTools, session_dir: Path, threads: int = 2) -> None:
        self.tools = tools
        self.session_dir = Path(session_dir)
        self.threads_n = threads
        self._order: list[Clip] = []
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._next = 0
        self._stop = False
        self._workers: list[threading.Thread] = []
        self._priority: int | None = None

    def start(self, order: list[Clip], current_index: int) -> None:
        with self._cond:
            self._order = list(order)
            self._next = max(0, min(current_index, len(self._order)))
            self._priority = self._next
            self._stop = False
        self._workers = [
            threading.Thread(target=self._run, name=f"sheet-worker-{i}", daemon=True)
            for i in range(self.threads_n)
        ]
        for t in self._workers:
            t.start()

    def prioritise(self, index: int) -> None:
        with self._cond:
            if 0 <= index < len(self._order):
                self._priority = index
                self._cond.notify_all()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        for t in self._workers:
            t.join(timeout=5)
        self._workers = []

    def _claim(self) -> Clip | None:
        with self._cond:
            while not self._stop:
                if self._priority is not None:
                    idx = self._priority
                    self._priority = None
                    if 0 <= idx < len(self._order):
                        clip = self._order[idx]
                        out = sheet_path(self.session_dir, clip.quick_id)
                        if not _blocks_sheet(clip.problem) and not out.is_file():
                            return clip
                # Walk from _next wrapping once through the list
                n = len(self._order)
                if n == 0:
                    return None
                start = self._next
                for offset in range(n):
                    idx = (start + offset) % n
                    clip = self._order[idx]
                    out = sheet_path(self.session_dir, clip.quick_id)
                    if _blocks_sheet(clip.problem) or out.is_file():
                        continue
                    self._next = (idx + 1) % n
                    return clip
                # Nothing left; wait for prioritise or stop
                self._cond.wait(timeout=1.0)
            return None

    def _run(self) -> None:
        while True:
            clip = self._claim()
            if clip is None:
                return
            out = sheet_path(self.session_dir, clip.quick_id)
            if out.is_file():
                continue
            try:
                make_sheet(self.tools, clip, out)
            except Exception:  # noqa: BLE001 — worker keeps going; page shows placeholder
                continue
