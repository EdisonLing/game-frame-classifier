"""Derive 256x144 train frames from native frame_sources and rebuild clip/slot indexes.

Reads ``data/frame_sources/`` (and the recipe), writes ``data/frames/`` plus
``data/manifests/clips_index.*`` and ``slots.*``. Spec:
``docs/roadmap/tools/derive-frames.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game_frame_classifier.sourcing.derive import derive_dir, pad_dims
from game_frame_classifier.sourcing.ffbin import FFmpegNotFoundError, ToolError, find_tools
from game_frame_classifier.sourcing.hashing import jpeg_size
from game_frame_classifier.sourcing.labels import GAMES, OTHER, normalize_other_name
from game_frame_classifier.sourcing.manifests import write_table
from game_frame_classifier.sourcing.recipe import Recipe, RecipeError, load_recipe

__version__ = "1.0.0"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

DERIVE_ID = "pad16x9_bicubic_256x144_q2"
DERIVE_ID_COMPACT = "compact_passthrough"

CLIPS_INDEX_COLUMNS = (
    "clip_key",
    "clip_sha256",
    "game",
    "other_name",
    "source",
    "source_kind",
    "origin",
    "public_examples_ok",
    "recorded_start_utc",
    "recorded_start_source",
    "duration_s",
    "native_width",
    "native_height",
    "padded",
    "hdr",
    "vfr",
    "video_codec",
    "encoder_tag",
    "low_tier",
    "low_encoder",
    "slots",
    "derive_id",
)

SLOTS_COLUMNS = (
    "slot_id",
    "clip_key",
    "game",
    "other_name",
    "source",
    "bucket",
    "target_time_s",
    "path_full",
    "path_low",
)

_FRAME_NAME = re.compile(r"^(.+)_(full|crf\d+)_b(\d+)\.jpg$", re.IGNORECASE)
_CRF_TIER = re.compile(r"^crf(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class ClipRef:
    game: str
    other_name: str
    source: str
    clip_key: str
    clip_dir: Path


@dataclass
class ClipPlan:
    ref: ClipRef
    clip: dict[str, Any]
    low_tier: str  # "" for quick-mode
    buckets: list[int]  # sorted paired buckets
    unpaired: int
    skip_reason: str = ""


def source_kind(source: str) -> str:
    if source.startswith("contributor_"):
        return "contributor"
    if source.startswith("public_"):
        return "public"
    return "personal"


def parse_frame_bucket(name: str, clip_key: str, tier: str) -> int | None:
    """Return bucket int from ``<clip_key>_<tier>_b<bucket>.jpg``, or None if the name does not match."""
    match = _FRAME_NAME.fullmatch(name)
    if not match:
        return None
    key, file_tier, bucket_s = match.group(1), match.group(2), match.group(3)
    if key != clip_key or file_tier.lower() != tier.lower():
        return None
    return int(bucket_s)


def frame_name(clip_key: str, tier: str, bucket: int) -> str:
    return f"{clip_key}_{tier}_b{bucket:06d}.jpg"


def slot_id(clip_key: str, bucket: int) -> str:
    return f"{clip_key}:b{bucket:06d}"


def rel_posix(*parts: str) -> str:
    return "/".join(parts)


def frames_clip_dir(data_root: Path, ref: ClipRef) -> Path:
    if ref.game == OTHER:
        return Path(data_root) / "frames" / "_other" / ref.other_name / ref.source / ref.clip_key
    return Path(data_root) / "frames" / ref.game / ref.source / ref.clip_key


def find_clips(fs_root: Path, *, game: str | None = None, source: str | None = None) -> list[ClipRef]:
    """Every ``clip.json`` under a known game folder or ``_other/<name>``."""
    fs_root = Path(fs_root)
    if not fs_root.is_dir():
        return []
    found: list[ClipRef] = []
    games = (game,) if game else (*GAMES, OTHER)
    for g in (item for item in games if item != OTHER):
        game_dir = fs_root / g
        if not game_dir.is_dir():
            continue
        for source_dir in sorted(p for p in game_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
            if source is not None and source_dir.name != source:
                continue
            for clip_dir in sorted(p for p in source_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
                if (clip_dir / "clip.json").is_file():
                    found.append(ClipRef(g, "", source_dir.name, clip_dir.name, clip_dir))
    if OTHER in games:
        other_root = fs_root / "_other"
        if other_root.is_dir():
            for name_dir in sorted(p for p in other_root.iterdir() if p.is_dir() and not p.name.startswith("_")):
                other_name = normalize_other_name(name_dir.name)
                if not other_name or other_name != name_dir.name:
                    continue
                for source_dir in sorted(p for p in name_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
                    if source is not None and source_dir.name != source:
                        continue
                    for clip_dir in sorted(p for p in source_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
                        if (clip_dir / "clip.json").is_file():
                            found.append(ClipRef(OTHER, other_name, source_dir.name, clip_dir.name, clip_dir))
    return found


def load_clip_json(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return data


def load_index(fs_root: Path) -> dict[str, Any]:
    path = Path(fs_root) / "_index" / "by_sha256.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_pack_manifest(fs_root: Path, pack_id: str) -> dict[str, Any] | None:
    if not pack_id or pack_id.startswith("personal:"):
        return None
    path = Path(fs_root) / "_packs" / pack_id / "pack_manifest.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def public_examples_ok(kind: str, pack_manifest: dict[str, Any] | None) -> bool:
    if kind == "personal":
        return True
    if kind != "contributor" or pack_manifest is None:
        return False
    contributor = pack_manifest.get("contributor")
    if not isinstance(contributor, dict):
        return False
    consent = contributor.get("consent")
    if not isinstance(consent, dict):
        return False
    return consent.get("public_examples") is True


def list_tier_dirs(clip_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in clip_dir.iterdir():
        if path.is_dir() and not path.name.startswith("_"):
            out[path.name] = path
    return out


def recipe_low_tiers(recipe: Recipe) -> set[str]:
    return {f"crf{n}" for n in recipe.crf_list}


def classify_tiers(tier_dirs: dict[str, Path], recipe: Recipe) -> tuple[str | None, str]:
    """Return ``(low_tier_or_empty, skip_reason)``. ``low_tier`` None means skip the clip."""
    names = set(tier_dirs)
    if "full" not in names:
        return None, "missing full tier"
    low_allowed = recipe_low_tiers(recipe)
    lows = {n for n in names if _CRF_TIER.fullmatch(n)}
    other = names - {"full"} - lows
    if other:
        return None, f"unexpected tier folders: {', '.join(sorted(other))}"
    if not lows:
        return "", ""  # quick-mode
    if len(lows) > 1:
        return None, f"multiple low tiers: {', '.join(sorted(lows))}"
    low = next(iter(lows))
    if low not in low_allowed:
        return None, f"low tier {low} does not match recipe"
    return low, ""


def buckets_in_tier(tier_dir: Path, clip_key: str, tier: str) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for path in sorted(tier_dir.glob("*.jpg")):
        bucket = parse_frame_bucket(path.name, clip_key, tier)
        if bucket is None:
            continue
        found[bucket] = path
    return found


def pair_slots(
    clip_key: str,
    full_buckets: dict[int, Path],
    low_tier: str,
    low_buckets: dict[int, Path] | None,
) -> tuple[list[int], int]:
    """Return (sorted paired buckets, unpaired count)."""
    if not low_tier:
        return sorted(full_buckets), 0
    assert low_buckets is not None
    paired = sorted(set(full_buckets) & set(low_buckets))
    unpaired = len(set(full_buckets) | set(low_buckets)) - len(paired)
    return paired, unpaired


def plan_clip(ref: ClipRef, recipe: Recipe) -> ClipPlan:
    try:
        clip = load_clip_json(ref.clip_dir / "clip.json")
    except (OSError, ValueError) as exc:
        return ClipPlan(ref, {}, "", [], 0, skip_reason=f"bad clip.json: {exc}")
    if str(clip.get("clip_key") or "") != ref.clip_key:
        return ClipPlan(ref, clip, "", [], 0, skip_reason="clip_key does not match folder name")
    tier_dirs = list_tier_dirs(ref.clip_dir)
    low_tier, reason = classify_tiers(tier_dirs, recipe)
    if low_tier is None:
        return ClipPlan(ref, clip, "", [], 0, skip_reason=reason)
    full_map = buckets_in_tier(tier_dirs["full"], ref.clip_key, "full")
    low_map = buckets_in_tier(tier_dirs[low_tier], ref.clip_key, low_tier) if low_tier else None
    buckets, unpaired = pair_slots(ref.clip_key, full_map, low_tier, low_map)
    if not buckets:
        return ClipPlan(ref, clip, low_tier, [], unpaired, skip_reason="no paired slots")
    return ClipPlan(ref, clip, low_tier, buckets, unpaired)


def output_complete(data_root: Path, plan: ClipPlan) -> bool:
    """Every slot has its derived files, none older than its source still (a re-extracted
    clip, for example after gfc-make-sources --rebuild, is derived again)."""
    out = frames_clip_dir(data_root, plan.ref)
    tiers = ["full"] + ([plan.low_tier] if plan.low_tier else [])
    for bucket in plan.buckets:
        for tier in tiers:
            name = frame_name(plan.ref.clip_key, tier, bucket)
            derived = out / tier / name
            if not derived.is_file():
                return False
            source = plan.ref.clip_dir / tier / name
            if source.is_file() and source.stat().st_mtime > derived.stat().st_mtime:
                return False
    return True


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _stage_numbered(src_files: list[Path], stage_dir: Path) -> None:
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    for i, src in enumerate(src_files):
        _link_or_copy(src, stage_dir / f"{i:06d}.jpg")


def _is_compact(plan: ClipPlan, recipe: Recipe) -> bool:
    """True when the source stills are already model size (a compact pack).

    Decided from the first full-tier still, not clip.json: clip.json holds the size of the
    original video, which a compact pack also reports.
    """
    if not plan.buckets:
        return False
    first = plan.ref.clip_dir / "full" / frame_name(plan.ref.clip_key, "full", plan.buckets[0])
    try:
        return jpeg_size(first) == tuple(recipe.compact_size)
    except (OSError, ValueError):
        return False


def derive_tier_folder(
    tools: Any,
    src_dir: Path,
    dst_dir: Path,
    names: list[str],
    recipe: Recipe,
    *,
    compact: bool,
    tmp_root: Path,
) -> None:
    """Derive or copy ``names`` from src_dir into dst_dir (same names). Uses temp dirs under tmp_root."""
    src_files = [src_dir / n for n in names]
    for f in src_files:
        if not f.is_file():
            raise ToolError(f"missing source frame: {f.name}")

    if compact:
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        dst_dir.mkdir(parents=True)
        for f in src_files:
            shutil.copyfile(f, dst_dir / f.name)
        return

    stage_in = tmp_root / "in"
    stage_out = tmp_root / "out"
    _stage_numbered(src_files, stage_in)
    derive_dir(tools, stage_in, stage_out, recipe)
    if stage_out.exists():
        # derive_dir already created stage_out; map numbered → pack names into a final staging folder
        named = tmp_root / "named"
        if named.exists():
            shutil.rmtree(named)
        named.mkdir(parents=True)
        for i, name in enumerate(names):
            src = stage_out / f"{i:06d}.jpg"
            if not src.is_file():
                raise ToolError(f"derive produced no output for {name}")
            src.rename(named / name)
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        dst_dir.parent.mkdir(parents=True, exist_ok=True)
        named.rename(dst_dir)
    else:
        raise ToolError("derive produced no output folder")


def verify_size(path: Path, expected: tuple[int, int]) -> None:
    size = jpeg_size(path)
    if size != expected:
        raise ToolError(f"{path.name} is {size[0]}x{size[1]}, expected {expected[0]}x{expected[1]}")


def derive_clip(
    tools: Any,
    data_root: Path,
    plan: ClipPlan,
    recipe: Recipe,
    *,
    force: bool,
) -> str:
    """Derive one clip. Returns ``derived`` | ``skipped`` | ``passthrough``."""
    if not force and output_complete(data_root, plan):
        return "skipped"

    compact = _is_compact(plan, recipe)
    out_final = frames_clip_dir(data_root, plan.ref)
    tmp_root = Path(data_root) / "frames" / "_tmp" / f"derive_{plan.ref.clip_key}"
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True)

    try:
        staging_clip = tmp_root / "clip_out"
        tiers = ["full"] + ([plan.low_tier] if plan.low_tier else [])
        for tier in tiers:
            names = [frame_name(plan.ref.clip_key, tier, b) for b in plan.buckets]
            src_tier = plan.ref.clip_dir / tier
            dst_tier = staging_clip / tier
            tier_tmp = tmp_root / f"tier_{tier}"
            derive_tier_folder(
                tools, src_tier, dst_tier, names, recipe, compact=compact, tmp_root=tier_tmp,
            )
            for name in names:
                verify_size(dst_tier / name, recipe.compact_size)

        out_final.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        if out_final.exists():
            backup = out_final.with_name(out_final.name + ".__old__")
            if backup.exists():
                shutil.rmtree(backup)
            out_final.rename(backup)
        try:
            staging_clip.rename(out_final)
        except BaseException:
            if backup is not None and backup.exists() and not out_final.exists():
                backup.rename(out_final)
            raise
        if backup is not None and backup.exists():
            shutil.rmtree(backup)
    finally:
        if tmp_root.exists():
            shutil.rmtree(tmp_root, ignore_errors=True)

    return "passthrough" if compact else "derived"


def native_geometry(clip: dict[str, Any], recipe: Recipe) -> tuple[int, int, bool]:
    try:
        width = int(clip.get("width") or 0)
        height = int(clip.get("height") or 0)
    except (TypeError, ValueError):
        width, height = 0, 0
    padded = bool(width and height and pad_dims(width, height, recipe.aspect_tolerance))
    return width, height, padded


def build_clip_row(
    plan: ClipPlan,
    recipe: Recipe,
    *,
    origin: str,
    examples_ok: bool,
    derive_id: str,
) -> dict[str, Any]:
    clip = plan.clip
    width, height, padded = native_geometry(clip, recipe)
    kind = source_kind(plan.ref.source)
    return {
        "clip_key": plan.ref.clip_key,
        "clip_sha256": str(clip.get("clip_sha256") or ""),
        "game": plan.ref.game,
        "other_name": plan.ref.other_name,
        "source": plan.ref.source,
        "source_kind": kind,
        "origin": origin,
        "public_examples_ok": examples_ok,
        "recorded_start_utc": str(clip.get("recorded_start_utc") or ""),
        "recorded_start_source": str(clip.get("recorded_start_source") or ""),
        "duration_s": clip.get("duration_s", ""),
        "native_width": width,
        "native_height": height,
        "padded": padded,
        "hdr": clip.get("hdr", ""),
        "vfr": clip.get("vfr", ""),
        "video_codec": str(clip.get("video_codec") or ""),
        "encoder_tag": str(clip.get("encoder_tag") or ""),
        "low_tier": plan.low_tier,
        "low_encoder": str(clip.get("low_encoder") or ""),
        "slots": len(plan.buckets),
        "derive_id": derive_id,
    }


def build_slot_rows(plan: ClipPlan, recipe: Recipe) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    frame_parts = (
        ("frames", "_other", plan.ref.other_name, plan.ref.source, plan.ref.clip_key)
        if plan.ref.game == OTHER
        else ("frames", plan.ref.game, plan.ref.source, plan.ref.clip_key)
    )
    for bucket in plan.buckets:
        path_full = rel_posix(
            *frame_parts, "full",
            frame_name(plan.ref.clip_key, "full", bucket),
        )
        if plan.low_tier:
            path_low = rel_posix(
                *frame_parts, plan.low_tier,
                frame_name(plan.ref.clip_key, plan.low_tier, bucket),
            )
        else:
            path_low = ""
        rows.append({
            "slot_id": slot_id(plan.ref.clip_key, bucket),
            "clip_key": plan.ref.clip_key,
            "game": plan.ref.game,
            "other_name": plan.ref.other_name,
            "source": plan.ref.source,
            "bucket": bucket,
            "target_time_s": float(bucket) * float(recipe.interval_s),
            "path_full": path_full,
            "path_low": path_low,
        })
    return rows


def resolve_origin_and_consent(
    fs_root: Path,
    plan: ClipPlan,
    index: dict[str, Any],
) -> tuple[str, bool]:
    kind = source_kind(plan.ref.source)
    sha = str(plan.clip.get("clip_sha256") or "")
    entry = index.get(sha) if sha else None
    pack_id = ""
    if isinstance(entry, dict):
        pack_id = str(entry.get("pack_id") or "")
    manifest = load_pack_manifest(fs_root, pack_id) if pack_id else None
    return pack_id, public_examples_ok(kind, manifest)


def derive_id_for(plan: ClipPlan, recipe: Recipe) -> str:
    return DERIVE_ID_COMPACT if _is_compact(plan, recipe) else DERIVE_ID


def write_indexes(
    data_root: Path,
    clip_rows: list[dict[str, Any]],
    slot_rows: list[dict[str, Any]],
) -> None:
    manifests = Path(data_root) / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    write_table(clip_rows, CLIPS_INDEX_COLUMNS, manifests / "clips_index.csv", manifests / "clips_index.json")
    write_table(slot_rows, SLOTS_COLUMNS, manifests / "slots.csv", manifests / "slots.json")


def rebuild_tables_from_disk(
    data_root: Path,
    fs_root: Path,
    recipe: Recipe,
    *,
    game: str | None = None,
    source: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Rebuild index rows from frame_sources + frames on disk. Returns (clips, slots, skip messages)."""
    index = load_index(fs_root)
    clip_rows: list[dict[str, Any]] = []
    slot_rows: list[dict[str, Any]] = []
    skips: list[str] = []
    for ref in find_clips(fs_root, game=game, source=source):
        plan = plan_clip(ref, recipe)
        if plan.skip_reason:
            skips.append(f"{ref.game}/{ref.source}/{ref.clip_key}: {plan.skip_reason}")
            continue
        if not output_complete(data_root, plan):
            skips.append(f"{ref.game}/{ref.source}/{ref.clip_key}: derived frames incomplete")
            continue
        origin, examples_ok = resolve_origin_and_consent(fs_root, plan, index)
        clip_rows.append(
            build_clip_row(
                plan, recipe, origin=origin, examples_ok=examples_ok, derive_id=derive_id_for(plan, recipe),
            )
        )
        slot_rows.extend(build_slot_rows(plan, recipe))
    clip_rows.sort(key=lambda r: (r["game"], r["other_name"], r["source"], r["clip_key"]))
    slot_rows.sort(key=lambda r: (r["game"], r["other_name"], r["source"], r["clip_key"], int(r["bucket"])))
    return clip_rows, slot_rows, skips


