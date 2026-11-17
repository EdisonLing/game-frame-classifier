"""End-to-end ingest of synthetic contributor packs."""

from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

import pytest

from game_frame_classifier.ingest_pack import main
from game_frame_classifier.sourcing.packzip import write_pack_zip
from game_frame_classifier.sourcing.recipe import load_recipe

ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = "gfc_pack_aabbccdd"
PACK_ID = "00000000-0000-4000-8000-0000000000aa"
CLIP_SHA = "a" * 64
CLIP_KEY = "c" + CLIP_SHA[:12]


def _minimal_jpeg(width: int = 8, height: int = 8) -> bytes:
    """Tiny valid grayscale baseline JPEG (SOF0) with given size."""
    # Precomputed 8x8 grey JPEG; width/height patched in SOF0.
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
    # Patch SOF0 height/width at the standard offset for this blob (after FFC0 000B 08)
    sof = raw.find(bytes.fromhex("ffc0000b08"))
    assert sof != -1
    patched = bytearray(raw)
    struct.pack_into(">HH", patched, sof + 5, height, width)
    return bytes(patched)


def make_pack_dir(tmp_path: Path, *, game: str = "Valorant", other_name: str | None = None) -> Path:
    jpeg = _minimal_jpeg(16, 9)
    sha = __import__("hashlib").sha256(jpeg).hexdigest()
    pack = tmp_path / PACK_ROOT
    rel = f"frames/{CLIP_KEY}/full/{CLIP_KEY}_full_b000000.jpg"
    path = pack / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(jpeg)
    crf_rel = f"frames/{CLIP_KEY}/crf45/{CLIP_KEY}_crf45_b000000.jpg"
    crf_path = pack / crf_rel
    crf_path.parent.mkdir(parents=True)
    crf_path.write_bytes(jpeg)

    recipe = load_recipe(ROOT / "config" / "recipe.json").to_manifest()
    clip = {
        "clip_key": CLIP_KEY,
        "clip_sha256": CLIP_SHA,
        "quick_id": "b" * 16,
        "status": "ok",
        "status_detail": "",
        "original_filename": "clip.mp4",
        "original_relpath": "clip.mp4",
        "aliases": [],
        "file_bytes": 1000,
        "expected_slots": 1,
        "slots": 1,
        "unpaired_dropped": 0,
        "width": 16,
        "height": 9,
    }
    # clip_key must match sha[:12] — override CLIP_SHA to match key derived from a real sha of empty?
    # Spec requires clip_key == c + sha[:12]. Use sha of jpeg for clip_sha256.
    real_sha = sha
    real_key = "c" + real_sha[:12]
    # rewrite paths with real_key
    import shutil
    shutil.rmtree(pack)
    pack.mkdir()
    for tier, rel_tier in (("full", f"frames/{real_key}/full/{real_key}_full_b000000.jpg"),
                           ("crf45", f"frames/{real_key}/crf45/{real_key}_crf45_b000000.jpg")):
        p = pack / rel_tier
        p.parent.mkdir(parents=True)
        p.write_bytes(jpeg)
    clip["clip_key"] = real_key
    clip["clip_sha256"] = real_sha
    frames = [
        {
            "image_id": f"{real_key}:full:b000000",
            "slot_id": f"{real_key}:b000000",
            "clip_key": real_key,
            "tier": "full",
            "crf": None,
            "bucket": 0,
            "target_time_s": 0.0,
            "pts_time_s": 0.0,
            "rel_path": f"frames/{real_key}/full/{real_key}_full_b000000.jpg",
            "width": 16,
            "height": 9,
            "bytes": len(jpeg),
            "sha256": real_sha,
        },
        {
            "image_id": f"{real_key}:crf45:b000000",
            "slot_id": f"{real_key}:b000000",
            "clip_key": real_key,
            "tier": "crf45",
            "crf": 45,
            "bucket": 0,
            "target_time_s": 0.0,
            "pts_time_s": 0.0,
            "rel_path": f"frames/{real_key}/crf45/{real_key}_crf45_b000000.jpg",
            "width": 16,
            "height": 9,
            "bytes": len(jpeg),
            "sha256": real_sha,
        },
    ]
    files_for_count = [
        pack / frames[0]["rel_path"],
        pack / frames[1]["rel_path"],
    ]
    (pack / "clips.json").write_text(json.dumps([clip]), encoding="utf-8")
    (pack / "frames.json").write_text(json.dumps(frames), encoding="utf-8")
    (pack / "clips.csv").write_text("clip_key\n" + real_key + "\n", encoding="utf-8")
    (pack / "frames.csv").write_text("image_id\n", encoding="utf-8")
    (pack / "run_log.txt").write_text("ok\n", encoding="utf-8")
    body_files = [p for p in pack.rglob("*") if p.is_file()]
    manifest = {
        "schema": "gfc.pack/1",
        "pack_id": PACK_ID,
        "recipe": recipe,
        "ffmpeg": {"build": "bundled"},
        "contributor": {
            "handle": "alex",
            "contributor_id": "11111111-1111-4111-8111-111111111111",
            "consent": {"data_use": True, "public_examples": True, "acknowledged_utc": "2026-01-01T00:00:00Z"},
        },
        "game": {"label": game, "other_name": other_name},
        "input": {"input_bytes": 5000, "clips_ok": 1},
        "output": {
            "tiers": ["full", "crf45"],
            "frame_mode": "native",
            "slots": 1,
            "images": 2,
            "file_count": len(body_files),
            "uncompressed_bytes": sum(p.stat().st_size for p in body_files),
        },
    }
    (pack / "pack_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    # fix file_count to include manifest? write_pack_zip counts all files then validate expects count+1 = entries
    # Remount: recount after writing manifest
    body_files = [p for p in pack.rglob("*") if p.is_file() and p.name != "pack_manifest.json"]
    manifest["output"]["file_count"] = len(body_files)
    manifest["output"]["uncompressed_bytes"] = sum(p.stat().st_size for p in body_files)
    (pack / "pack_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return pack


def snapshot(folder: Path) -> dict[str, int]:
    if not folder.exists():
        return {}
    return {p.relative_to(folder).as_posix(): p.stat().st_size for p in folder.rglob("*") if p.is_file()}


def test_ingest_places_and_skips_duplicate(tmp_path):
    pack = make_pack_dir(tmp_path / "src")
    z = tmp_path / "pack.zip"
    write_pack_zip(pack, z)
    data = tmp_path / "data"
    assert main([str(z), "--data-root", str(data), "--recipe", str(ROOT / "config" / "recipe.json")]) == 0
    fs = data / "frame_sources"
    assert (fs / "_packs" / PACK_ID / "ingest.json").is_file()
    assert (fs / "_index" / "by_sha256.json").is_file()
    assert (fs / "_stats" / "handoff_sizes.jsonl").is_file()
    placed = list((fs / "Valorant" / "contributor_alex").glob("c*/full/*.jpg"))
    assert len(placed) == 1
    before = snapshot(fs)
    assert main([str(z), "--data-root", str(data), "--recipe", str(ROOT / "config" / "recipe.json")]) == 1
    # without --force, second ingest of same pack_id fails
    assert snapshot(fs) == before
    assert main([str(z), "--data-root", str(data), "--recipe", str(ROOT / "config" / "recipe.json"), "--force"]) == 0


def test_dry_run_writes_nothing(tmp_path):
    pack = make_pack_dir(tmp_path / "src")
    z = tmp_path / "pack.zip"
    write_pack_zip(pack, z)
    data = tmp_path / "data"
    data.mkdir()
    before = snapshot(data)
    assert main([str(z), "--data-root", str(data), "--recipe", str(ROOT / "config" / "recipe.json"), "--dry-run"]) == 0
    # scratch may appear then be removed; allow empty frame_sources/_tmp absence
    after = {k: v for k, v in snapshot(data).items() if not k.startswith("frame_sources/_tmp")}
    assert after == before


def test_bad_zip_writes_nothing(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.jpg", b"x")
    before = snapshot(data)
    assert main([str(z), "--data-root", str(data), "--recipe", str(ROOT / "config" / "recipe.json")]) == 1
    assert snapshot(data) == before
