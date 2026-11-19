"""System: stills ingest → derive → clean --slots → split keeps clips whole."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image

from game_frame_classifier.dataset_splitter import main as split_main
from game_frame_classifier.derive_frames import main as derive_main
from game_frame_classifier.frame_cleaner import main as clean_main
from game_frame_classifier.ingest_stills import main as ingest_main
from game_frame_classifier.public_sources import clips_on_disk, source_status
from tests.helpers.derive_frames_fixtures import copy_recipe
from tests.helpers.ffmpeg_fixtures import requires_ffmpeg
from tests.helpers.splitter_fixtures import write_split_config


def _write_still(path: Path, colour: tuple[int, int, int], *, png: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Compact size so derive can passthrough; asymmetric so the cleaner keeps them.
    im = Image.new("RGB", (256, 144), colour)
    px = im.load()
    for y in range(144):
        for x in range(40, 80):
            px[x, y] = (255, max(colour[1], 1), 0)
        for x in range(176, 216):
            px[x, y] = (0, 0, 255)
    if png:
        im.save(path, format="PNG")
    else:
        im.save(path, format="JPEG", quality=95)


def _approved_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    entry = {
        "source_id": "public_test_stills",
        "games": ["Valorant", "CS2"],
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
    lic = repo / "docs" / "licenses" / "public_test_stills"
    lic.mkdir(parents=True)
    (lic / "LICENSE.txt").write_text("Made-up MIT for system test.\n", encoding="utf-8")
    (lic / "provenance.json").write_text(
        json.dumps(
            {
                "source_id": "public_test_stills",
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


@requires_ffmpeg
def test_ingest_derive_clean_split_keeps_clips_whole(tmp_path: Path) -> None:
    repo = _approved_repo(tmp_path)
    data = tmp_path / "data"
    images = tmp_path / "images"

    # Valorant: 15 JPEGs across 3 dataset groups (5 each).
    # CS2: 15 stills (10 JPEG + 5 PNG) with no group → made-up groups of 5.
    rows: list[dict[str, str]] = []
    for gi in range(3):
        for si in range(5):
            name = f"val_g{gi}_{si}.jpg"
            _write_still(images / name, (30 + gi * 40, 80 + si * 10, 120))
            rows.append({"file": name, "game": "Valorant", "group": f"vid{gi}", "order": str(si)})
    for i in range(10):
        name = f"cs2_{i:02d}.jpg"
        _write_still(images / name, (20, 40 + i * 5, 60))
        rows.append({"file": name, "game": "CS2", "group": "", "order": ""})
    for i in range(5):
        name = f"cs2_png_{i}.png"
        _write_still(images / name, (100, 20 + i * 10, 40), png=True)
        rows.append({"file": name, "game": "CS2", "group": "", "order": ""})

    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "game", "group", "order"])
        writer.writeheader()
        writer.writerows(rows)

    code = ingest_main(
        [
            str(images),
            "--manifest",
            str(manifest),
            "--source",
            "public_test_stills",
            "--group-size",
            "5",
            "--data-root",
            str(data),
            "--repo-root",
            str(repo),
        ]
    )
    assert code == 0

    fs = data / "frame_sources"
    val_clips = list((fs / "Valorant" / "public_test_stills").iterdir())
    cs2_clips = list((fs / "CS2" / "public_test_stills").iterdir())
    assert len(val_clips) == 3
    assert len(cs2_clips) == 3  # 15 stills / group-size 5
    origins = {
        json.loads((c / "clip.json").read_text(encoding="utf-8"))["group_origin"]
        for c in val_clips
    }
    assert origins == {"dataset"}
    cs2_origins = {
        json.loads((c / "clip.json").read_text(encoding="utf-8"))["group_origin"]
        for c in cs2_clips
    }
    assert cs2_origins == {"made_up"}

    # Provenance lists the manifest.
    provenance = json.loads(
        (repo / "docs/licenses/public_test_stills/provenance.json").read_text(encoding="utf-8")
    )
    assert any(f.get("name") == manifest.name for f in provenance["files"])

    recipe = copy_recipe(tmp_path / "recipe.json")
    assert derive_main(["--data-root", str(data), "--recipe", str(recipe)]) == 0
    slots = data / "manifests" / "slots.csv"
    assert slots.is_file()
    assert clean_main(["--slots", str(slots), "--data-root", str(data)]) == 0
    assert (data / "manifests" / "slots_clean.csv").is_file()

    # Split config beside an approved public_sources.json so licenses.json can resolve.
    config_dir = tmp_path / "split_config"
    config_dir.mkdir()
    (config_dir / "public_sources.json").write_text(
        (repo / "config" / "public_sources.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    split_config = write_split_config(
        config_dir / "split.json",
        split_id="stills_sys",
        max_source_share=1.0,
    )
    assert split_main(["--data-root", str(data), "--config", str(split_config)]) == 0

    split_dir = data / "manifests" / "splits" / "stills_sys"
    clip_to_splits: dict[str, set[str]] = defaultdict(set)
    for split_name in ("train", "val", "test_session", "test_source"):
        path = split_dir / f"{split_name}.csv"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                clip_to_splits[row["clip_key"]].add(split_name)
    assert clip_to_splits
    assert all(len(splits) == 1 for splits in clip_to_splits.values())

    licenses = json.loads((split_dir / "licenses.json").read_text(encoding="utf-8"))
    assert [s["source_id"] for s in licenses["sources"]] == ["public_test_stills"]

    assert source_status("public_test_stills", data, repo) == "active"
    counts = clips_on_disk(data, "public_test_stills")
    assert counts.get("Valorant") == 3
    assert counts.get("CS2") == 3
