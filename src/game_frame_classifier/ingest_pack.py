"""Ingest a Frame Export Kit contributor pack into data/frame_sources/ (ingest-pack spec)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from game_frame_classifier.sourcing import SCHEMA_PACK
from game_frame_classifier.sourcing.hashing import jpeg_size
from game_frame_classifier.sourcing.labels import GAMES, OTHER, normalize_handle, normalize_other_name
from game_frame_classifier.sourcing.packzip import PackZipError, validate_pack_zip
from game_frame_classifier.sourcing.recipe import RecipeError, load_recipe

__version__ = "1.0.0"
SCHEMA_INGEST = "gfc.ingest/1"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

REQUIRED_PACK_FILES = (
    "pack_manifest.json",
    "clips.json",
    "frames.json",
    "clips.csv",
    "frames.csv",
    "run_log.txt",
)


class IngestError(ValueError):
    """Pack content failed an ingest check."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def frame_sources_root(data_root: Path) -> Path:
    return Path(data_root) / "frame_sources"


def ensure_under(root: Path, path: Path) -> Path:
    """Resolve path; refuse if it escapes root (junctions/symlinks followed)."""
    root_r = root.resolve()
    target = Path(path).resolve()
    if target != root_r and root_r not in target.parents:
        raise IngestError(f"refusing path outside data root: {target.name}")
    return target


