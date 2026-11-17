"""Measure Frame Export Kit still sizes vs source video, by resolution.

Runs the Frame Export Kit recipe (bucket sampler @ 1/5 s, full + CRF 45 video
re-encode, JPEG q2) on every clip under data/raw/<game>/, at 2160p (native),
1440p and 1080p (lanczos downscale of the same decoded frames), plus compact
256x144 derived from the 1080p stills. Each clip is decoded once.

Output: data/bench_handoff/<run>/ (images + results.json) and a printed table.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLUTIONS = {"2160p": (3840, 2160), "1440p": (2560, 1440), "1080p": (1920, 1080)}
INTERVAL_S = 5.0
CRF = 45
JPEG_Q = 2


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    num, den = (int(x) for x in v["avg_frame_rate"].split("/"))
    return {
        "codec": v["codec_name"],
        "width": v["width"],
        "height": v["height"],
        "avg_fps": num / den if den else 0.0,
        "duration_s": float(data["format"]["duration"]),
        "bit_rate": int(data["format"]["bit_rate"]),
        "bytes": path.stat().st_size,
    }


def select_expr(fps: float) -> str:
    off = 0.5 / (fps if 10 <= fps <= 240 else 60.0)
    i = INTERVAL_S
    return (
        f"gte(t\\,0)*(isnan(prev_selected_t)+gt(floor((t+{off:.6f})/{i})\\,"
        f"floor((prev_selected_t+{off:.6f})/{i})))"
    )


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-4000:])
        raise SystemExit(f"ffmpeg failed: {' '.join(cmd[:6])} ...")


def process_clip(clip: Path, meta: dict, out: Path, seconds: float | None) -> dict:
    expr = select_expr(meta["avg_fps"])
    names = list(RESOLUTIONS)
    graph = [f"[0:v]split={len(names)}" + "".join(f"[s{n}]" for n in names)]
    for n in names:
        w, h = RESOLUTIONS[n]
        src = f"[s{n}]"
        if (w, h) != (meta["width"], meta["height"]):
            graph.append(f"{src}scale={w}:{h}:flags=lanczos[v{n}]")
            src = f"[v{n}]"
        graph.append(f"{src}split[f{n}][e{n}]")
        graph.append(f"[f{n}]select='{expr}'[o{n}]")

    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-i", str(clip), "-filter_complex", ";".join(graph)]
    for n in names:
        full_dir = out / n / "full"
        full_dir.mkdir(parents=True, exist_ok=True)
        cmd += ["-map", f"[o{n}]", "-fps_mode", "passthrough", "-q:v", str(JPEG_Q),
                "-start_number", "0", str(full_dir / "%06d.jpg")]
        cmd += ["-map", f"[e{n}]", "-an", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", str(CRF), "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
                str(out / n / f"tmp_crf{CRF}.mp4")]
    t0 = time.perf_counter()
    run(cmd)
    t_main = time.perf_counter() - t0

    crf_video_bytes = {}
    for n in names:
        tmp = out / n / f"tmp_crf{CRF}.mp4"
        crf_dir = out / n / f"crf{CRF}"
        crf_dir.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(tmp),
             "-vf", f"select='{expr}'", "-fps_mode", "passthrough", "-q:v", str(JPEG_Q),
             "-start_number", "0", str(crf_dir / "%06d.jpg")])
        crf_video_bytes[n] = tmp.stat().st_size
        tmp.unlink()

    compact = out / "compact_256x144" / "full"
    compact.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
         "-start_number", "0", "-i", str(out / "1080p" / "full" / "%06d.jpg"),
         "-vf", "scale=256:144:flags=bicubic", "-fps_mode", "passthrough", "-q:v", str(JPEG_Q),
         "-start_number", "0", str(compact / "%06d.jpg")])
    compact_crf = out / "compact_256x144" / f"crf{CRF}"
    compact_crf.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
         "-start_number", "0", "-i", str(out / "1080p" / f"crf{CRF}" / "%06d.jpg"),
         "-vf", "scale=256:144:flags=bicubic", "-fps_mode", "passthrough", "-q:v", str(JPEG_Q),
         "-start_number", "0", str(compact_crf / "%06d.jpg")])

    return {"main_pass_s": round(t_main, 1), "crf_video_bytes": crf_video_bytes}


def sizes(folder: Path) -> list[int]:
    return sorted(p.stat().st_size for p in folder.glob("*.jpg"))


def summarize(values: list[int]) -> dict:
    values = sorted(values)
    n = len(values)
    return {
        "n": n,
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p10": values[max(0, math.ceil(0.1 * n) - 1)],
        "p90": values[max(0, math.ceil(0.9 * n) - 1)],
        "min": values[0],
        "max": values[-1],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", default="Valorant")
    ap.add_argument("--seconds", type=float, default=None, help="limit each clip (quick test)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "bench_handoff" / "run")
    args = ap.parse_args()

    clips = sorted((ROOT / "data" / "raw" / args.game).rglob("*.mp4"))
    if not clips:
        raise SystemExit("no clips found")
    ffmpeg_version = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]

    per_clip = []
    for k, clip in enumerate(clips):
        meta = probe(clip)
        out = args.out / f"clip{k:02d}"
        info = process_clip(clip, meta, out, args.seconds)
        dur = min(meta["duration_s"], args.seconds) if args.seconds else meta["duration_s"]
        per_clip.append({"clip": f"clip{k:02d}", **meta, "measured_duration_s": dur, **info})
        print(f"clip{k:02d}: {meta['width']}x{meta['height']} {meta['codec']} "
              f"{meta['avg_fps']:.1f} fps {dur:.0f}s  main pass {info['main_pass_s']}s", flush=True)

    tiers = ["full", f"crf{CRF}"]
    sets = {n: {} for n in [*RESOLUTIONS, "compact_256x144"]}
    for n in sets:
        for t in tiers:
            vals = []
            for c in per_clip:
                vals += sizes(args.out / c["clip"] / n / t)
            sets[n][t] = summarize(vals)
        counts = {sets[n][t]["n"] for t in tiers}
        if len(counts) != 1:
            raise SystemExit(f"tier counts differ at {n}: {counts}")

    total_dur = sum(c["measured_duration_s"] for c in per_clip)
    if args.seconds:
        master_bytes = sum(c["bit_rate"] / 8 * c["measured_duration_s"] for c in per_clip)
    else:
        master_bytes = sum(c["bytes"] for c in per_clip)
    results = {
        "game": args.game,
        "clips": len(per_clip),
        "footage_s": total_dur,
        "ffmpeg": ffmpeg_version,
        "recipe": {"interval_s": INTERVAL_S, "tiers": tiers, "x264_preset": "veryfast",
                   "jpeg_qscale": JPEG_Q, "downscale": "lanczos from decoded 2160p",
                   "compact": "bicubic 256x144 from 1080p stills"},
        "master_bytes_per_5s": master_bytes / total_dur * INTERVAL_S,
        "master_mbps": master_bytes * 8 / total_dur / 1e6,
        "stills": sets,
        "crf_video_mbps": {n: sum(c["crf_video_bytes"][n] for c in per_clip) * 8 / total_dur / 1e6
                           for n in RESOLUTIONS},
        "per_clip": per_clip,
    }
    (args.out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(f"\nfootage {total_dur / 60:.1f} min, master {results['master_mbps']:.1f} Mbps "
          f"= {results['master_bytes_per_5s'] / 1024:.0f} KiB per 5 s")
    print(f"{'set':<16}{'full KiB':>10}{'crf45 KiB':>11}{'slot KiB':>10}{'MiB/min':>9}{'slots':>7}")
    for n, d in sets.items():
        slot = d["full"]["mean"] + d[f"crf{CRF}"]["mean"]
        print(f"{n:<16}{d['full']['mean'] / 1024:>10.0f}{d[f'crf{CRF}']['mean'] / 1024:>11.0f}"
              f"{slot / 1024:>10.0f}{slot * 60 / INTERVAL_S / 2**20:>9.2f}{d['full']['n']:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
