"""Time authentic quality path on synthetic 1080p 30/60fps (friend profile)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from game_frame_classifier.quality_encoder import encode_video_quality_tiers
from tests.helpers.ffmpeg_fixtures import make_color_video

OUT = Path("data/bench_extract/quality_1080")
DURATION_S = 30.0  # half-minute clip; scale rates to per video-minute


def run_one(fps: int) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    vid = OUT / f"synth_1080_{fps}fps_{int(DURATION_S)}s.mp4"
    make_color_video(
        vid,
        duration_s=DURATION_S,
        width=1920,
        height=1080,
        fps=fps,
        color="green",
    )
    dest = OUT / f"tiers_{fps}fps"
    t0 = time.perf_counter()
    by_tier = encode_video_quality_tiers(
        vid,
        dest,
        game="Valorant",
        video_id=f"synth_{fps}",
        interval_s=5.0,
        width=256,
        height=144,
    )
    wall = time.perf_counter() - t0
    n_frames = sum(len(v) for v in by_tier.values())
    frame_bytes = 0
    for tier_recs in by_tier.values():
        for r in tier_recs:
            frame_bytes += Path(r.path).stat().st_size
    return {
        "fps": fps,
        "duration_s": DURATION_S,
        "wall_s": wall,
        "wall_s_per_video_min": wall / (DURATION_S / 60.0),
        "total_frames_all_tiers": n_frames,
        "zip_like_frame_MB": frame_bytes / (1024**2),
        "MB_per_video_min_frames": (frame_bytes / (1024**2)) / (DURATION_S / 60.0),
    }


def main() -> None:
    results = [run_one(30), run_one(60)]
    for r in results:
        print(
            f"1080p{r['fps']} {r['duration_s']:.0f}s → "
            f"{r['wall_s']:.2f}s wall "
            f"({r['wall_s_per_video_min']:.1f} s/video-min), "
            f"{r['zip_like_frame_MB']:.2f} MB frames "
            f"({r['MB_per_video_min_frames']:.2f} MB/video-min)"
        )
    payload = {"method": "video_crf_then_extract", "runs": results}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bench_quality_1080.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
