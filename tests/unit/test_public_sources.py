"""Unit tests for public dataset licence capture and generated docs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from game_frame_classifier.public_sources import (
    PublicSourcesError,
    build_ledger_table,
    build_third_party,
    clips_on_disk,
    fetch_license,
    load_sources,
    main,
    record_download,
    replace_ledger_table,
    source_status,
    update_documents,
)


def _entry(**overrides: object) -> dict:
    base = {
        "source_id": "public_vpt_contractor",
        "games": ["Minecraft"],
        "dataset_name": "OpenAI VPT contractor demos",
        "official_url": "https://example.com/vpt",
        "license_spdx": "MIT",
        "license_url": "https://example.com/MIT.txt",
        "commercial_ok": "review",
        "attribution_text": "Made-up VPT attribution (MIT).",
        "approved": True,
        "notes": "",
    }
    base.update(overrides)
    return base


def _write_config(path: Path, entries: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sources": entries}, indent=2) + "\n", encoding="utf-8")
    return path


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _opener(payload: bytes | dict[str, bytes]):
    def open_url(url: str, *args: object, **kwargs: object) -> _FakeResponse:
        if isinstance(payload, dict):
            if url not in payload:
                raise OSError(f"unexpected url {url}")
            return _FakeResponse(payload[url])
        return _FakeResponse(payload)

    return open_url


def test_load_sources_requires_keys(tmp_path: Path) -> None:
    path = tmp_path / "public_sources.json"
    path.write_text(json.dumps({"sources": [{"source_id": "x"}]}), encoding="utf-8")
    with pytest.raises(PublicSourcesError, match="missing keys"):
        load_sources(path)


def test_fetch_refuses_unapproved_and_unknown(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "config" / "public_sources.json",
        [_entry(approved=False)],
    )
    sources = load_sources(config)
    with pytest.raises(PublicSourcesError, match="not approved") as excinfo:
        fetch_license(
            "public_vpt_contractor",
            repo_root=tmp_path,
            sources=sources,
            opener=_opener(b"MIT text"),
        )
    assert excinfo.value.exit_code == 2
    assert not (tmp_path / "docs" / "licenses").exists()

    with pytest.raises(PublicSourcesError, match="unknown") as excinfo:
        fetch_license(
            "public_missing",
            repo_root=tmp_path,
            sources=sources,
            opener=_opener(b"MIT text"),
        )
    assert excinfo.value.exit_code == 2


def test_fetch_saves_licence_with_hash(tmp_path: Path) -> None:
    _write_config(tmp_path / "config" / "public_sources.json", [_entry()])
    text = b"Permission is hereby granted (made-up MIT).\n"
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    path = fetch_license(
        "public_vpt_contractor",
        repo_root=tmp_path,
        opener=_opener(text),
        now=now,
    )
    assert path.read_bytes() == text
    provenance = json.loads(
        (tmp_path / "docs/licenses/public_vpt_contractor/provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert provenance["license_sha256"] == __import__("hashlib").sha256(text).hexdigest()
    assert provenance["retrieved_utc"] == "2026-03-15T12:00:00Z"
    assert provenance["files"] == []


def test_fetch_empty_or_failed_stops(tmp_path: Path) -> None:
    _write_config(tmp_path / "config" / "public_sources.json", [_entry()])
    with pytest.raises(PublicSourcesError, match="empty") as empty:
        fetch_license(
            "public_vpt_contractor",
            repo_root=tmp_path,
            opener=_opener(b"   \n"),
        )
    assert empty.value.exit_code == 1

    def boom(url: str, *args: object, **kwargs: object):
        raise OSError("network down")

    with pytest.raises(PublicSourcesError, match="failed") as failed:
        fetch_license(
            "public_vpt_contractor",
            repo_root=tmp_path,
            opener=boom,
        )
    assert failed.value.exit_code == 1
    assert not (tmp_path / "docs/licenses/public_vpt_contractor/LICENSE.txt").exists()


def test_changed_licence_keeps_old_copy(tmp_path: Path) -> None:
    _write_config(tmp_path / "config" / "public_sources.json", [_entry()])
    fetch_license(
        "public_vpt_contractor",
        repo_root=tmp_path,
        opener=_opener(b"old licence\n"),
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    fetch_license(
        "public_vpt_contractor",
        repo_root=tmp_path,
        opener=_opener(b"new licence\n"),
        now=datetime(2026, 2, 2, tzinfo=timezone.utc),
    )
    dest = tmp_path / "docs/licenses/public_vpt_contractor"
    assert (dest / "LICENSE.txt").read_bytes() == b"new licence\n"
    assert (dest / "LICENSE.2026-02-02.txt").read_bytes() == b"old licence\n"


def test_record_download_appends_file(tmp_path: Path) -> None:
    _write_config(tmp_path / "config" / "public_sources.json", [_entry()])
    fetch_license(
        "public_vpt_contractor",
        repo_root=tmp_path,
        opener=_opener(b"licence\n"),
    )
    archive = tmp_path / "cache" / "demo.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"archive-bytes")
    record_download("public_vpt_contractor", archive, repo_root=tmp_path)
    provenance = json.loads(
        (tmp_path / "docs/licenses/public_vpt_contractor/provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert provenance["files"] == [
        {
            "name": "demo.zip",
            "bytes": len(b"archive-bytes"),
            "sha256": __import__("hashlib").sha256(b"archive-bytes").hexdigest(),
        }
    ]


def test_status_planned_downloaded_active(tmp_path: Path) -> None:
    data = tmp_path / "data"
    repo = tmp_path
    assert source_status("public_vpt_contractor", data, repo) == "planned"
    lic = repo / "docs/licenses/public_vpt_contractor"
    lic.mkdir(parents=True)
    (lic / "LICENSE.txt").write_text("x", encoding="utf-8")
    assert source_status("public_vpt_contractor", data, repo) == "downloaded"
    clip = data / "frame_sources" / "Minecraft" / "public_vpt_contractor" / "c000000000001"
    clip.mkdir(parents=True)
    assert source_status("public_vpt_contractor", data, repo) == "active"


def test_clip_dirs_finds_other_source_clips(tmp_path: Path) -> None:
    data = tmp_path / "data"
    other_clip = (
        data / "frame_sources" / "_other" / "desktop_misc" / "public_test_stills" / "cother0000001"
    )
    other_clip.mkdir(parents=True)
    skipped = data / "frame_sources" / "_other" / "_hidden" / "public_test_stills" / "cskip"
    skipped.mkdir(parents=True)
    game_clip = data / "frame_sources" / "Minecraft" / "public_test_stills" / "cgame00000001"
    game_clip.mkdir(parents=True)
    counts = clips_on_disk(data, "public_test_stills")
    assert counts == {"Minecraft": 1, "Other": 1}
    assert source_status("public_test_stills", data, tmp_path) == "active"


def test_third_party_zero_one_two_active(tmp_path: Path) -> None:
    entries = [
        _entry(),
        _entry(
            source_id="public_gamed",
            games=["Valorant", "CS2"],
            dataset_name="Gamed",
            official_url="https://example.com/gamed",
            license_spdx="CC-BY-4.0",
            license_url="https://example.com/CC-BY-4.0.txt",
            attribution_text="Made-up Gamed attribution.",
        ),
    ]
    sources = {e["source_id"]: e for e in entries}
    data = tmp_path / "data"
    zero = build_third_party(sources, data_root=data, repo_root=tmp_path)
    assert "No public datasets are active" in zero

    (data / "frame_sources/Minecraft/public_vpt_contractor/c1").mkdir(parents=True)
    (tmp_path / "docs/licenses/public_vpt_contractor").mkdir(parents=True)
    (
        tmp_path / "docs/licenses/public_vpt_contractor/provenance.json"
    ).write_text(
        json.dumps({"retrieved_utc": "2026-03-01T00:00:00Z"}),
        encoding="utf-8",
    )
    one = build_third_party(sources, data_root=data, repo_root=tmp_path)
    assert "OpenAI VPT contractor demos" in one
    assert "`public_vpt_contractor`" in one
    assert "public_gamed" not in one.split("## Downloaded")[0]

    (data / "frame_sources/Valorant/public_gamed/c2").mkdir(parents=True)
    two = build_third_party(sources, data_root=data, repo_root=tmp_path)
    assert "public_vpt_contractor" in two
    assert "public_gamed" in two
    assert two.index("### Gamed") != two.index("### OpenAI VPT")


def test_ledger_markers_and_check(tmp_path: Path) -> None:
    entries = [_entry(approved=False)]
    _write_config(tmp_path / "config" / "public_sources.json", entries)
    ledger = tmp_path / "docs/research/public-sources-ledger.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "# Ledger\n\nintro\n\n<!-- ledger:start -->\nold\n<!-- ledger:end -->\n\nfooter\n",
        encoding="utf-8",
    )
    data = tmp_path / "data"
    data.mkdir()

    assert update_documents(repo_root=tmp_path, data_root=data, check=False) == 0
    text = ledger.read_text(encoding="utf-8")
    assert "intro" in text and "footer" in text
    assert "public_vpt_contractor" in text
    assert "old" not in text.split("<!-- ledger:start -->")[1].split("<!-- ledger:end -->")[0]
    third = (tmp_path / "docs/THIRD_PARTY_DATA.md").read_text(encoding="utf-8")
    assert "No public datasets are active" in third

    assert update_documents(repo_root=tmp_path, data_root=data, check=True) == 0
    (tmp_path / "docs/THIRD_PARTY_DATA.md").write_text("stale\n", encoding="utf-8")
    assert update_documents(repo_root=tmp_path, data_root=data, check=True) == 1

    # CLI --check path
    assert main(["--repo-root", str(tmp_path), "--data-root", str(data), "--check"]) == 1


def test_replace_ledger_requires_markers() -> None:
    with pytest.raises(PublicSourcesError, match="markers"):
        replace_ledger_table("# no markers\n", "| a |\n")


def test_build_ledger_table_columns(tmp_path: Path) -> None:
    sources = {"public_vpt_contractor": _entry(approved=False)}
    table = build_ledger_table(sources, data_root=tmp_path / "data", repo_root=tmp_path)
    header = table.splitlines()[0]
    assert header.startswith("| source_id | status |")
    assert "date_accessed" not in header
    assert "approved | retrieved |" in header.replace(" ", " ")
