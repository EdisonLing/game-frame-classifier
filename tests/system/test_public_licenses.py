"""System: fake host → licence fetch → clip on disk → split → gfc-licenses active."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from game_frame_classifier.dataset_splitter import run_split
from game_frame_classifier.public_sources import (
    fetch_license,
    main as licenses_main,
    record_download,
    source_status,
    update_documents,
)
from tests.helpers.splitter_fixtures import write_split_config, write_split_inputs


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_fake_host_ingest_split_and_licenses_doc(tmp_path: Path) -> None:
    host = tmp_path / "host"
    host.mkdir()
    license_text = b"Made-up MIT licence for system test.\n"
    (host / "MIT.txt").write_bytes(license_text)
    archive = host / "demo.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", "demo archive")

    repo = tmp_path / "repo"
    data = repo / "data"
    config_dir = repo / "config"
    config_dir.mkdir(parents=True)
    entry = {
        "source_id": "public_vpt_contractor",
        "games": ["Minecraft"],
        "dataset_name": "OpenAI VPT contractor demos",
        "official_url": "https://example.com/vpt",
        "license_spdx": "MIT",
        "license_url": str((host / "MIT.txt").as_uri()),
        "commercial_ok": "review",
        "attribution_text": "Made-up VPT attribution (MIT).",
        "approved": True,
        "notes": "",
    }
    (config_dir / "public_sources.json").write_text(
        json.dumps({"sources": [entry]}, indent=2) + "\n",
        encoding="utf-8",
    )
    ledger = repo / "docs" / "research" / "public-sources-ledger.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "# Ledger\n\n<!-- ledger:start -->\n<!-- ledger:end -->\n",
        encoding="utf-8",
    )

    def opener(url: str, *args: object, **kwargs: object) -> _FakeResponse:
        assert url == entry["license_url"]
        return _FakeResponse(license_text)

    fetch_license(
        "public_vpt_contractor",
        repo_root=repo,
        opener=opener,
        now=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    record_download("public_vpt_contractor", archive, repo_root=repo)
    assert (
        repo / "docs/licenses/public_vpt_contractor/LICENSE.txt"
    ).read_bytes() == license_text
    assert source_status("public_vpt_contractor", data, repo) == "downloaded"

    clip = data / "frame_sources" / "Minecraft" / "public_vpt_contractor" / "c0000000000aa"
    clip.mkdir(parents=True)
    (clip / "clip.json").write_text("{}", encoding="utf-8")
    assert source_status("public_vpt_contractor", data, repo) == "active"

    # Derive-like manifests for a tiny split that includes the public source.
    write_split_inputs(
        data,
        [
            {
                "source": "public_vpt_contractor",
                "source_kind": "public",
                "game": "Minecraft",
                "recorded_start_utc": "2026-01-01T00:00:00Z",
            },
            {
                "source": "me",
                "source_kind": "personal",
                "game": "Minecraft",
                "recorded_start_utc": "2026-01-01T01:00:00Z",
            },
        ],
        slots_per_clip=2,
    )
    split_config = write_split_config(
        config_dir / "split.json",
        split_id="sys_public",
        max_source_share=1.0,
    )
    run_split(data, split_config)
    licenses = json.loads(
        (data / "manifests/splits/sys_public/licenses.json").read_text(encoding="utf-8")
    )
    assert [s["source_id"] for s in licenses["sources"]] == ["public_vpt_contractor"]

    assert update_documents(repo_root=repo, data_root=data) == 0
    third = (repo / "docs/THIRD_PARTY_DATA.md").read_text(encoding="utf-8")
    assert "public_vpt_contractor" in third
    assert "Active sources" in third
    assert licenses_main(
        ["--repo-root", str(repo), "--data-root", str(data), "--check"]
    ) == 0
