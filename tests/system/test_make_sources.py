"""System and parity tests for gfc-make-sources."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from game_frame_classifier.frame_export import cli as frame_export_cli
from game_frame_classifier.frame_export import paths as frame_export_paths
from game_frame_classifier.ingest_pack import main as ingest_main
from game_frame_classifier.make_sources import main
from game_frame_classifier.sourcing.hashing import sha256_file
from tests.helpers.make_sources_fixtures import RECIPE, ROOT, data_tree, make_raw_clip, requires_ffmpeg

USER = {
    "schema": "gfc.user/1",
    "contributor_id": "00000000-0000-4000-8000-000000000001",
    "handle": "tester",
    "consent_data_use": True,
    "consent_public_examples": False,
    "consent_utc": "2026-01-01T00:00:00Z",
    "last_game": "",
    "frame_mode_override": None,
}


def _image_sha_list(clip_dir: Path) -> list[str]:
    paths = sorted(p for p in clip_dir.rglob("*.jpg") if p.is_file())
    return [sha256_file(p) for p in paths]


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    if not root.exists():
        return {}
    return {
        p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


@requires_ffmpeg
def test_two_clips_then_rerun_rebuild_dry_run(tmp_path):
    data_root, source_dir = data_tree(tmp_path)
    make_raw_clip(source_dir, "one.mp4", duration_s=12.0)
    make_raw_clip(source_dir / "nested", "two.mp4", duration_s=7.0)

    assert main(["--data-root", str(data_root), "--recipe", str(RECIPE)]) == 0

    fs = data_root / "frame_sources"
    clip_dirs = sorted((fs / "Valorant" / "tester").glob("c*"))
    assert len(clip_dirs) == 2
    for clip_dir in clip_dirs:
        assert (clip_dir / "clip.json").is_file()
        assert (clip_dir / "full").is_dir()
        assert (clip_dir / "crf45").is_dir()
        full = list((clip_dir / "full").glob("*.jpg"))
        crf = list((clip_dir / "crf45").glob("*.jpg"))
        assert full and crf and len(full) == len(crf)
        for jpg in full + crf:
            assert jpg.name.startswith(clip_dir.name + "_")
            assert "_b" in jpg.name
        clip = json.loads((clip_dir / "clip.json").read_text(encoding="utf-8"))
        assert clip["status"] == "ok"
        assert clip["slots"] == clip["expected_slots"] >= 1
        assert clip["original_relpath"] in ("one.mp4", "nested/two.mp4")

    index = json.loads((fs / "_index" / "by_sha256.json").read_text(encoding="utf-8"))
    assert len(index) == 2
    for sha, rec in index.items():
        assert rec["clip_key"] == "c" + sha[:12]
        assert rec["pack_id"].startswith("personal:")
        assert rec["game"] == "Valorant"
        assert rec["source"] == "tester"
        assert rec["rel_dir"] == f"Valorant/tester/{rec['clip_key']}"

    personal_runs = sorted((fs / "_personal").iterdir())
    assert len(personal_runs) == 1
    run_dir = personal_runs[0]
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "gfc.personal_run/1"
    assert manifest["input"]["clips_ok"] == 2
    assert manifest["output"]["tiers"] == ["full", "crf45"]
    assert manifest["output"]["frame_mode"] == "native"
    assert (run_dir / "clips.json").is_file()
    assert (run_dir / "frames.json").is_file()
    frames = json.loads((run_dir / "frames.json").read_text(encoding="utf-8"))
    assert frames and all(not f["rel_path"].startswith("/") for f in frames)
    assert all(f["rel_path"].startswith("Valorant/tester/") for f in frames)

    before = _tree_snapshot(fs / "Valorant")
    index_before = (fs / "_index" / "by_sha256.json").read_text(encoding="utf-8")
    assert main(["--data-root", str(data_root), "--recipe", str(RECIPE)]) == 0
    assert _tree_snapshot(fs / "Valorant") == before
    assert (fs / "_index" / "by_sha256.json").read_text(encoding="utf-8") == index_before
    assert len(list((fs / "_personal").iterdir())) == 2
    second_manifest = json.loads(
        sorted((fs / "_personal").glob("*/run_manifest.json"))[-1].read_text(encoding="utf-8")
    )
    assert second_manifest["input"]["clips_ok"] == 0
    assert second_manifest["input"]["clips_skipped_existing"] == 2

    target = clip_dirs[0]
    clip_key = target.name
    old_hashes = _image_sha_list(target)
    assert main([
        "--data-root", str(data_root), "--recipe", str(RECIPE), "--rebuild", clip_key,
    ]) == 0
    assert target.is_dir()
    new_hashes = _image_sha_list(target)
    assert new_hashes == old_hashes
    rebuilt_index = json.loads((fs / "_index" / "by_sha256.json").read_text(encoding="utf-8"))
    assert any(rec["clip_key"] == clip_key for rec in rebuilt_index.values())

    snap = _tree_snapshot(fs)
    assert main([
        "--data-root", str(data_root), "--recipe", str(RECIPE), "--dry-run",
    ]) == 0
    assert _tree_snapshot(fs) == snap


@requires_ffmpeg
def test_dry_run_leaves_tree_unchanged(tmp_path):
    data_root, source_dir = data_tree(tmp_path)
    make_raw_clip(source_dir, "only.mp4", duration_s=6.0)
    fs = data_root / "frame_sources"
    before = _tree_snapshot(data_root)
    assert main(["--data-root", str(data_root), "--recipe", str(RECIPE), "--dry-run"]) == 0
    assert _tree_snapshot(data_root) == before
    assert not fs.exists()


@requires_ffmpeg
def test_parity_with_frame_export_and_ingest(tmp_path, monkeypatch):
    """Same clip via Frame Export Kit + ingest vs make-sources → identical image digests."""
    video_src = tmp_path / "shared"
    video_src.mkdir()
    make_raw_clip(video_src, "match.mp4", duration_s=12.0, width=320, height=180)

    # Path A: frame-export → zip → ingest
    home = tmp_path / "tool"
    (home / "config").mkdir(parents=True)
    shutil.copyfile(ROOT / "config" / "recipe.json", home / "config" / "recipe.json")
    (home / "config" / "user.json").write_text(json.dumps(USER), encoding="utf-8")
    monkeypatch.setattr(frame_export_paths, "app_home", lambda: home)
    export_clips = tmp_path / "export_clips"
    export_clips.mkdir()
    shutil.copyfile(video_src / "match.mp4", export_clips / "match.mp4")
    assert frame_export_cli.main([
        str(export_clips), "--yes", "--game", "Valorant", "--no-open", "--budget-hours", "0", "--cpu",
    ]) == 0
    zips = sorted((home / "output").glob("GFC_Valorant_tester_*.zip"))
    assert len(zips) == 1
    ingest_root = tmp_path / "ingest_data"
    assert ingest_main([
        str(zips[0]), "--data-root", str(ingest_root), "--recipe", str(RECIPE),
    ]) == 0
    ingest_clips = list((ingest_root / "frame_sources" / "Valorant" / "contributor_tester").glob("c*"))
    assert len(ingest_clips) == 1
    ingest_hashes = _image_sha_list(ingest_clips[0])
    assert ingest_hashes

    # Path B: make-sources
    personal_root, source_dir = data_tree(tmp_path / "personal")
    shutil.copyfile(video_src / "match.mp4", source_dir / "match.mp4")
    assert main(["--data-root", str(personal_root), "--recipe", str(RECIPE), "--cpu"]) == 0
    personal_clips = list((personal_root / "frame_sources" / "Valorant" / "tester").glob("c*"))
    assert len(personal_clips) == 1
    personal_hashes = _image_sha_list(personal_clips[0])

    assert personal_clips[0].name == ingest_clips[0].name
    assert personal_hashes == ingest_hashes


@requires_ffmpeg
def test_cpu_run_records_encoder_per_frame_and_clip(tmp_path):
    data_root, source_dir = data_tree(tmp_path)
    make_raw_clip(source_dir, "one.mp4", duration_s=12.0, width=320, height=180)
    assert main(["--data-root", str(data_root), "--recipe", str(RECIPE), "--cpu"]) == 0
    fs = data_root / "frame_sources"
    run_dir = next((fs / "_personal").iterdir())
    frames = json.loads((run_dir / "frames.json").read_text(encoding="utf-8"))
    low = [f for f in frames if f["tier"] != "full"]
    full = [f for f in frames if f["tier"] == "full"]
    assert low and all(f["encoder"] == "libx264" and f["encoder_rc"] == "crf45" for f in low)
    assert full and all(f["encoder"] == "" and f["encoder_rc"] == "" for f in full)
    clip = json.loads(next((fs / "Valorant" / "tester").glob("c*/clip.json")).read_text(encoding="utf-8"))
    assert clip["low_encoder"] == "libx264" and clip["gpu_fallback"] == ""
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["encoder"]["requested"] == "cpu"
    assert manifest["encoder"]["clips_cpu"] == 1
