"""End-to-end derive-frames on synthetic frame_sources."""

from __future__ import annotations

import csv
from pathlib import Path

from game_frame_classifier.derive_frames import main
from game_frame_classifier.sourcing.hashing import jpeg_size, sha256_file
from tests.helpers.derive_frames_fixtures import (
    clip_key_for,
    copy_recipe,
    write_clip_tree,
    write_index_entry,
    write_pack_manifest,
)
from tests.helpers.ffmpeg_fixtures import requires_ffmpeg


def _read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


@requires_ffmpeg
def test_derive_16x9_4x3_compact_and_rerun(tmp_path):
    data = tmp_path / "data"
    fs = data / "frame_sources"
    recipe = copy_recipe(tmp_path / "recipe.json")

    sha_16 = "11" * 32
    sha_43 = "22" * 32
    sha_compact = "33" * 32
    sha_quick = "44" * 32
    sha_bad = "55" * 32

    write_clip_tree(
        fs, game="Valorant", source="tester", clip_sha256=sha_16,
        width=640, height=360, buckets=[0, 1], use_ffmpeg_jpegs=True,
        low_encoder="h264_d3d12va",
    )
    write_clip_tree(
        fs, game="Valorant", source="tester", clip_sha256=sha_43,
        width=640, height=480, buckets=[0], use_ffmpeg_jpegs=True,
    )
    write_clip_tree(
        fs, game="Valorant", source="contributor_alex", clip_sha256=sha_compact,
        width=256, height=144, buckets=[0], use_ffmpeg_jpegs=True,
    )
    write_clip_tree(
        fs, game="Valorant", source="contributor_alex", clip_sha256=sha_quick,
        width=640, height=360, buckets=[0, 2], tiers=("full",),
        use_ffmpeg_jpegs=True, low_encoder="",
    )
    # only crf45 → excluded
    write_clip_tree(
        fs, game="Valorant", source="tester", clip_sha256=sha_bad,
        width=640, height=360, buckets=[0], tiers=("crf45",),
        use_ffmpeg_jpegs=True,
    )

    for sha, source, pack in (
        (sha_16, "tester", "personal:run1"),
        (sha_43, "tester", "personal:run1"),
        (sha_compact, "contributor_alex", "pack-compact"),
        (sha_quick, "contributor_alex", "pack-quick"),
        (sha_bad, "tester", "personal:run1"),
    ):
        write_index_entry(
            fs, clip_sha256=sha, clip_key=clip_key_for(sha),
            pack_id=pack, game="Valorant", source=source,
        )
    write_pack_manifest(fs, "pack-compact", public_examples=False)
    write_pack_manifest(fs, "pack-quick", public_examples=True)

    # Snapshot compact source bytes before derive
    compact_key = clip_key_for(sha_compact)
    compact_src = (
        fs / "Valorant" / "contributor_alex" / compact_key / "full"
        / f"{compact_key}_full_b000000.jpg"
    )
    compact_bytes = compact_src.read_bytes()
    compact_sha = sha256_file(compact_src)

    code = main(["--data-root", str(data), "--recipe", str(recipe)])
    assert code == 0

    clips = _read_csv(data / "manifests" / "clips_index.csv")
    slots = _read_csv(data / "manifests" / "slots.csv")
    keys = {r["clip_key"] for r in clips}
    assert clip_key_for(sha_bad) not in keys
    assert clip_key_for(sha_16) in keys
    assert clip_key_for(sha_43) in keys
    assert clip_key_for(sha_compact) in keys
    assert clip_key_for(sha_quick) in keys

    by_key = {r["clip_key"]: r for r in clips}
    assert by_key[clip_key_for(sha_16)]["padded"] == "false"
    assert by_key[clip_key_for(sha_16)]["low_encoder"] == "h264_d3d12va"
    assert by_key[clip_key_for(sha_43)]["padded"] == "true"
    assert by_key[clip_key_for(sha_compact)]["derive_id"] == "compact_passthrough"
    assert by_key[clip_key_for(sha_16)]["derive_id"] == "pad16x9_bicubic_256x144_q2"
    assert by_key[clip_key_for(sha_quick)]["low_tier"] == ""
    assert by_key[clip_key_for(sha_quick)]["slots"] == "2"
    assert by_key[clip_key_for(sha_compact)]["public_examples_ok"] == "false"
    assert by_key[clip_key_for(sha_quick)]["public_examples_ok"] == "true"

    for row in slots:
        full = data / row["path_full"]
        assert full.is_file()
        assert jpeg_size(full) == (256, 144)
        if row["path_low"]:
            low = data / row["path_low"]
            assert low.is_file()
            assert jpeg_size(low) == (256, 144)
        else:
            assert row["clip_key"] == clip_key_for(sha_quick)

    compact_out = (
        data / "frames" / "Valorant" / "contributor_alex" / compact_key / "full"
        / f"{compact_key}_full_b000000.jpg"
    )
    assert compact_out.read_bytes() == compact_bytes
    assert sha256_file(compact_out) == compact_sha

    # Rerun: no image work (mtime/content unchanged for an already-complete clip)
    before = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in (data / "frames").rglob("*.jpg")
        if "_tmp" not in p.parts
    }
    slots_before = (data / "manifests" / "slots.csv").read_text(encoding="utf-8")
    clips_before = (data / "manifests" / "clips_index.csv").read_text(encoding="utf-8")

    code = main(["--data-root", str(data), "--recipe", str(recipe)])
    assert code == 0
    after = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in (data / "frames").rglob("*.jpg")
        if "_tmp" not in p.parts
    }
    assert after == before
    assert (data / "manifests" / "slots.csv").read_text(encoding="utf-8") == slots_before
    assert (data / "manifests" / "clips_index.csv").read_text(encoding="utf-8") == clips_before

    # --index-only reproduces identical tables
    (data / "manifests" / "slots.csv").write_text("junk\n", encoding="utf-8")
    code = main(["--data-root", str(data), "--recipe", str(recipe), "--index-only"])
    assert code == 0
    assert (data / "manifests" / "slots.csv").read_text(encoding="utf-8") == slots_before
    assert (data / "manifests" / "clips_index.csv").read_text(encoding="utf-8") == clips_before


