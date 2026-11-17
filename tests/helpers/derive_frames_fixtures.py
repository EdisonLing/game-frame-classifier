"""Synthetic frame_sources trees for derive-frames unit and system tests."""

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path
from typing import Any

from tests.helpers.ffmpeg_fixtures import ffmpeg_available

ROOT = Path(__file__).resolve().parents[2]


def minimal_jpeg(width: int = 16, height: int = 9) -> bytes:
    """Tiny valid grayscale baseline JPEG with the given SOF0 size."""
    raw = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000"
        "ffdb004300080606070605080707070909080a0c14"
        "0d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e"
        "2720222c231c1c2837292c30313434341f27393d38"
        "323c2e333432ffdb0043010909090c0b0c180d0d18"
        "32211c213232323232323232323232323232323232"
        "323232323232323232323232323232323232323232"
        "323232323232323232323232ffc0000b0800080001"
        "011100ffc4001f0000010501010101010100000000"
        "000000000102030405060708090a0bffc400b51000"
        "0201030302040304050504040000017d0102030004"
        "1105122131410613516107227114328191a1082342"
        "b1c11552d1f02433627282090a161718191a252627"
        "28292a3435363738393a434445464748494a535455"
        "565758595a636465666768696a737475767778797a"
        "838485868788898a92939495969798999aa2a3a4a5"
        "a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8"
        "c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9ea"
        "f1f2f3f4f5f6f7f8f9faffc4001f01000301010101"
        "01010101000000000000000102030405060708090a"
        "0bffc400b511000201020404030407050404000102"
        "770001020311040521310612415107617113223281"
        "08144291a1b1c109233352f0156272d10a162434e1"
        "25f11718191a262728292a35363738393a43444546"
        "4748494a535455565758595a636465666768696a73"
        "7475767778797a82838485868788898a9293949596"
        "9798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9"
        "bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3"
        "e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda000c03"
        "010002110311003f00fdfcf80a28a2803fffd9"
    )
    sof = raw.find(bytes.fromhex("ffc0000b08"))
    patched = bytearray(raw)
    struct.pack_into(">HH", patched, sof + 5, height, width)
    return bytes(patched)


def make_solid_jpeg(path: Path, width: int, height: int, *, color: str = "red") -> Path:
    """Write a real JPEG via ffmpeg (needed when derive must decode it)."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg required to build derive fixtures")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}",
        "-frames:v", "1", "-q:v", "2", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return path


def clip_key_for(sha_hex: str) -> str:
    return "c" + sha_hex[:12]


def default_clip_meta(
    *,
    clip_key: str,
    clip_sha256: str,
    width: int,
    height: int,
    low_encoder: str = "libx264",
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "clip_key": clip_key,
        "clip_sha256": clip_sha256,
        "status": "ok",
        "recorded_start_utc": "2026-01-02T03:04:05Z",
        "recorded_start_source": "mtime",
        "duration_s": 30.0,
        "width": width,
        "height": height,
        "hdr": False,
        "vfr": False,
        "video_codec": "h264",
        "encoder_tag": "Lavc",
        "low_encoder": low_encoder,
        "slots": 1,
        "expected_slots": 1,
        "unpaired_dropped": 0,
    }
    row.update(extra)
    return row


def write_clip_tree(
    fs_root: Path,
    *,
    game: str,
    source: str,
    clip_sha256: str,
    width: int,
    height: int,
    buckets: list[int],
    tiers: tuple[str, ...] = ("full", "crf45"),
    low_encoder: str = "libx264",
    use_ffmpeg_jpegs: bool = False,
    colors: dict[str, str] | None = None,
    extra_files: list[tuple[str, str, int]] | None = None,
) -> Path:
    """
    Create ``frame_sources/<game>/<source>/<clip_key>/{tiers}/...`` plus ``clip.json``.

    ``extra_files`` is a list of ``(tier, filename, bucket_or_-1)`` written as tiny JPEGs
    for unpaired-name tests (``bucket_or_-1`` unused for naming).
    """
    clip_key = clip_key_for(clip_sha256)
    clip_dir = Path(fs_root) / game / source / clip_key
    clip_dir.mkdir(parents=True, exist_ok=True)
    colors = colors or {}
    for tier in tiers:
        tier_dir = clip_dir / tier
        tier_dir.mkdir(parents=True, exist_ok=True)
        color = colors.get(tier, "red" if tier == "full" else "blue")
        for bucket in buckets:
            name = f"{clip_key}_{tier}_b{bucket:06d}.jpg"
            dest = tier_dir / name
            if use_ffmpeg_jpegs:
                make_solid_jpeg(dest, width, height, color=color)
            else:
                dest.write_bytes(minimal_jpeg(width, height))
    if extra_files:
        for tier, name, _ in extra_files:
            dest = clip_dir / tier / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(minimal_jpeg(width, height))
    meta = default_clip_meta(
        clip_key=clip_key,
        clip_sha256=clip_sha256,
        width=width,
        height=height,
        low_encoder=low_encoder,
        slots=len(buckets),
        expected_slots=len(buckets),
    )
    (clip_dir / "clip.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return clip_dir


def write_index_entry(
    fs_root: Path,
    *,
    clip_sha256: str,
    clip_key: str,
    pack_id: str,
    game: str,
    source: str,
) -> None:
    index_path = Path(fs_root) / "_index" / "by_sha256.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if index_path.is_file():
        data = json.loads(index_path.read_text(encoding="utf-8"))
    data[clip_sha256] = {
        "clip_key": clip_key,
        "pack_id": pack_id,
        "game": game,
        "source": source,
        "rel_dir": f"{game}/{source}/{clip_key}",
    }
    index_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_pack_manifest(
    fs_root: Path,
    pack_id: str,
    *,
    handle: str = "alex",
    public_examples: bool | None = False,
) -> Path:
    pack_dir = Path(fs_root) / "_packs" / pack_id
    pack_dir.mkdir(parents=True, exist_ok=True)
    consent: dict[str, Any] = {"data_use": True}
    if public_examples is not None:
        consent["public_examples"] = public_examples
    manifest = {
        "schema": "gfc.pack/1",
        "pack_id": pack_id,
        "contributor": {
            "handle": handle,
            "contributor_id": "cid-" + handle,
            "consent": consent,
        },
        "game": {"label": "Valorant"},
    }
    path = pack_dir / "pack_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def copy_recipe(dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text((ROOT / "config" / "recipe.json").read_text(encoding="utf-8"), encoding="utf-8")
    return dest
