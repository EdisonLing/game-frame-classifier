#!/usr/bin/env python3
"""Prototype: turn labelled public stills into frame_sources quick-mode clips.

Writes only under data/ (frame_sources, and the download cache data/_public_cache/).

Supported --dataset values:
  gamed              Hugging Face ybashir/gamed-game-classification-dataset (eval zip)
  gameplay_images    Hugging Face Bingsu/Gameplay_Images (Minecraft class only)

Example:
  python scripts/prototype_public_stills.py --dataset gamed --max-videos 3
  python scripts/prototype_public_stills.py --dataset gameplay_images --max-images 60
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from game_frame_classifier.ingest_stills import StillClip, StillRow, write_still_clip  # noqa: E402
from game_frame_classifier.public_sources import (  # noqa: E402
    PublicSourcesError,
    fetch_license,
    record_download,
)

SOURCE_IDS = {
    "gamed": "public_gamed",
    "gameplay_images": "public_gameplay_images",
}

GAME_MAP_GAMED = {
    "valorant": "Valorant",
    "cs2": "CS2",
}
# dota2 is not one of the six target games — skip unless --include-dota2


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"using cached {dest}")
        return
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)
    print(f"saved {dest} ({dest.stat().st_size} bytes)")


def prototype_gamed(args: argparse.Namespace) -> None:
    source = SOURCE_IDS["gamed"]
    fetch_license(source, repo_root=ROOT)
    cache = Path(args.cache_dir)
    zip_path = cache / "gamed_eval_frames.zip"
    manifest_path = cache / "gamed_eval_manifest.csv"
    download(
        "https://huggingface.co/datasets/ybashir/gamed-game-classification-dataset/resolve/main/eval/frames.zip",
        zip_path,
    )
    record_download(source, zip_path, repo_root=ROOT)
    download(
        "https://huggingface.co/datasets/ybashir/gamed-game-classification-dataset/resolve/main/eval/manifest.csv",
        manifest_path,
    )
    record_download(source, manifest_path, repo_root=ROOT)

    extract_root = cache / "gamed_eval_extract"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_root)

    # Locate frames by matching manifest paths to extracted files.
    by_video: dict[tuple[str, str], list[tuple[float, Path]]] = defaultdict(list)
    with open(manifest_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cls = (row.get("class") or "").strip().lower()
            if cls == "dota2" and not args.include_dota2:
                continue
            game = GAME_MAP_GAMED.get(cls)
            if not game:
                continue
            video_id = (row.get("video_id") or "").strip()
            if not video_id:
                continue
            rel = (row.get("path") or "").replace("\\", "/")
            # Manifest paths look like dataset/frames/<class>/<file>.jpg — zip layout may differ.
            name = Path(rel).name
            matches = list(extract_root.rglob(name))
            if not matches:
                continue
            t_sec = float(row.get("t_sec") or 0)
            by_video[(game, video_id)].append((t_sec, matches[0]))

    # Cap videos per game for a small prototype.
    selected: list[tuple[str, str, list[tuple[float, Path]]]] = []
    per_game: dict[str, int] = defaultdict(int)
    for (game, video_id), frames in sorted(by_video.items()):
        if per_game[game] >= args.max_videos:
            continue
        frames_sorted = sorted(frames, key=lambda x: x[0])
        if not frames_sorted:
            continue
        selected.append((game, video_id, frames_sorted))
        per_game[game] += 1

    fs_root = Path(args.data_root) / "frame_sources"
    written = []
    for i, (game, video_id, frames) in enumerate(selected):
        rows = [
            StillRow(
                file=str(path.relative_to(extract_root)).replace("\\", "/"),
                game=game,
                other_name="",
                group=video_id,
                order=float(t_sec),
            )
            for t_sec, path in frames
        ]
        clip = StillClip(
            game=game,
            other_name="",
            group=video_id,
            group_origin="dataset",
            rows=rows,
        )
        status, n, _failed = write_still_clip(
            fs_root,
            source,
            clip,
            extract_root,
            clip_index=i,
            force=True,
        )
        if status == "written":
            dest = fs_root / game / source
            written.append(dest)
            print(f"wrote {game}/{source} group={video_id} ({n} frames)")

    print(f"gamed prototype: {len(written)} clips under {source}")


def prototype_gameplay_images(args: argparse.Namespace) -> None:
    """Pull Minecraft-labelled stills via Hugging Face datasets API parquet/rows if needed.

    Prefer a small local cache of PNGs downloaded with huggingface_hub when available.
    """
    source = SOURCE_IDS["gameplay_images"]
    fetch_license(source, repo_root=ROOT)
    cache = Path(args.cache_dir) / "gameplay_images"
    cache.mkdir(parents=True, exist_ok=True)

    try:
        from datasets import load_dataset
    except ImportError:
        raise SystemExit(
            "Install datasets (pip install datasets) for gameplay_images prototype, "
            "or prototype gamed first (stdlib-only)."
        )

    print("loading Bingsu/Gameplay_Images (Minecraft label only)…")
    ds = load_dataset("Bingsu/Gameplay_Images", split="train")
    # Label names from dataset card: Minecraft is class 7 in the 10-class set.
    label_names = ds.features["label"].names
    try:
        minecraft_id = label_names.index("Minecraft")
    except ValueError:
        # Some mirrors use lowercase / underscored names.
        minecraft_id = next(i for i, n in enumerate(label_names) if "minecraft" in n.lower())

    rows_ds = [ex for ex in ds if int(ex["label"]) == minecraft_id][: args.max_images]
    if not rows_ds:
        raise SystemExit("no Minecraft rows found in Gameplay Images")

    # Group into synthetic clips of N stills for session-ish splits.
    group = max(args.images_per_clip, 1)
    fs_root = Path(args.data_root) / "frame_sources"
    written = []
    clip_index = 0
    for gi in range(0, len(rows_ds), group):
        chunk = rows_ds[gi : gi + group]
        still_rows: list[StillRow] = []
        for j, ex in enumerate(chunk):
            jpeg_path = cache / f"mc_{gi:04d}_{j:02d}.jpg"
            if not jpeg_path.is_file():
                img = ex["image"]
                # datasets returns PIL Image
                img.convert("RGB").save(jpeg_path, format="JPEG", quality=95)
            still_rows.append(
                StillRow(
                    file=jpeg_path.name,
                    game="Minecraft",
                    other_name="",
                    group=f"auto{gi // group:04d}",
                    order=float(j),
                )
            )
        clip = StillClip(
            game="Minecraft",
            other_name="",
            group=f"auto{gi // group:04d}",
            group_origin="made_up",
            rows=still_rows,
        )
        status, n, _failed = write_still_clip(
            fs_root,
            source,
            clip,
            cache,
            clip_index=clip_index,
            force=True,
        )
        clip_index += 1
        if status == "written":
            written.append(clip.group)
            print(f"wrote Minecraft/{source} group={clip.group} ({n} frames)")

    print(f"gameplay_images prototype: {len(written)} clips under {source}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=("gamed", "gameplay_images"), required=True)
    p.add_argument("--data-root", type=Path, default=ROOT / "data")
    p.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "_public_cache")
    p.add_argument("--max-videos", type=int, default=3, help="gamed: max videos per game")
    p.add_argument("--include-dota2", action="store_true")
    p.add_argument("--max-images", type=int, default=60, help="gameplay_images: max Minecraft stills")
    p.add_argument("--images-per-clip", type=int, default=10)
    args = p.parse_args()
    args.data_root.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.dataset == "gamed":
            prototype_gamed(args)
        else:
            prototype_gameplay_images(args)
    except PublicSourcesError as exc:
        print(f"prototype_public_stills: {exc}", file=sys.stderr)
        return exc.exit_code
    print("done", utc_now())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
