"""Time frame extraction; report wall-sec per video-minute (and related rates)."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from game_frame_classifier.frame_extractor import extract_frames

RAW = Path("data/raw")
OUT = Path("data/bench_extract")
INTERVAL_S = 5.0
WIDTH = 256
HEIGHT = 144


def probe(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "format=duration:stream=width,height,codec_name,avg_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    data = json.loads(subprocess.check_output(cmd, text=True))
    st = data["streams"][0]
    return {
        "path": path,
        "duration_s": float(data["format"]["duration"]),
        "width": int(st["width"]),
        "height": int(st["height"]),
        "codec": st.get("codec_name"),
        "fps": st.get("avg_frame_rate"),
        "mb": path.stat().st_size / (1024**2),
    }


def time_extract(video: Path, out_dir: Path, *, max_duration_s: float | None) -> dict:
    if out_dir.exists():
        import shutil

        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    records = extract_frames(
        video,
        out_dir,
        game="Valorant",
        video_id=video.stem[:40],
        interval_s=INTERVAL_S,
        width=WIDTH,
        height=HEIGHT,
        max_duration_s=max_duration_s,
        write_manifest=True,
    )
    wall = time.perf_counter() - t0
    processed = max_duration_s if max_duration_s is not None else probe(video)["duration_s"]
    return {
        "wall_s": wall,
        "processed_s": processed,
        "frames": len(records),
        "wall_per_video_min": wall / (processed / 60.0),
        "frames_per_s_wall": len(records) / wall if wall > 0 else 0.0,
    }


def main() -> None:
    videos = sorted(
        p
        for p in RAW.rglob("*")
        if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".avi"}
    )
    if not videos:
        raise SystemExit("no videos under data/raw")

    print("=== inventory ===")
    infos = [probe(p) for p in videos]
    total_s = sum(i["duration_s"] for i in infos)
    for i in infos:
        print(
            f"  {i['path'].name}: {i['duration_s']/60:.2f} min, "
            f"{i['width']}x{i['height']} {i['codec']}, {i['mb']:.0f} MB"
        )
    print(f"  TOTAL: {total_s/60:.2f} video-minutes across {len(infos)} file(s)")

    # Controlled slices on the first clip (warm decode path similarly each time).
    sample = infos[0]["path"]
    print(f"\n=== timed slices on {sample.name} @ {INTERVAL_S}s / {WIDTH}x{HEIGHT} ===")
    slice_results = []
    for minutes in (1.0, 3.0, 5.0):
        max_s = minutes * 60.0
        if max_s > infos[0]["duration_s"] + 1:
            print(f"  skip {minutes:g} min slice (clip shorter)")
            continue
        out = OUT / f"slice_{minutes:g}min"
        r = time_extract(sample, out, max_duration_s=max_s)
        slice_results.append({"label": f"{minutes:g}min_slice", **r})
        print(
            f"  {minutes:g} min video → {r['wall_s']:.2f}s wall, "
            f"{r['frames']} frames, "
            f"{r['wall_per_video_min']:.2f} wall-s / video-min"
        )

    # One full-clip timing if not enormous; otherwise 10-min slice as long sample.
    full_dur = infos[0]["duration_s"]
    if full_dur <= 15 * 60:
        print(f"\n=== full first clip ({full_dur/60:.2f} min) ===")
        r = time_extract(sample, OUT / "full_first", max_duration_s=None)
        slice_results.append({"label": "full_first", **r})
        print(
            f"  full → {r['wall_s']:.2f}s wall, {r['frames']} frames, "
            f"{r['wall_per_video_min']:.2f} wall-s / video-min"
        )
    else:
        print("\n=== 10 min long slice (full clip > 15 min) ===")
        r = time_extract(sample, OUT / "slice_10min", max_duration_s=600.0)
        slice_results.append({"label": "10min_slice", **r})
        print(
            f"  10 min video → {r['wall_s']:.2f}s wall, {r['frames']} frames, "
            f"{r['wall_per_video_min']:.2f} wall-s / video-min"
        )

    # Firm estimate: prefer longest measured slice (most stable).
    best = max(slice_results, key=lambda x: x["processed_s"])
    rate = best["wall_per_video_min"]
    # Use median of all slices as secondary check.
    rates = sorted(x["wall_per_video_min"] for x in slice_results)
    median = rates[len(rates) // 2]

    print("\n=== estimate ===")
    print(f"  primary rate (longest run): {rate:.2f} wall-seconds per video-minute")
    print(f"  median across runs:         {median:.2f} wall-seconds per video-minute")
    print(f"  ⇒ wall hours for current library ({total_s/60:.1f} min): "
          f"{(total_s/60) * rate / 3600:.2f} h  (primary)")
    print(f"  formula: wall_sec ≈ {rate:.2f} × video_minutes "
          f"(interval={INTERVAL_S}s, {WIDTH}x{HEIGHT}, this machine/codec)")

    payload = {
        "settings": {
            "interval_s": INTERVAL_S,
            "width": WIDTH,
            "height": HEIGHT,
        },
        "inventory": [
            {
                "file": i["path"].name,
                "duration_s": i["duration_s"],
                "duration_min": i["duration_s"] / 60,
                "width": i["width"],
                "height": i["height"],
                "codec": i["codec"],
                "mb": i["mb"],
            }
            for i in infos
        ],
        "total_video_minutes": total_s / 60,
        "runs": slice_results,
        "primary_wall_sec_per_video_min": rate,
        "median_wall_sec_per_video_min": median,
        "estimate_wall_hours_current_library": (total_s / 60) * rate / 3600,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    out_json = OUT / "bench_extract_summary.json"
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