def run_derive(
    data_root: Path,
    recipe: Recipe,
    *,
    game: str | None = None,
    source: str | None = None,
    force: bool = False,
    index_only: bool = False,
) -> int:
    data_root = Path(data_root)
    fs_root = data_root / "frame_sources"
    if not fs_root.is_dir():
        print(f"Missing frame_sources: {fs_root}")
        return EXIT_USAGE

    tools = None
    if not index_only:
        try:
            tools = find_tools()
        except FFmpegNotFoundError as exc:
            print(f"ffmpeg problem: {exc}")
            return EXIT_USAGE

    refs = find_clips(fs_root, game=game, source=source)
    failed = 0
    derived = skipped = passthrough = 0
    report_skips: list[str] = []

    if not index_only:
        assert tools is not None
        for ref in refs:
            plan = plan_clip(ref, recipe)
            if plan.skip_reason:
                msg = f"{ref.game}/{ref.source}/{ref.clip_key}: {plan.skip_reason}"
                report_skips.append(msg)
                print(f"  skip {msg}")
                continue
            try:
                status = derive_clip(tools, data_root, plan, recipe, force=force)
            except (ToolError, OSError, ValueError) as exc:
                failed += 1
                print(f"  FAIL {ref.game}/{ref.source}/{ref.clip_key}: {exc}")
                continue
            if status == "skipped":
                skipped += 1
            elif status == "passthrough":
                passthrough += 1
            else:
                derived += 1
            if plan.unpaired:
                print(
                    f"  {ref.clip_key}: {len(plan.buckets)} slots "
                    f"({plan.unpaired} unpaired ignored)"
                )

    # --game / --source limit the image work only; the tables always cover every clip on disk.
    clip_rows, slot_rows, table_skips = rebuild_tables_from_disk(data_root, fs_root, recipe)
    for msg in table_skips:
        if msg not in report_skips and (game is None or msg.startswith(f"{game}/")):
            print(f"  skip {msg}")
    write_indexes(data_root, clip_rows, slot_rows)

    print(
        f"clips indexed: {len(clip_rows)}, slots: {len(slot_rows)}; "
        f"derived={derived}, passthrough={passthrough}, skipped_complete={skipped}, failed={failed}"
    )
    print(f"Wrote {data_root / 'manifests' / 'clips_index.csv'}")
    print(f"Wrote {data_root / 'manifests' / 'slots.csv'}")
    return EXIT_FAIL if failed else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfc-derive-frames",
        description="Derive 256x144 frames from frame_sources and rebuild clips_index / slots.",
    )
    p.add_argument("--data-root", type=Path, default=Path("data"), help="data root (default: data)")
    p.add_argument(
        "--recipe", type=Path, default=Path("config/recipe.json"),
        help="recipe JSON (default: config/recipe.json)",
    )
    p.add_argument("--game", default=None, help="only this game folder")
    p.add_argument("--source", default=None, help="only this source folder")
    p.add_argument("--force", action="store_true", help="derive again even when output is complete")
    p.add_argument(
        "--index-only", action="store_true",
        help="skip image work; rebuild tables from what is on disk",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"gfc-derive-frames {__version__}")
    try:
        recipe = load_recipe(args.recipe)
    except (RecipeError, OSError) as exc:
        print(f"Recipe problem: {exc}")
        return EXIT_USAGE
    if args.game is not None and args.game not in (*GAMES, OTHER):
        print(f"Unknown game: {args.game} (expected one of {', '.join((*GAMES, OTHER))})")
        return EXIT_USAGE
    return run_derive(
        args.data_root,
        recipe,
        game=args.game,
        source=args.source,
        force=args.force,
        index_only=args.index_only,
    )


if __name__ == "__main__":
    sys.exit(main())
