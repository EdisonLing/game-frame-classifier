"""Locate ffmpeg/ffprobe and run them with argument lists only (never a shell)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

EXE_SUFFIX = ".exe" if os.name == "nt" else ""
ENV_DIR = "GFC_FFMPEG_DIR"
STRIPPED_ENV = ("FFREPORT",)
_OUT_TIME = re.compile(r"^out_time_us=(\d+)\s*$")
# Progress keys that only change when ffmpeg makes real progress (speed and bitrate drift with the clock).
_PROGRESS_KEYS = ("frame", "out_time_us", "total_size", "dup_frames", "drop_frames")
# No progress for this long means ffmpeg is stuck (for example a hung GPU driver). Sparse outputs
# (one still per 5 s of video) can legitimately go quiet for a while, so this is generous.
STALL_S = 300.0
_state = {"low_priority": False}


class FFmpegNotFoundError(RuntimeError):
    """No usable ffmpeg/ffprobe pair was found."""


class ToolError(RuntimeError):
    """ffmpeg or ffprobe failed, could not start, or timed out."""

    def __init__(self, message: str, returncode: int | None = None, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr_tail = stderr_tail


@dataclass(frozen=True)
class FFTools:
    ffmpeg: Path
    ffprobe: Path
    origin: str  # "bundled", "env" or "path"


def pack_root() -> Path:
    """Folder holding app/ (Frame Export Kit) or src/ (repo checkout)."""
    return Path(__file__).resolve().parents[3]


def _pair(directory: Path) -> tuple[Path, Path] | None:
    ffmpeg = directory / f"ffmpeg{EXE_SUFFIX}"
    ffprobe = directory / f"ffprobe{EXE_SUFFIX}"
    if ffmpeg.is_file() and ffprobe.is_file():
        return ffmpeg, ffprobe
    return None


def find_tools(*, bundled_only: bool = False) -> FFTools:
    """Bundled bin/ first, then GFC_FFMPEG_DIR, then PATH (bundled only in pack mode)."""
    bundled = _pair(pack_root() / "bin")
    if bundled:
        return FFTools(bundled[0], bundled[1], "bundled")
    if bundled_only:
        raise FFmpegNotFoundError("bin/ffmpeg and bin/ffprobe are missing")
    env_dir = os.environ.get(ENV_DIR)
    if env_dir:
        pair = _pair(Path(env_dir))
        if pair:
            return FFTools(pair[0], pair[1], "env")
        raise FFmpegNotFoundError(f"{ENV_DIR} has no ffmpeg/ffprobe")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return FFTools(Path(ffmpeg), Path(ffprobe), "path")
    raise FFmpegNotFoundError("ffmpeg/ffprobe not found in bin/, GFC_FFMPEG_DIR or PATH")


def set_low_priority(enabled: bool) -> None:
    """Run later ffmpeg/ffprobe processes at below-normal priority (Windows)."""
    _state["low_priority"] = enabled


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in STRIPPED_ENV:
        env.pop(key, None)
    return env


def _creationflags() -> int:
    if os.name == "nt" and _state["low_priority"]:
        return subprocess.BELOW_NORMAL_PRIORITY_CLASS
    return 0


def _argv(args: Sequence[object]) -> list[str]:
    return [os.fspath(a) if isinstance(a, os.PathLike) else str(a) for a in args]


def run_capture(args: Sequence[object], timeout: float = 120) -> subprocess.CompletedProcess[str]:
    name = Path(str(args[0])).name
    try:
        return subprocess.run(
            _argv(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            env=_child_env(),
            creationflags=_creationflags(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{name} timed out after {timeout:g} s") from exc
    except OSError as exc:
        raise ToolError(f"could not start {name}: {exc.strerror}") from exc


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", "replace").strip()


def run_ffmpeg(
    args: Sequence[object],
    *,
    stderr_path: Path,
    duration_s: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
    stall_s: float = STALL_S,
) -> None:
    """Run ffmpeg whose args include `-progress pipe:1`; stderr is saved to stderr_path.

    ffmpeg is killed and ToolError raised when its progress values stop changing for
    stall_s seconds, so a hung encoder or driver can't stop a run forever.
    """
    with open(stderr_path, "wb") as err:
        try:
            proc = subprocess.Popen(
                _argv(args),
                stdout=subprocess.PIPE,
                stderr=err,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_child_env(),
                creationflags=_creationflags(),
            )
        except OSError as exc:
            raise ToolError(f"could not start ffmpeg: {exc.strerror}") from exc
        state = {"last": time.monotonic(), "seen": {}}

        def read_progress() -> None:
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key in _PROGRESS_KEYS and state["seen"].get(key) != value:
                    state["seen"][key] = value
                    state["last"] = time.monotonic()
                match = _OUT_TIME.match(line)
                if match and on_progress is not None and duration_s > 0:
                    on_progress(min(1.0, int(match.group(1)) / 1_000_000 / duration_s))

        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        stalled = False
        try:
            while True:
                try:
                    code = proc.wait(timeout=1.0)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - state["last"] > stall_s:
                        stalled = True
                        proc.kill()
                        code = proc.wait()
                        break
            reader.join(timeout=5)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
    if stalled:
        raise ToolError(f"ffmpeg made no progress for {stall_s:g} s and was stopped", code, _tail(stderr_path))
    if code != 0:
        tail = _tail(stderr_path)
        last = tail.splitlines()[-1] if tail else "no error output"
        raise ToolError(f"ffmpeg exited with code {code}: {last}", code, tail)


def version_line(exe: Path) -> str:
    """Version token from `<exe> -version`, e.g. n8.1.3-35-gf1acb0a266-20261116."""
    proc = run_capture([exe, "-version"], timeout=30)
    first = proc.stdout.splitlines()[0] if proc.stdout else ""
    parts = first.split()
    return parts[2] if len(parts) >= 3 and parts[1] == "version" else first
