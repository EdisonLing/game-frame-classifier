#!/usr/bin/env python3
"""Prototype: turn labelled public stills into frame_sources quick-mode clips.

Does not touch the main checkout. Writes only under this worktree's data/.

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
import hashlib
import io
import json
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

from game_frame_classifier.derive_frames import frame_name  # noqa: E402
from game_frame_classifier.sourcing.hashing import jpeg_size  # noqa: E402
from game_frame_classifier.sourcing.manifests import CLIP_COLUMNS, blank_clip_row  # noqa: E402

GAME_MAP_GAMED = {
    "valorant": "Valorant",
    "cs2": "CS2",
}
# dota2 is not one of the six target games — skip unless --include-dota2


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clip_key_for(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return "c" + digest[:12]


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"using cached {dest}")
        return
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)
    print(f"saved {dest} ({dest.stat().st_size} bytes)")


def write_clip(
    fs_root: Path,
    game: str,
    source: str,
    seed: str,
    image_paths: list[Path],
    *,
    original_name: str,
    recorded_start_utc: str,
) -> Path:
    key = clip_key_for(seed)
    dest = fs_root / game / source / key
    if dest.exists():
        shutil.rmtree(dest)
    full = dest / "full"
    full.mkdir(parents=True)

    # Hash identity from the ordered still bytes so re-runs stay stable.
    h = hashlib.sha256()
    widths: list[int] = []
    heights: list[int] = []
    for i, src in enumerate(image_paths):
        data = src.read_bytes()
        h.update(data)
        out = full / frame_name(key, "full", i)
        out.write_bytes(data)
        w, ht = jpeg_size(out)
        widths.append(w)
        heights.append(ht)

    row = blank_clip_row()
    row.update(
        {
            "clip_key": key,
            "clip_sha256": h.hexdigest(),
            "quick_id": h.hexdigest()[:16],
            "status": "ok",
            "status_detail": "prototype_public_stills",
            "original_filename": original_name,
            "original_relpath": original_name,
            "file_bytes": sum(p.stat().st_size for p in image_paths),
            "recorded_start_utc": recorded_start_utc,
            "recorded_start_source": "prototype",
            "duration_s": float(max(len(image_paths), 1) * 5.0),
            "width": widths[0] if widths else 0,
            "height": heights[0] if heights else 0,
            "expected_slots": len(image_paths),
            "slots": len(image_paths),
            "label_hint": game,
        }
    )
    missing = [c for c in CLIP_COLUMNS if c not in row]
    if missing:
        raise SystemExit(f"clip.json missing columns: {missing}")
    payload = {c: row.get(c, "") for c in CLIP_COLUMNS}
    payload["game"] = game
    payload["prototype_dataset"] = source
    (dest / "clip.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest


def prototype_gamed(args: argparse.Namespace) -> None:
    cache = Path(args.cache_dir)
    zip_path = cache / "gamed_eval_frames.zip"
    manifest_path = cache / "gamed_eval_manifest.csv"
    download(
        "https://huggingface.co/datasets/ybashir/gamed-game-classification-dataset/resolve/main/eval/frames.zip",
        zip_path,
    )
    download(
        "https://huggingface.co/datasets/ybashir/gamed-game-classification-dataset/resolve/main/eval/manifest.csv",
        manifest_path,
    )

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
    selected: list[tuple[str, str, list[Path]]] = []
    per_game: dict[str, int] = defaultdict(int)
    for (game, video_id), frames in sorted(by_video.items()):
        if per_game[game] >= args.max_videos:
            continue
        frames_sorted = [p for _, p in sorted(frames, key=lambda x: x[0])]
        if not frames_sorted:
            continue
        selected.append((game, video_id, frames_sorted))
        per_game[game] += 1

    fs_root = Path(args.data_root) / "frame_sources"
    source = "public_gamed"
    written = []
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i, (game, video_id, paths) in enumerate(selected):
        # Convert non-JPEG if needed: Gamed eval is JPEG already.
        start = (base_time.timestamp() + i * 3600)
        recorded = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        dest = write_clip(
            fs_root,
            game,
            source,
            seed=f"gamed:{game}:{video_id}",
            image_paths=paths,
            original_name=f"gamed_{video_id}.jpgseq",
            recorded_start_utc=recorded,
        )
        written.append(dest)
        print(f"wrote {dest.relative_to(Path(args.data_root))} ({len(paths)} frames)")

    print(f"gamed prototype: {len(written)} clips under {source}")


def _png_to_jpeg_bytes(png_path: Path) -> bytes:
    # stdlib-only path: prefer Pillow if present, else require preconverted JPEG.
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "gameplay_images prototype needs Pillow to convert PNG→JPEG, or pass pre-made JPEGs"
        ) from exc
    with Image.open(png_path) as im:
        rgb = im.convert("RGB")
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=95)
        return buf.getvalue()


def prototype_gameplay_images(args: argparse.Namespace) -> None:
    """Pull Minecraft-labelled stills via Hugging Face datasets API parquet/rows if needed.

    Prefer a small local cache of PNGs downloaded with huggingface_hub when available.
    """
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

    rows = [ex for ex in ds if int(ex["label"]) == minecraft_id][: args.max_images]
    if not rows:
        raise SystemExit("no Minecraft rows found in Gameplay Images")

    # Group into synthetic clips of N stills for session-ish splits.
    group = max(args.images_per_clip, 1)
    fs_root = Path(args.data_root) / "frame_sources"
    source = "public_gameplay_images"
    written = []
    base_time = datetime(2022, 1, 1, tzinfo=timezone.utc)
    for gi in range(0, len(rows), group):
        chunk = rows[gi : gi + group]
        tmp_paths: list[Path] = []
        for j, ex in enumerate(chunk):
            jpeg_path = cache / f"mc_{gi:04d}_{j:02d}.jpg"
            if not jpeg_path.is_file():
                img = ex["image"]
                # datasets returns PIL Image
                img.convert("RGB").save(jpeg_path, format="JPEG", quality=95)
            tmp_paths.append(jpeg_path)
        recorded = datetime.fromtimestamp(
            base_time.timestamp() + (gi // group) * 3600, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        dest = write_clip(
            fs_root,
            "Minecraft",
            source,
            seed=f"gameplay_images:Minecraft:group{gi // group}",
            image_paths=tmp_paths,
            original_name=f"gameplay_images_mc_group{gi // group}.jpgseq",
            recorded_start_utc=recorded,
        )
        written.append(dest)
        print(f"wrote {dest.relative_to(Path(args.data_root))} ({len(tmp_paths)} frames)")

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

    if args.dataset == "gamed":
        prototype_gamed(args)
    else:
        prototype_gameplay_images(args)
    print("done", utc_now())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
