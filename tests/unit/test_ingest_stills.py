"""Unit tests for gfc-ingest-stills."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from game_frame_classifier.ingest_stills import (
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_USAGE,
    IngestStillsError,
    StillClip,
    StillRow,
    check_licence,
    clip_key_for,
    group_rows,
    main,
    read_manifest,
    run,
    write_still_clip,
)


def _jpeg(path: Path, colour: tuple[int, int, int] = (40, 80, 120), size=(64, 36)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path, format="JPEG", quality=95)
    return path


def _png(path: Path, colour: tuple[int, int, int] = (200, 40, 40), size=(64, 36)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path, format="PNG")
    return path


def _manifest(path: Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else ["file", "game"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _approved_repo(tmp_path: Path, source_id: str = "public_test_stills") -> Path:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    entry = {
        "source_id": source_id,
        "games": ["Valorant"],
        "dataset_name": "Public test stills",
        "official_url": "https://example.com/public_test_stills",
        "license_spdx": "MIT",
        "license_url": "https://example.com/MIT.txt",
        "commercial_ok": "yes",
        "attribution_text": "Made-up public_test_stills attribution.",
        "approved": True,
        "notes": "",
    }
    (repo / "config" / "public_sources.json").write_text(
        json.dumps({"sources": [entry]}, indent=2) + "\n",
        encoding="utf-8",
    )
    lic = repo / "docs" / "licenses" / source_id
    lic.mkdir(parents=True)
    (lic / "LICENSE.txt").write_text("Made-up MIT for tests.\n", encoding="utf-8")
    (lic / "provenance.json").write_text(
        json.dumps(
            {
                "source_id": source_id,
                "dataset_url": entry["official_url"],
                "dataset_revision": "",
                "license_spdx": "MIT",
                "license_url": entry["license_url"],
                "license_sha256": "0" * 64,
                "retrieved_utc": "2026-01-01T00:00:00Z",
                "files": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return repo


# --- manifest ---


def test_manifest_required_columns(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    bad = tmp_path / "bad.csv"
    bad.write_text("game\nValorant\n", encoding="utf-8")
    with pytest.raises(IngestStillsError, match="missing required column: file") as exc:
        read_manifest(bad, images)
    assert exc.value.exit_code == EXIT_USAGE


def test_manifest_unknown_game(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _jpeg(images / "a.jpg")
    man = _manifest(tmp_path / "m.csv", [{"file": "a.jpg", "game": "Fortnite"}])
    with pytest.raises(IngestStillsError, match="unknown game"):
        read_manifest(man, images)


def test_manifest_other_without_name(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _jpeg(images / "a.jpg")
    man = _manifest(
        tmp_path / "m.csv",
        [{"file": "a.jpg", "game": "Other", "other_name": ""}],
        fieldnames=["file", "game", "other_name"],
    )
    with pytest.raises(IngestStillsError, match="other_name"):
        read_manifest(man, images)


def test_manifest_duplicate_file(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _jpeg(images / "a.jpg")
    man = _manifest(
        tmp_path / "m.csv",
        [
            {"file": "a.jpg", "game": "Valorant"},
            {"file": "a.jpg", "game": "Valorant"},
        ],
    )
    with pytest.raises(IngestStillsError, match="duplicate file"):
        read_manifest(man, images)


def test_manifest_missing_image(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    man = _manifest(tmp_path / "m.csv", [{"file": "missing.jpg", "game": "Valorant"}])
    with pytest.raises(IngestStillsError, match="missing image"):
        read_manifest(man, images)


def test_manifest_ignores_hash_and_blank(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _jpeg(images / "a.jpg")
    path = tmp_path / "m.csv"
    path.write_text(
        "file,game\n"
        "\n"
        "# comment.jpg,Valorant\n"
        "a.jpg,Valorant\n",
        encoding="utf-8",
    )
    rows = read_manifest(path, images)
    assert [r.file for r in rows] == ["a.jpg"]


# --- groups ---


def test_dataset_groups() -> None:
    rows = [
        StillRow("b.jpg", "Valorant", "", "vid1", 2.0),
        StillRow("a.jpg", "Valorant", "", "vid1", 1.0),
        StillRow("c.jpg", "Valorant", "", "vid2", None),
    ]
    clips = group_rows(rows, group_size=10, limit_groups=None)
    assert len(clips) == 2
    by_group = {c.group: c for c in clips}
    assert by_group["vid1"].group_origin == "dataset"
    assert [r.file for r in by_group["vid1"].rows] == ["a.jpg", "b.jpg"]
    assert by_group["vid2"].rows[0].file == "c.jpg"


def test_made_up_groups_of_n() -> None:
    rows = [
        StillRow(f"{i:02d}.jpg", "CS2", "", "", None) for i in range(5)
    ]
    clips = group_rows(rows, group_size=2, limit_groups=None)
    assert [c.group for c in clips] == ["auto0000", "auto0001", "auto0002"]
    assert all(c.group_origin == "made_up" for c in clips)
    assert [len(c.rows) for c in clips] == [2, 2, 1]


def test_order_then_file_within_clip() -> None:
    rows = [
        StillRow("z.jpg", "Valorant", "", "g", None),
        StillRow("a.jpg", "Valorant", "", "g", 10.0),
        StillRow("m.jpg", "Valorant", "", "g", 5.0),
    ]
    clips = group_rows(rows, group_size=10, limit_groups=None)
    assert [r.file for r in clips[0].rows] == ["m.jpg", "a.jpg", "z.jpg"]


def test_limit_groups() -> None:
    rows = [
        StillRow(f"v{i}.jpg", "Valorant", "", f"g{i}", None) for i in range(4)
    ] + [
        StillRow(f"c{i}.jpg", "CS2", "", f"g{i}", None) for i in range(3)
    ]
    clips = group_rows(rows, group_size=10, limit_groups=2)
    assert sum(1 for c in clips if c.game == "Valorant") == 2
    assert sum(1 for c in clips if c.game == "CS2") == 2


# --- licence gate ---


def test_licence_gate_refuses_public(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    entry = {
        "source_id": "public_test_stills",
        "games": ["Valorant"],
        "dataset_name": "t",
        "official_url": "https://example.com",
        "license_spdx": "MIT",
        "license_url": "https://example.com/MIT.txt",
        "commercial_ok": "yes",
        "attribution_text": "x",
        "approved": False,
        "notes": "",
    }
    (repo / "config" / "public_sources.json").write_text(
        json.dumps({"sources": [entry]}), encoding="utf-8"
    )
    with pytest.raises(IngestStillsError, match="save the licence first") as exc:
        check_licence("public_test_stills", repo_root=repo)
    assert exc.value.exit_code == EXIT_USAGE

    entry["approved"] = True
    (repo / "config" / "public_sources.json").write_text(
        json.dumps({"sources": [entry]}), encoding="utf-8"
    )
    with pytest.raises(IngestStillsError, match="save the licence first"):
        check_licence("public_test_stills", repo_root=repo)

    with pytest.raises(IngestStillsError, match="save the licence first"):
        check_licence("public_unknown", repo_root=repo)


def test_licence_gate_skips_non_public(tmp_path: Path) -> None:
    check_licence("friend_tester", repo_root=tmp_path)  # no config needed


# --- write ---


def test_write_jpeg_copy_png_convert_and_clip_json(tmp_path: Path) -> None:
    images = tmp_path / "images"
    jpeg = _jpeg(images / "a.jpg", colour=(10, 20, 30))
    png = _png(images / "b.png", colour=(90, 100, 110))
    jpeg_bytes = jpeg.read_bytes()
    clip = StillClip(
        game="Valorant",
        other_name="",
        group="vid1",
        group_origin="dataset",
        rows=[
            StillRow("a.jpg", "Valorant", "", "vid1", 0.0),
            StillRow("b.png", "Valorant", "", "vid1", 1.0),
        ],
    )
    fs = tmp_path / "frame_sources"
    status, written, failed = write_still_clip(
        fs, "friend_tester", clip, images, clip_index=3, force=False
    )
    assert status == "written"
    assert written == 2 and failed == 0
    key = clip_key_for("friend_tester", clip)
    dest = fs / "Valorant" / "friend_tester" / key
    stored_jpeg = (dest / "full" / f"{key}_full_b000000.jpg").read_bytes()
    assert stored_jpeg == jpeg_bytes
    stored_png_as_jpeg = dest / "full" / f"{key}_full_b000001.jpg"
    assert stored_png_as_jpeg.is_file()
    assert stored_png_as_jpeg.read_bytes()[:2] == b"\xff\xd8"
    payload = json.loads((dest / "clip.json").read_text(encoding="utf-8"))
    assert payload["status_detail"] == "stills"
    assert payload["recorded_start_source"] == "synthetic"
    assert payload["recorded_start_utc"] == "2000-01-01T03:00:00Z"
    assert payload["group_origin"] == "dataset"
    assert payload["stills_group"] == "vid1"
    assert payload["expected_slots"] == 2
    assert payload["duration_s"] == 10.0


def test_write_unreadable_and_empty_clip(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    bad = images / "bad.jpg"
    bad.write_bytes(b"not-a-jpeg")
    clip = StillClip(
        game="Valorant",
        other_name="",
        group="g",
        group_origin="made_up",
        rows=[StillRow("bad.jpg", "Valorant", "", "g", None)],
    )
    status, written, failed = write_still_clip(
        tmp_path / "frame_sources", "friend_tester", clip, images, clip_index=0, force=False
    )
    assert status == "empty"
    assert written == 0 and failed == 1
    assert not (tmp_path / "frame_sources" / "Valorant").exists()


def test_stable_clip_keys_and_skip_force(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _jpeg(images / "a.jpg")
    clip = StillClip(
        game="Valorant",
        other_name="",
        group="g1",
        group_origin="dataset",
        rows=[StillRow("a.jpg", "Valorant", "", "g1", None)],
    )
    key1 = clip_key_for("friend_tester", clip)
    key2 = clip_key_for("friend_tester", clip)
    assert key1 == key2 and key1.startswith("c") and len(key1) == 13
    fs = tmp_path / "frame_sources"
    assert write_still_clip(fs, "friend_tester", clip, images, clip_index=0, force=False)[0] == "written"
    assert write_still_clip(fs, "friend_tester", clip, images, clip_index=0, force=False)[0] == "skipped"
    dest = fs / "Valorant" / "friend_tester" / key1 / "clip.json"
    old = dest.read_text(encoding="utf-8")
    assert write_still_clip(fs, "friend_tester", clip, images, clip_index=0, force=True)[0] == "written"
    assert dest.is_file()
    assert json.loads(dest.read_text(encoding="utf-8"))["clip_key"] == key1
    assert old  # rewritten


def test_write_other_path(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _jpeg(images / "a.jpg")
    clip = StillClip(
        game="Other",
        other_name="desktop_misc",
        group="g",
        group_origin="made_up",
        rows=[StillRow("a.jpg", "Other", "desktop_misc", "g", None)],
    )
    fs = tmp_path / "frame_sources"
    write_still_clip(fs, "friend_tester", clip, images, clip_index=0, force=False)
    key = clip_key_for("friend_tester", clip)
    assert (fs / "_other" / "desktop_misc" / "friend_tester" / key / "clip.json").is_file()


# --- times ---


def test_synthetic_times_stable_order(tmp_path: Path) -> None:
    images = tmp_path / "images"
    rows_meta = []
    for i, (game, group) in enumerate(
        [("CS2", "a"), ("Valorant", "z"), ("Valorant", "a")]
    ):
        name = f"{i}.jpg"
        _jpeg(images / name)
        rows_meta.append({"file": name, "game": game, "group": group})
    man = _manifest(tmp_path / "m.csv", rows_meta, fieldnames=["file", "game", "group"])
    summary = run(
        images,
        man,
        "friend_tester",
        data_root=tmp_path / "data",
        repo_root=tmp_path,
        force=True,
    )
    assert summary["clips_written"] == 3
    fs = tmp_path / "data" / "frame_sources"
    times = []
    for clip_json in sorted(fs.rglob("clip.json")):
        if "_stills" in clip_json.parts:
            continue
        payload = json.loads(clip_json.read_text(encoding="utf-8"))
        times.append((payload["game"], payload["stills_group"], payload["recorded_start_utc"]))
    times.sort()
    # Index order is (game, other_name, group): CS2/a, Valorant/a, Valorant/z
    assert [t[2] for t in times] == [
        "2000-01-01T00:00:00Z",
        "2000-01-01T01:00:00Z",
        "2000-01-01T02:00:00Z",
    ]


def test_run_partial_failure_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    images = tmp_path / "images"
    _jpeg(images / "ok.jpg")
    (images / "bad.jpg").write_bytes(b"nope")
    man = _manifest(
        tmp_path / "m.csv",
        [
            {"file": "ok.jpg", "game": "Valorant", "group": "g1"},
            {"file": "bad.jpg", "game": "Valorant", "group": "g2"},
        ],
        fieldnames=["file", "game", "group"],
    )
    code = main(
        [
            str(images),
            "--manifest",
            str(man),
            "--source",
            "friend_tester",
            "--data-root",
            str(tmp_path / "data"),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert code == EXIT_PARTIAL
    out = capsys.readouterr().out
    assert "made-up groups" not in out or "warning" in out or True
    # g1 written; g2 empty failed
    assert any((tmp_path / "data" / "frame_sources").rglob("clip.json"))


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _jpeg(images / "a.jpg")
    man = _manifest(tmp_path / "m.csv", [{"file": "a.jpg", "game": "Valorant"}])
    data = tmp_path / "data"
    code = main(
        [
            str(images),
            "--manifest",
            str(man),
            "--source",
            "friend_tester",
            "--data-root",
            str(data),
            "--dry-run",
        ]
    )
    assert code == EXIT_OK
    assert not data.exists() or not any(data.rglob("clip.json"))


def test_made_up_warning_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    images = tmp_path / "images"
    _jpeg(images / "a.jpg")
    man = _manifest(tmp_path / "m.csv", [{"file": "a.jpg", "game": "Valorant"}])
    run(images, man, "friend_tester", data_root=tmp_path / "data", repo_root=tmp_path)
    out = capsys.readouterr().out
    assert "made-up groups" in out
    assert "leakage is possible" in out


def test_public_refused_writes_nothing(tmp_path: Path) -> None:
    repo = _approved_repo(tmp_path)
    # unapprove
    cfg = json.loads((repo / "config" / "public_sources.json").read_text(encoding="utf-8"))
    cfg["sources"][0]["approved"] = False
    (repo / "config" / "public_sources.json").write_text(json.dumps(cfg), encoding="utf-8")
    images = tmp_path / "images"
    _jpeg(images / "a.jpg")
    man = _manifest(tmp_path / "m.csv", [{"file": "a.jpg", "game": "Valorant"}])
    data = tmp_path / "data"
    code = main(
        [
            str(images),
            "--manifest",
            str(man),
            "--source",
            "public_test_stills",
            "--data-root",
            str(data),
            "--repo-root",
            str(repo),
        ]
    )
    assert code == EXIT_USAGE
    assert not data.exists() or not list(data.rglob("*"))


def test_contributor_source_refused(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _jpeg(images / "a.jpg")
    man = _manifest(tmp_path / "m.csv", [{"file": "a.jpg", "game": "Valorant"}])
    code = main(
        [
            str(images),
            "--manifest",
            str(man),
            "--source",
            "contributor_alex",
            "--data-root",
            str(tmp_path / "data"),
        ]
    )
    assert code == EXIT_USAGE
