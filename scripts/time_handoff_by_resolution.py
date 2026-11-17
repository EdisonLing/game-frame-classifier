"""Time the Frame Export Kit recipe per resolution on simulated recordings.

make-sources: cut one minute (60-120 s) from each clip under data/raw/<game>/
and re-encode it as a typical gameplay recording: 60 fps H.264 at the NVIDIA
App "High" preset bitrates (1080p 16.2 Mbps, 1440p 28.8 Mbps, 2160p 50 Mbps).

time: run the Frame Export Kit steps on each simulated recording, one resolution
at a time, and report wall seconds per minute of footage plus still sizes:
  1. SHA-256 of the file
  2. full tier: bucket select @ 1/5 s -> JPEG q2
  3. CRF 45 re-encode (libx264 veryfast, yuv420p, passthrough)
  4. crf45 tier: same select on the re-encode

Run `time` with the machine otherwise idle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "bench_handoff" / "sim_recordings"
PROFILES = {
    "1080p": (1920, 1080, "16.2M"),
    "1440p": (2560, 1440, "28.8M"),
    "2160p": (3840, 2160, "50M"),
}
FPS = 60
CUT_START_S, CUT_LEN_S = 60, 60
EXPR = (
    "gte(t\\,0)*(isnan(prev_selected_t)+gt(floor((t+0.008333)/5)\\,"
    "floor((prev_selected_t+0.008333)/5)))"
)


def run(cmd: list[str]) -> float:
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-4000:])
        raise SystemExit("ffmpeg failed")
    return time.perf_counter() - t0


def make_sources(game: str) -> None:
    clips = sorted((ROOT / "data" / "raw" / game).rglob("*.mp4"))
    names = list(PROFILES)
    for k, clip in enumerate(clips):
        graph = [f"[0:v]fps={FPS},split={len(names)}" + "".join(f"[s{n}]" for n in names)]
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
               "-ss", str(CUT_START_S), "-t", str(CUT_LEN_S), "-i", str(clip)]
        maps = []
        for n in names:
            w, h, rate = PROFILES[n]
            graph.append(f"[s{n}]scale={w}:{h}:flags=lanczos[o{n}]")
            dest = OUT / n / f"clip{k:02d}.mp4"
            dest.parent.mkdir(parents=True, exist_ok=True)
            maps += ["-map", f"[o{n}]", "-an", "-c:v", "libx264", "-preset", "faster",
                     "-b:v", rate, "-maxrate", rate, "-bufsize", rate, "-g", str(2 * FPS),
                     "-pix_fmt", "yuv420p", str(dest)]
        run(cmd + ["-filter_complex", ";".join(graph)] + maps)
        print(f"clip{k:02d} done", flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def time_profile(name: str) -> dict:
    srcs = sorted((OUT / name).glob("clip*.mp4"))
    work = OUT / f"_work_{name}"
    steps = {"hash": 0.0, "full_extract": 0.0, "crf_encode": 0.0, "crf_extract": 0.0}
    footage = src_bytes = 0.0
    full_sizes: list[int] = []
    crf_sizes: list[int] = []
    for src in srcs:
        footage += duration(src)
        src_bytes += src.stat().st_size
        full_dir, crf_dir = work / src.stem / "full", work / src.stem / "crf45"
        full_dir.mkdir(parents=True, exist_ok=True)
        crf_dir.mkdir(parents=True, exist_ok=True)
        tmp = work / src.stem / "tmp_crf45.mp4"

        t0 = time.perf_counter()
        sha256(src)
        steps["hash"] += time.perf_counter() - t0
        base = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
        steps["full_extract"] += run(base + [
            "-i", str(src), "-map", "0:v:0", "-an", "-vf", f"select='{EXPR}',showinfo",
            "-fps_mode", "passthrough", "-q:v", "2", "-start_number", "0", str(full_dir / "%06d.jpg")])
        steps["crf_encode"] += run(base + [
            "-i", str(src), "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "45", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", str(tmp)])
        steps["crf_extract"] += run(base + [
            "-i", str(tmp), "-vf", f"select='{EXPR}',showinfo",
            "-fps_mode", "passthrough", "-q:v", "2", "-start_number", "0", str(crf_dir / "%06d.jpg")])
        tmp.unlink()
        full_sizes += [p.stat().st_size for p in full_dir.glob("*.jpg")]
        crf_sizes += [p.stat().st_size for p in crf_dir.glob("*.jpg")]

    total = sum(steps.values())
    minutes = footage / 60
    return {
        "clips": len(srcs),
        "footage_s": footage,
        "source_mbps": src_bytes * 8 / footage / 1e6,
        "source_bytes_per_5s": src_bytes / footage * 5,
        "steps_s": {k: round(v, 2) for k, v in steps.items()},
        "total_s": round(total, 2),
        "s_per_footage_min": total / minutes,
        "steps_s_per_footage_min": {k: v / minutes for k, v in steps.items()},
        "slots": len(full_sizes),
        "full_mean_bytes": statistics.fmean(full_sizes),
        "crf45_mean_bytes": statistics.fmean(crf_sizes),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["make-sources", "time"])
    ap.add_argument("--game", default="Valorant")
    args = ap.parse_args()

    if args.command == "make-sources":
        make_sources(args.game)
        return 0

    ffmpeg_version = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    results = {
        "ffmpeg": ffmpeg_version,
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "profiles": {},
    }
    for name in PROFILES:
        r = time_profile(name)
        results["profiles"][name] = r
        slot = r["full_mean_bytes"] + r["crf45_mean_bytes"]
        print(f"{name}: {r['s_per_footage_min']:.1f} s per footage minute "
              f"({ {k: round(v, 1) for k, v in r['steps_s_per_footage_min'].items()} }); "
              f"source {r['source_mbps']:.1f} Mbps; slot {slot / 1024:.0f} KiB "
              f"(full {r['full_mean_bytes'] / 1024:.0f}, crf45 {r['crf45_mean_bytes'] / 1024:.0f}); "
              f"{r['slots']} slots", flush=True)
    (OUT / "timing_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
