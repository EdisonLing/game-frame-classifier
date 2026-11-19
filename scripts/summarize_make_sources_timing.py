"""Summarise gfc-make-sources timing from the run reports under data/frame_sources/_personal/.

Reads each run's clips.csv (rows with status ok and a wall_s) and prints wall seconds per
clip and per minute of footage, grouped by codec, resolution and extract method. Use the
rates to estimate a coming run: wall_s ~ rate * footage_minutes.

Usage: python scripts/summarize_make_sources_timing.py [--data-root data]
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def load_rows(data_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted((data_root / "frame_sources" / "_personal").glob("*/clips.csv")):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") == "ok" and row.get("wall_s") and row.get("duration_s"):
                    rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, default=Path("data"))
    args = ap.parse_args()
    rows = load_rows(args.data_root)
    if not rows:
        print("no timed clips found")
        return 1
    groups: dict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        key = (
            r.get("video_codec") or "?",
            f"{r.get('width') or '?'}x{r.get('height') or '?'}",
            r.get("extract_method") or "?",
        )
        groups[key].append((float(r["wall_s"]), float(r["duration_s"])))
    print(f"{'codec':8} {'size':10} {'method':7} {'clips':>5} {'footage min':>11} "
          f"{'s/clip':>7} {'s/footage-min':>13}")
    total_wall = total_dur = 0.0
    for key in sorted(groups, key=lambda k: -sum(w for w, _ in groups[k])):
        pairs = groups[key]
        wall = sum(w for w, _ in pairs)
        dur = sum(d for _, d in pairs)
        total_wall += wall
        total_dur += dur
        print(f"{key[0]:8} {key[1]:10} {key[2]:7} {len(pairs):5d} {dur / 60:11.1f} "
              f"{wall / len(pairs):7.1f} {wall / (dur / 60):13.1f}")
    print(f"{'all':27} {len(rows):5d} {total_dur / 60:11.1f} "
          f"{total_wall / len(rows):7.1f} {total_wall / (total_dur / 60):13.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
