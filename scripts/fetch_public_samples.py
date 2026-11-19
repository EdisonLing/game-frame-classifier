#!/usr/bin/env python3
"""Download small, deterministic samples of approved public datasets.

Each dataset's licence is saved first (``fetch_license``) and every downloaded file
is recorded in its provenance (``record_download``). Videos land in
``data/raw/<Game>/<source_id>/`` for ``gfc-make-sources``; stills land in
``data/_public_cache/<source_id>/`` with a manifest for ``gfc-ingest-stills``.

  python scripts/fetch_public_samples.py vpt --per-index 3
  python scripts/fetch_public_samples.py bedd --per-task 4
  python scripts/fetch_public_samples.py marvelrivals --images 300
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from game_frame_classifier.public_sources import (  # noqa: E402
    PublicSourcesError,
    fetch_license,
    record_download,
)

BLOB = "https://openaipublic.blob.core.windows.net/minecraft-rl/"
VPT_INDEXES = ("all_6xx_Jun_29", "all_7xx_Apr_6", "all_8xx_Jun_29", "all_9xx_Jun_29", "all_10xx_Jun_29")
BEDD_INDEXES = ("find-cave-Jul-28", "waterfall-Jul-28", "pen-animals-Jul-28", "build-house-Jul-28")
MR_REPO = "Chappieut/MARVELRIVALSYOLO"
MR_REVISION = "066c9417ddc63f6fe6696920fba6e538bcb1a49e"


def fetch(url: str, dest: Path) -> Path:
    """Download url to dest unless it is already there; return dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"  have {dest.name}")
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=300) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out, 1024 * 1024)
    tmp.replace(dest)
    print(f"  got  {dest.name} ({dest.stat().st_size / 1e6:.0f} MB)")
    return dest


def spread(items: list[str], n: int) -> list[str]:
    """n items evenly spaced through a sorted list (deterministic)."""
    items = sorted(items)
    if n >= len(items):
        return items
    return [items[(i * len(items)) // n] for i in range(n)]


def index_mp4s(name: str) -> list[str]:
    with urllib.request.urlopen(f"{BLOB}snapshots/{name}.json", timeout=120) as resp:
        data = json.load(resp)
    return [p for p in data["relpaths"] if p.endswith(".mp4")]


def fetch_videos(source: str, indexes: tuple[str, ...], per_index: int, data_root: Path) -> None:
    """per_index videos spread through each index; a file the index lists but the
    host no longer has (HTTP 404) is skipped for the next one in the same index."""
    fetch_license(source, repo_root=ROOT)
    out_dir = data_root / "raw" / "Minecraft" / source
    for name in indexes:
        print(f"{source}: {name}")
        paths = sorted(index_mp4s(name))
        got = 0
        for start in spread(paths, per_index):
            for rel in paths[paths.index(start):]:
                try:
                    dest = fetch(BLOB + rel, out_dir / Path(rel).name)
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:
                        raise
                    print(f"  missing on host, skipped {Path(rel).name}")
                    continue
                record_download(source, dest, repo_root=ROOT)
                got += 1
                break
        print(f"  {got} of {per_index} videos")


def mr_group(file_name: str) -> str:
    """Group id from a screenshot's unix time: one group per 10 minutes."""
    match = re.search(r"screenshot_(\d{10})", file_name)
    return f"t{int(match.group(1)) // 600}"


def fetch_marvelrivals(images: int, data_root: Path) -> None:
    source = "public_marvelrivals_yolo"
    fetch_license(source, repo_root=ROOT)
    with urllib.request.urlopen(f"https://huggingface.co/api/datasets/{MR_REPO}/revision/{MR_REVISION}", timeout=120) as resp:
        files = [s["rfilename"] for s in json.load(resp)["siblings"]]
    # Only full-screen captures (screenshot_<unix time>); the rest are character crops
    # made for detection training, not gameplay frames.
    pngs = [f for f in files if f.startswith("images/") and re.search(r"screenshot_\d{10}", f)]
    cache = data_root / "_public_cache" / source
    rows = []
    for rel in spread(pngs, images):
        url = f"https://huggingface.co/datasets/{MR_REPO}/resolve/{MR_REVISION}/{rel}"
        dest = fetch(url, cache / rel)
        record_download(source, dest, repo_root=ROOT)
        rows.append({"file": rel, "game": "Marvel_Rivals", "other_name": "", "group": mr_group(rel), "order": ""})
    manifest = cache / "manifest.csv"
    with open(manifest, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "game", "other_name", "group", "order"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"manifest: {manifest} ({len(rows)} stills, {len({r['group'] for r in rows})} groups)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dataset", choices=("vpt", "bedd", "marvelrivals"))
    p.add_argument("--per-index", type=int, default=3, help="vpt: videos per contractor index")
    p.add_argument("--per-task", type=int, default=4, help="bedd: videos per task")
    p.add_argument("--images", type=int, default=300, help="marvelrivals: stills")
    p.add_argument("--data-root", type=Path, default=ROOT / "data")
    args = p.parse_args()
    try:
        if args.dataset == "vpt":
            fetch_videos("public_vpt_contractor", VPT_INDEXES, args.per_index, args.data_root)
        elif args.dataset == "bedd":
            fetch_videos("public_bedd_basalt", BEDD_INDEXES, args.per_task, args.data_root)
        else:
            fetch_marvelrivals(args.images, args.data_root)
    except PublicSourcesError as exc:
        print(f"fetch_public_samples: {exc}", file=sys.stderr)
        return exc.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