@requires_ffmpeg
def test_new_clip_appears_without_touching_existing(tmp_path):
    data = tmp_path / "data"
    fs = data / "frame_sources"
    recipe = copy_recipe(tmp_path / "recipe.json")
    sha1 = "aa" * 32
    sha2 = "bb" * 32
    write_clip_tree(
        fs, game="CS2", source="tester", clip_sha256=sha1,
        width=640, height=360, buckets=[0], use_ffmpeg_jpegs=True,
    )
    write_index_entry(
        fs, clip_sha256=sha1, clip_key=clip_key_for(sha1),
        pack_id="personal:r", game="CS2", source="tester",
    )
    assert main(["--data-root", str(data), "--recipe", str(recipe)]) == 0
    key1 = clip_key_for(sha1)
    existing = list((data / "frames" / "CS2" / "tester" / key1).rglob("*.jpg"))
    assert existing
    stamp = {p: (p.stat().st_mtime_ns, sha256_file(p)) for p in existing}

    write_clip_tree(
        fs, game="CS2", source="tester", clip_sha256=sha2,
        width=640, height=360, buckets=[0], use_ffmpeg_jpegs=True,
    )
    write_index_entry(
        fs, clip_sha256=sha2, clip_key=clip_key_for(sha2),
        pack_id="personal:r", game="CS2", source="tester",
    )
    assert main(["--data-root", str(data), "--recipe", str(recipe)]) == 0

    for p, (mtime, digest) in stamp.items():
        assert p.stat().st_mtime_ns == mtime
        assert sha256_file(p) == digest
    keys = {r["clip_key"] for r in _read_csv(data / "manifests" / "clips_index.csv")}
    assert key1 in keys and clip_key_for(sha2) in keys


@requires_ffmpeg
def test_compact_pack_is_detected_from_the_stills_not_clip_json(tmp_path):
    """A compact pack's clip.json reports the original video size; its stills are already 256x144."""
    import json

    data = tmp_path / "data"
    fs = data / "frame_sources"
    recipe = copy_recipe(tmp_path / "recipe.json")
    clip_dir = write_clip_tree(
        fs, game="Valorant", source="contributor_x", clip_sha256="66" * 32,
        width=256, height=144, buckets=[0, 1], use_ffmpeg_jpegs=True,
    )
    meta = json.loads((clip_dir / "clip.json").read_text(encoding="utf-8"))
    meta.update(width=1920, height=1080)
    (clip_dir / "clip.json").write_text(json.dumps(meta), encoding="utf-8")
    assert main(["--data-root", str(data), "--recipe", str(recipe)]) == 0
    key = clip_key_for("66" * 32)
    for tier in ("full", "crf45"):
        for src in sorted((clip_dir / tier).glob("*.jpg")):
            out = data / "frames" / "Valorant" / "contributor_x" / key / tier / src.name
            assert sha256_file(out) == sha256_file(src)
    (row,) = _read_csv(data / "manifests" / "clips_index.csv")
    assert row["derive_id"] == "compact_passthrough"


@requires_ffmpeg
def test_game_filter_limits_work_but_tables_keep_every_clip(tmp_path):
    data = tmp_path / "data"
    fs = data / "frame_sources"
    recipe = copy_recipe(tmp_path / "recipe.json")
    write_clip_tree(fs, game="Valorant", source="tester", clip_sha256="77" * 32,
                    width=640, height=360, buckets=[0, 1], use_ffmpeg_jpegs=True)
    write_clip_tree(fs, game="CS2", source="tester", clip_sha256="88" * 32,
                    width=640, height=360, buckets=[0], use_ffmpeg_jpegs=True)
    assert main(["--data-root", str(data), "--recipe", str(recipe)]) == 0
    assert main(["--data-root", str(data), "--recipe", str(recipe), "--game", "Valorant"]) == 0
    games = sorted({r["game"] for r in _read_csv(data / "manifests" / "clips_index.csv")})
    assert games == ["CS2", "Valorant"]
    assert len(_read_csv(data / "manifests" / "slots.csv")) == 3


@requires_ffmpeg
def test_newer_source_stills_are_derived_again(tmp_path):
    import os
    import time

    data = tmp_path / "data"
    fs = data / "frame_sources"
    recipe = copy_recipe(tmp_path / "recipe.json")
    clip_dir = write_clip_tree(fs, game="Valorant", source="tester", clip_sha256="99" * 32,
                               width=640, height=360, buckets=[0], use_ffmpeg_jpegs=True)
    assert main(["--data-root", str(data), "--recipe", str(recipe)]) == 0
    key = clip_key_for("99" * 32)
    derived = data / "frames" / "Valorant" / "tester" / key / "full" / f"{key}_full_b000000.jpg"
    first = derived.stat().st_mtime
    src = clip_dir / "full" / f"{key}_full_b000000.jpg"
    later = time.time() + 5
    os.utime(src, (later, later))
    assert main(["--data-root", str(data), "--recipe", str(recipe)]) == 0
    assert derived.stat().st_mtime > first