def atomic_write_json(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_index(fs_root: Path) -> dict[str, Any]:
    path = fs_root / "_index" / "by_sha256.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise IngestError("by_sha256.json is not an object")
    return data


def save_index(fs_root: Path, index: dict[str, Any]) -> None:
    atomic_write_json(fs_root / "_index" / "by_sha256.json", index)


def append_stats(fs_root: Path, row: dict[str, Any]) -> None:
    path = fs_root / "_stats" / "handoff_sizes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def recipe_diff(expected: dict[str, Any], packed: dict[str, Any]) -> list[str]:
    """Human-readable field diffs; empty if none. packed may omit questions detail."""
    diffs: list[str] = []
    keys = sorted(set(expected) | set(packed))
    for key in keys:
        if key == "questions":
            continue
        if expected.get(key) != packed.get(key):
            diffs.append(f"{key}: expected {expected.get(key)!r}, pack {packed.get(key)!r}")
    return diffs


def source_dir_name(handle: str) -> str:
    return f"contributor_{handle}"


def clip_dest(fs_root: Path, game: str, other_name: str, handle: str, clip_key: str) -> Path:
    source = source_dir_name(handle)
    if game == OTHER:
        return fs_root / "_other" / other_name / source / clip_key
    return fs_root / game / source / clip_key


def rel_dir_for(game: str, other_name: str, handle: str, clip_key: str) -> str:
    source = source_dir_name(handle)
    if game == OTHER:
        return f"_other/{other_name}/{source}/{clip_key}"
    return f"{game}/{source}/{clip_key}"


def _read_json_entry(zf: zipfile.ZipFile, name: str) -> Any:
    try:
        return json.loads(zf.read(name).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, KeyError) as exc:
        raise IngestError(f"cannot read {name}: {exc}") from exc


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def open_pack_members(zip_path: Path, scratch: Path) -> list[tuple[Path, dict[str, Any], int]]:
    """Return [(pack_zip_path, manifest, zip_bytes), ...] after validate_pack_zip.

    For a single pack, pack_zip_path is zip_path.
    For a zip-of-packs, each inner zip is copied to scratch and left there for the caller to delete.
    """
    manifests = validate_pack_zip(zip_path, scratch)
    with zipfile.ZipFile(zip_path) as zf:
        files = [i for i in zf.infolist() if not i.is_dir()]
        if files and all(i.filename.lower().endswith(".zip") for i in files):
            out: list[tuple[Path, dict[str, Any], int]] = []
            for k, (info, manifest) in enumerate(zip(files, manifests)):
                inner = scratch / f"ingest_inner_{k:03d}.zip"
                with zf.open(info) as src, open(inner, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                out.append((inner, manifest, info.file_size))
            return out
    return [(zip_path, manifests[0], zip_path.stat().st_size)]


def check_pack_content(
    zf: zipfile.ZipFile,
    root: str,
    manifest: dict[str, Any],
    expected_recipe: dict[str, Any],
    prior_packs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    """Return (ok_clips, frames_for_ok, recipe_diff, warnings)."""
    names = {i.filename for i in zf.infolist() if not i.is_dir()}
    for req in REQUIRED_PACK_FILES:
        if f"{root}/{req}" not in names:
            raise IngestError(f"missing {req}")

    contributor = manifest.get("contributor") if isinstance(manifest.get("contributor"), dict) else {}
    handle = normalize_handle(str(contributor.get("handle") or ""))
    if not handle or handle != str(contributor.get("handle") or ""):
        raise IngestError("contributor.handle missing or not normalised")
    contributor_id = str(contributor.get("contributor_id") or "")
    if not contributor_id:
        raise IngestError("contributor.contributor_id missing")
    consent = contributor.get("consent") if isinstance(contributor.get("consent"), dict) else {}
    if consent.get("data_use") is not True:
        raise IngestError("consent.data_use must be true")

    game_info = manifest.get("game") if isinstance(manifest.get("game"), dict) else {}
    game = str(game_info.get("label") or "")
    other_name = ""
    if game == OTHER:
        other_name = normalize_other_name(str(game_info.get("other_name") or ""))
        if not other_name:
            raise IngestError("Other pack needs game.other_name")
    elif game not in GAMES:
        raise IngestError(f"unknown game label: {game}")

    packed_recipe = manifest.get("recipe") if isinstance(manifest.get("recipe"), dict) else {}
    diffs = recipe_diff(expected_recipe, packed_recipe)

    warnings: list[str] = []
    for prev in prior_packs:
        prev_c = prev.get("contributor") if isinstance(prev.get("contributor"), dict) else {}
        prev_handle = str(prev_c.get("handle") or "")
        prev_id = str(prev_c.get("contributor_id") or "")
        if prev_handle == handle and prev_id and prev_id != contributor_id:
            warnings.append(f"handle {handle!r} was used with a different contributor_id")
        if prev_id == contributor_id and prev_handle and prev_handle != handle:
            warnings.append(f"contributor_id {contributor_id} was used with handle {prev_handle!r}")

    clips = _read_json_entry(zf, f"{root}/clips.json")
    frames = _read_json_entry(zf, f"{root}/frames.json")
    if not isinstance(clips, list) or not isinstance(frames, list):
        raise IngestError("clips.json / frames.json must be lists")

    tiers = list((manifest.get("output") or {}).get("tiers") or [])
    if not tiers:
        raise IngestError("manifest.output.tiers missing")

    ok_clips = [c for c in clips if isinstance(c, dict) and c.get("status") == "ok"]
    for clip in ok_clips:
        clip_key = str(clip.get("clip_key") or "")
        sha = str(clip.get("clip_sha256") or "")
        if not clip_key.startswith("c") or len(clip_key) != 13:
            raise IngestError(f"bad clip_key: {clip_key!r}")
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise IngestError(f"bad clip_sha256 for {clip_key}")
        if clip_key != "c" + sha[:12]:
            raise IngestError(f"clip_key does not match clip_sha256 for {clip_key}")
        slots = clip.get("slots")
        expected = clip.get("expected_slots")
        unpaired = clip.get("unpaired_dropped")
        if not isinstance(slots, int) or not isinstance(expected, int) or slots < 1:
            raise IngestError(f"bad slots for {clip_key}")
        if slots != expected or unpaired not in (0, "0", "", None):
            raise IngestError(f"incomplete slots for {clip_key}")

    ok_keys = {str(c["clip_key"]) for c in ok_clips}
    frames_ok = [f for f in frames if isinstance(f, dict) and str(f.get("clip_key")) in ok_keys]
    for fr in frames_ok:
        rel = str(fr.get("rel_path") or "")
        name = f"{root}/{rel}"
        if name not in names:
            raise IngestError(f"missing frame file: {rel}")
        data = zf.read(name)
        if len(data) != int(fr.get("bytes") or -1):
            raise IngestError(f"byte size mismatch: {rel}")
        if _sha256_bytes(data) != str(fr.get("sha256") or ""):
            raise IngestError(f"sha256 mismatch: {rel}")
        # JPEG SOF check via a temp file under the caller's scratch is done in place_pack

    for clip in ok_clips:
        clip_key = str(clip["clip_key"])
        mine = [f for f in frames_ok if str(f.get("clip_key")) == clip_key]
        if len(mine) != int(clip["slots"]) * len(tiers):
            raise IngestError(f"frame count mismatch for {clip_key}")
        by_tier: dict[str, set[int]] = {}
        for fr in mine:
            tier = str(fr.get("tier") or "")
            if tier not in tiers:
                raise IngestError(f"unexpected tier {tier} for {clip_key}")
            by_tier.setdefault(tier, set()).add(int(fr["bucket"]))
        if set(by_tier) != set(tiers):
            raise IngestError(f"missing tier for {clip_key}")
        buckets = next(iter(by_tier.values()))
        if any(by_tier[t] != buckets for t in tiers):
            raise IngestError(f"tier buckets disagree for {clip_key}")

    return ok_clips, frames_ok, diffs, warnings


def _jpeg_check(zf: zipfile.ZipFile, root: str, frames_ok: list[dict[str, Any]], scratch: Path) -> None:
    scratch.mkdir(parents=True, exist_ok=True)
    for fr in frames_ok:
        rel = str(fr["rel_path"])
        tmp = scratch / "frame_check.jpg"
        tmp.write_bytes(zf.read(f"{root}/{rel}"))
        try:
            width, height = jpeg_size(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        if (width, height) != (int(fr["width"]), int(fr["height"])):
            raise IngestError(f"JPEG size mismatch: {rel}")


def load_prior_pack_manifests(fs_root: Path) -> list[dict[str, Any]]:
    packs = fs_root / "_packs"
    if not packs.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(packs.glob("*/pack_manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def place_pack(
    pack_zip: Path,
    manifest: dict[str, Any],
    zip_bytes: int,
    fs_root: Path,
    expected_recipe: dict[str, Any],
    *,
    dry_run: bool,
    force: bool,
    source_basename: str,
    scratch: Path,
) -> dict[str, Any]:
    pack_id = str(manifest.get("pack_id") or "")
    if not pack_id:
        raise IngestError("pack_id missing")
    pack_dir = ensure_under(fs_root, fs_root / "_packs" / pack_id)
    if pack_dir.exists() and not force and not dry_run:
        raise IngestError(f"pack {pack_id} already ingested (use --force to replace)")

    with zipfile.ZipFile(pack_zip) as zf:
        files = [i for i in zf.infolist() if not i.is_dir()]
        roots = {i.filename.split("/", 1)[0] for i in files}
        root = next(iter(roots))
        prior = load_prior_pack_manifests(fs_root)
        ok_clips, frames_ok, diffs, warnings = check_pack_content(
            zf, root, manifest, expected_recipe, prior,
        )
        _jpeg_check(zf, root, frames_ok, scratch)

        contributor = manifest["contributor"]
        handle = str(contributor["handle"])
        game = str(manifest["game"]["label"])
        other_name = normalize_other_name(str(manifest["game"].get("other_name") or "")) if game == OTHER else ""

        index = load_index(fs_root)
        placed: list[str] = []
        skipped: list[str] = []

        if dry_run:
            for clip in ok_clips:
                sha = str(clip["clip_sha256"])
                existing = index.get(sha)
                if existing and existing.get("pack_id") != pack_id:
                    skipped.append(str(clip["clip_key"]))
                else:
                    placed.append(str(clip["clip_key"]))
            return {
                "schema": SCHEMA_INGEST,
                "ingested_utc": utc_now_iso(),
                "tool": {"name": "gfc-ingest-pack", "version": __version__},
                "source_zip": source_basename,
                "pack_id": pack_id,
                "recipe_diff": diffs,
                "warnings": warnings,
                "clips_placed": len(placed),
                "clips_skipped_existing": len(skipped),
                "clips_failed": 0,
                "placed_clip_keys": placed,
                "skipped_clip_keys": skipped,
                "dry_run": True,
                "game": game,
                "handle": handle,
            }

        # Extract verbatim pack tables into _packs/<id>/ via a staging folder
        stage = ensure_under(fs_root, fs_root / "_tmp" / f"stage_{pack_id}")
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)

        def extract_to(arc: str, dest: Path) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(arc) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)

        for req in REQUIRED_PACK_FILES:
            extract_to(f"{root}/{req}", stage / req)
        for info in files:
            rel = info.filename[len(root) + 1 :]
            if rel.startswith("probe/") and rel.endswith(".json"):
                extract_to(info.filename, stage / rel)

        for clip in ok_clips:
            sha = str(clip["clip_sha256"])
            clip_key = str(clip["clip_key"])
            existing = index.get(sha)
            if existing and existing.get("pack_id") != pack_id:
                skipped.append(clip_key)
                continue
            dest = ensure_under(fs_root, clip_dest(fs_root, game, other_name, handle, clip_key))
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            mine = [f for f in frames_ok if str(f.get("clip_key")) == clip_key]
            for fr in mine:
                rel = str(fr["rel_path"])
                out = ensure_under(fs_root, dest / Path(rel).relative_to(f"frames/{clip_key}"))
                extract_to(f"{root}/{rel}", out)
            (dest / "clip.json").write_text(
                json.dumps(clip, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
            )
            index[sha] = {
                "clip_key": clip_key,
                "pack_id": pack_id,
                "game": game if game != OTHER else OTHER,
                "source": source_dir_name(handle),
                "rel_dir": rel_dir_for(game, other_name, handle, clip_key),
            }
            placed.append(clip_key)

        ingest_record = {
            "schema": SCHEMA_INGEST,
            "ingested_utc": utc_now_iso(),
            "tool": {"name": "gfc-ingest-pack", "version": __version__},
            "source_zip": source_basename,
            "pack_id": pack_id,
            "recipe_diff": diffs,
            "warnings": warnings,
            "clips_placed": len(placed),
            "clips_skipped_existing": len(skipped),
            "clips_failed": 0,
            "placed_clip_keys": placed,
            "skipped_clip_keys": skipped,
        }
        atomic_write_json(stage / "ingest.json", ingest_record)

        if pack_dir.exists():
            shutil.rmtree(pack_dir)
        pack_dir.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(pack_dir)
        save_index(fs_root, index)

        sizes = Counter()
        for fr in frames_ok:
            if str(fr.get("clip_key")) in placed:
                sizes[(int(fr["width"]), int(fr["height"]))] += 1
        modal = sizes.most_common(1)[0][0] if sizes else (0, 0)
        input_bytes = int((manifest.get("input") or {}).get("input_bytes") or 0)
        uncompressed = int((manifest.get("output") or {}).get("uncompressed_bytes") or 0)
        append_stats(fs_root, {
            "ingested_utc": ingest_record["ingested_utc"],
            "pack_id": pack_id,
            "game": game,
            "handle": handle,
            "frame_mode": str((manifest.get("recipe") or {}).get("frame_mode") or ""),
            "width": modal[0],
            "height": modal[1],
            "zip_bytes": zip_bytes,
            "input_bytes": input_bytes,
            "uncompressed_bytes": uncompressed,
            "slots": int((manifest.get("output") or {}).get("slots") or 0),
            "images": int((manifest.get("output") or {}).get("images") or 0),
            "clips_placed": len(placed),
        })
        return ingest_record


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gfc-ingest-pack", description="Ingest a contributor pack zip into data/frame_sources.")
    p.add_argument("zip", help="path to a pack zip, or a zip of pack zips")
    p.add_argument("--data-root", type=Path, default=Path("data"), help="project data root (default: data)")
    p.add_argument("--recipe", type=Path, default=Path("config/recipe.json"), help="expected recipe JSON")
    p.add_argument("--dry-run", action="store_true", help="validate only; write nothing")
    p.add_argument("--force", action="store_true", help="replace an already-ingested pack_id")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"gfc-ingest-pack {__version__}")
    zip_path = Path(args.zip)
    if not zip_path.is_file():
        print(f"Not a file: {zip_path}")
        return EXIT_USAGE
    try:
        recipe = load_recipe(args.recipe)
    except (RecipeError, OSError) as exc:
        print(f"Recipe problem: {exc}")
        return EXIT_USAGE
    expected = recipe.to_manifest()
    data_root = Path(args.data_root)
    fs_root = frame_sources_root(data_root)
    if not args.dry_run:
        fs_root.mkdir(parents=True, exist_ok=True)
        ensure_under(data_root.resolve(), fs_root)
    scratch = fs_root / "_tmp" / "scratch" if not args.dry_run else Path(args.data_root) / "frame_sources" / "_tmp" / "scratch"
    # dry-run still needs a scratch under data-root for nested zip copies; create then delete if dry-run
    scratch.mkdir(parents=True, exist_ok=True)

    print(f"Validating {zip_path.name} …")
    failed = 0
    try:
        try:
            members = open_pack_members(zip_path, scratch)
        except PackZipError as exc:
            print(f"Zip rejected: {exc}")
            return EXIT_FAIL

        source_basename = zip_path.name
        for pack_zip, manifest, zip_bytes in members:
            pack_id = str(manifest.get("pack_id") or "?")
            try:
                if manifest.get("schema") != SCHEMA_PACK:
                    raise IngestError(f"bad schema {manifest.get('schema')!r}")
                record = place_pack(
                    pack_zip, manifest, zip_bytes, fs_root, expected,
                    dry_run=args.dry_run, force=args.force,
                    source_basename=source_basename, scratch=scratch,
                )
            except IngestError as exc:
                print(f"  pack {pack_id[:8]}…: FAILED — {exc}")
                failed += 1
            else:
                game = record.get("game", "")
                handle = record.get("handle", "")
                diff = record.get("recipe_diff") or []
                print(
                    f"  pack {pack_id[:8]}…: {game} / contributor_{handle} — "
                    f"placed {record['clips_placed']}, skipped existing {record['clips_skipped_existing']}"
                )
                print(f"  recipe_diff: {diff if diff else '(none)'}")
                for w in record.get("warnings") or []:
                    print(f"  warning: {w}")
                if args.dry_run:
                    print("  dry-run: no files written")
                else:
                    print(f"Wrote {Path('data') / 'frame_sources' / '_packs' / pack_id}/".replace("data", str(args.data_root)))
            finally:
                if pack_zip != zip_path:
                    pack_zip.unlink(missing_ok=True)
    finally:
        if args.dry_run and scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)
        tmp = fs_root / "_tmp"
        if tmp.is_dir() and not any(tmp.iterdir()):
            tmp.rmdir()

    return EXIT_FAIL if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
