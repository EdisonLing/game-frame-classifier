"""Public dataset licence capture, status, and generated attribution docs.

Spec: ``docs/roadmap/tools/public-licenses.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from game_frame_classifier.sourcing.manifests import write_json

REQUIRED_KEYS = (
    "source_id",
    "games",
    "dataset_name",
    "official_url",
    "license_spdx",
    "license_url",
    "commercial_ok",
    "attribution_text",
    "approved",
    "notes",
)

LEDGER_START = "<!-- ledger:start -->"
LEDGER_END = "<!-- ledger:end -->"

Opener = Callable[..., Any]


class PublicSourcesError(RuntimeError):
    """Expected config or licence error with a command exit code."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _utc_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_sources(path: Path | str) -> dict[str, dict[str, Any]]:
    """Load ``config/public_sources.json`` into ``source_id → entry``."""
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "sources" not in raw:
        raise PublicSourcesError(f"{path}: expected object with 'sources' list", 2)
    sources = raw["sources"]
    if not isinstance(sources, list):
        raise PublicSourcesError(f"{path}: 'sources' must be a list", 2)
    out: dict[str, dict[str, Any]] = {}
    for i, entry in enumerate(sources):
        if not isinstance(entry, dict):
            raise PublicSourcesError(f"{path}: sources[{i}] must be an object", 2)
        missing = [k for k in REQUIRED_KEYS if k not in entry]
        if missing:
            raise PublicSourcesError(
                f"{path}: sources[{i}] missing keys: {', '.join(missing)}", 2
            )
        source_id = entry["source_id"]
        if not isinstance(source_id, str) or not source_id:
            raise PublicSourcesError(f"{path}: sources[{i}].source_id must be a non-empty string", 2)
        if source_id in out:
            raise PublicSourcesError(f"{path}: duplicate source_id {source_id!r}", 2)
        if not isinstance(entry["approved"], bool):
            raise PublicSourcesError(f"{path}: {source_id}: approved must be a boolean", 2)
        if not isinstance(entry["games"], list) or not all(isinstance(g, str) for g in entry["games"]):
            raise PublicSourcesError(f"{path}: {source_id}: games must be a list of strings", 2)
        out[source_id] = dict(entry)
    return out


def resolve_sources_path(config_path: Path | None = None) -> Path:
    """Prefer a public_sources.json beside a split config; else repo ``config/``."""
    if config_path is not None:
        beside = Path(config_path).resolve().parent / "public_sources.json"
        if beside.is_file():
            return beside
    default = Path("config/public_sources.json")
    if default.is_file():
        return default
    raise PublicSourcesError("config/public_sources.json not found", 2)


def license_dir(repo_root: Path, source_id: str) -> Path:
    return Path(repo_root) / "docs" / "licenses" / source_id


def fetch_license(
    source_id: str,
    *,
    repo_root: Path,
    sources: dict[str, dict[str, Any]] | None = None,
    sources_path: Path | None = None,
    opener: Opener = urllib.request.urlopen,
    now: datetime | None = None,
) -> Path:
    """Download a source's licence text and write provenance (Behaviour 1)."""
    repo_root = Path(repo_root)
    if sources is None:
        path = sources_path or (repo_root / "config" / "public_sources.json")
        sources = load_sources(path)
    entry = sources.get(source_id)
    if entry is None:
        raise PublicSourcesError(f"unknown public source: {source_id}", 2)
    if not entry["approved"]:
        raise PublicSourcesError(
            f"public source {source_id} is not approved; set approved=true after reading the licence",
            2,
        )

    license_url = str(entry["license_url"])
    try:
        with opener(license_url) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise PublicSourcesError(f"failed to download licence for {source_id}: {exc}", 1) from exc
    if not data or not data.strip():
        raise PublicSourcesError(f"licence for {source_id} is empty", 1)

    retrieved = _utc_now(now)
    retrieved_utc = retrieved.strftime("%Y-%m-%dT%H:%M:%SZ")
    retrieved_date = retrieved.strftime("%Y-%m-%d")
    digest = _sha256_bytes(data)

    dest_dir = license_dir(repo_root, source_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    license_path = dest_dir / "LICENSE.txt"
    if license_path.is_file():
        old_digest = _sha256_file(license_path)
        if old_digest != digest:
            backup = dest_dir / f"LICENSE.{retrieved_date}.txt"
            # Never overwrite an earlier backup of the same day; keep a unique name.
            if backup.exists():
                n = 2
                while True:
                    candidate = dest_dir / f"LICENSE.{retrieved_date}.{n}.txt"
                    if not candidate.exists():
                        backup = candidate
                        break
                    n += 1
            license_path.replace(backup)
            print(f"licence changed for {source_id}; kept previous as {backup.name}", file=sys.stderr)

    license_path.write_bytes(data)
    provenance_path = dest_dir / "provenance.json"
    files: list[dict[str, Any]] = []
    if provenance_path.is_file():
        try:
            prev = json.loads(provenance_path.read_text(encoding="utf-8"))
            if isinstance(prev.get("files"), list):
                files = list(prev["files"])
        except (json.JSONDecodeError, OSError):
            files = []
    provenance = {
        "source_id": source_id,
        "dataset_url": entry["official_url"],
        "dataset_revision": "",
        "license_spdx": entry["license_spdx"],
        "license_url": license_url,
        "license_sha256": digest,
        "retrieved_utc": retrieved_utc,
        "files": files,
    }
    write_json(provenance, provenance_path)
    return license_path


def record_download(source_id: str, file_path: Path, *, repo_root: Path) -> None:
    """Append an archive's name, size and sha256 to provenance.json (Behaviour 2)."""
    repo_root = Path(repo_root)
    file_path = Path(file_path)
    provenance_path = license_dir(repo_root, source_id) / "provenance.json"
    if not provenance_path.is_file():
        raise PublicSourcesError(
            f"provenance missing for {source_id}; call fetch_license before record_download",
            1,
        )
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    files = list(provenance.get("files") or [])
    entry = {
        "name": file_path.name,
        "bytes": file_path.stat().st_size,
        "sha256": _sha256_file(file_path),
    }
    # Replace an earlier record of the same name so re-downloads stay a single row.
    files = [f for f in files if f.get("name") != entry["name"]]
    files.append(entry)
    provenance["files"] = files
    write_json(provenance, provenance_path)


def _clip_dirs(data_root: Path, source_id: str) -> list[Path]:
    """Clip folders under ``frame_sources/<Game>/<source_id>/``."""
    fs = Path(data_root) / "frame_sources"
    if not fs.is_dir():
        return []
    found: list[Path] = []
    for game_dir in sorted(p for p in fs.iterdir() if p.is_dir() and not p.name.startswith("_")):
        source_dir = game_dir / source_id
        if not source_dir.is_dir():
            continue
        for clip in sorted(source_dir.iterdir()):
            if clip.is_dir() and not clip.name.startswith("_"):
                found.append(clip)
    return found


def clips_on_disk(data_root: Path, source_id: str) -> dict[str, int]:
    """Map game → number of clip folders for a source."""
    counts: dict[str, int] = defaultdict(int)
    for clip in _clip_dirs(data_root, source_id):
        # frame_sources/<Game>/<source_id>/<clip>
        counts[clip.parent.parent.name] += 1
    return dict(sorted(counts.items()))


def source_status(source_id: str, data_root: Path, repo_root: Path) -> str:
    """Compute planned / downloaded / active (Behaviour 3)."""
    if _clip_dirs(data_root, source_id):
        return "active"
    if license_dir(repo_root, source_id).is_dir():
        return "downloaded"
    return "planned"


def _retrieved_date(repo_root: Path, source_id: str) -> str:
    path = license_dir(repo_root, source_id) / "provenance.json"
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    retrieved = str(payload.get("retrieved_utc") or "")
    if len(retrieved) >= 10:
        return retrieved[:10]
    return retrieved


def build_third_party(
    sources: dict[str, dict[str, Any]],
    *,
    data_root: Path,
    repo_root: Path,
) -> str:
    """Render ``docs/THIRD_PARTY_DATA.md`` (Behaviour 4)."""
    active: list[str] = []
    downloaded: list[str] = []
    for source_id in sources:
        status = source_status(source_id, data_root, repo_root)
        if status == "active":
            active.append(source_id)
        elif status == "downloaded":
            downloaded.append(source_id)

    lines = [
        "# Third-party public datasets",
        "",
        "Generated by `gfc-licenses`. Do not edit by hand; edit"
        " `config/public_sources.json` and re-run.",
        "",
    ]
    if not active:
        lines.extend(
            [
                "No public datasets are active (no clip folders under"
                " `data/frame_sources/<Game>/<source_id>/`).",
                "",
            ]
        )
    else:
        lines.extend(["## Active sources", ""])
        for source_id in active:
            entry = sources[source_id]
            frames = clips_on_disk(data_root, source_id)
            frames_txt = ", ".join(f"{game}: {n}" for game, n in frames.items()) or "(none)"
            retrieved = _retrieved_date(repo_root, source_id) or "(unknown)"
            lines.extend(
                [
                    f"### {entry['dataset_name']} (`{source_id}`)",
                    "",
                    f"- Dataset: [{entry['dataset_name']}]({entry['official_url']})",
                    f"- Licence: [{entry['license_spdx']}](licenses/{source_id}/LICENSE.txt)",
                    f"- Attribution: {entry['attribution_text']}",
                    f"- Commercial use: {entry['commercial_ok']}",
                    f"- Retrieved: {retrieved}",
                    f"- Clips on disk: {frames_txt}",
                    "",
                ]
            )

    lines.extend(["## Downloaded but unused", ""])
    if not downloaded:
        lines.append("None.")
        lines.append("")
    else:
        for source_id in downloaded:
            entry = sources[source_id]
            lines.append(
                f"- `{source_id}` — {entry['dataset_name']} ({entry['license_spdx']})"
            )
        lines.append("")
    return "\n".join(lines)


def build_ledger_table(
    sources: dict[str, dict[str, Any]],
    *,
    data_root: Path,
    repo_root: Path,
) -> str:
    """Markdown table body (including header) for the ledger markers."""
    header = (
        "| source_id | status | games | dataset_name | official_url | license_spdx |"
        " commercial_ok | attribution_text | approved | retrieved |"
    )
    sep = "|---|---|---|---|---|---|---|---|---|---|"
    rows = [header, sep]
    for source_id, entry in sources.items():
        status = source_status(source_id, data_root, repo_root)
        games = ", ".join(entry["games"])
        approved = "true" if entry["approved"] else "false"
        retrieved = _retrieved_date(repo_root, source_id)
        rows.append(
            "| "
            + " | ".join(
                [
                    f"`{source_id}`",
                    status,
                    games,
                    entry["dataset_name"],
                    entry["official_url"],
                    entry["license_spdx"],
                    str(entry["commercial_ok"]),
                    entry["attribution_text"],
                    approved,
                    retrieved,
                ]
            )
            + " |"
        )
    return "\n".join(rows)


def replace_ledger_table(ledger_text: str, table: str) -> str:
    """Replace content between ledger markers; raise if markers are missing."""
    start = ledger_text.find(LEDGER_START)
    end = ledger_text.find(LEDGER_END)
    if start < 0 or end < 0 or end < start:
        raise PublicSourcesError(
            "public-sources-ledger.md missing <!-- ledger:start --> / <!-- ledger:end --> markers",
            1,
        )
    before = ledger_text[: start + len(LEDGER_START)]
    after = ledger_text[end:]
    return before + "\n" + table + "\n" + after


def write_split_licenses(
    output: Path,
    assigned_slots: list[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Write ``licenses.json`` / ``licenses.md`` for a split folder (Behaviour 5)."""
    # source_id → split → game → count
    counts: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    public_ids: set[str] = set()
    for slot in assigned_slots:
        source = str(slot.get("source") or "")
        kind = str(slot.get("source_kind") or "")
        if kind != "public" and not source.startswith("public_"):
            continue
        public_ids.add(source)
        split = str(slot.get("split") or "")
        game = str(slot.get("game") or "")
        if split and game:
            counts[source][split][game] += 1

    missing = sorted(sid for sid in public_ids if sid not in sources)
    if missing:
        raise PublicSourcesError(
            "public source(s) in split missing from config/public_sources.json: "
            + ", ".join(missing),
            2,
        )

    entries: list[dict[str, Any]] = []
    for source_id in sorted(public_ids):
        entry = sources[source_id]
        slot_counts = {
            split: dict(sorted(games.items()))
            for split, games in sorted(counts[source_id].items())
        }
        entries.append(
            {
                "source_id": source_id,
                "dataset_name": entry["dataset_name"],
                "official_url": entry["official_url"],
                "license_spdx": entry["license_spdx"],
                "license_url": entry["license_url"],
                "commercial_ok": entry["commercial_ok"],
                "attribution_text": entry["attribution_text"],
                "slots": slot_counts,
            }
        )

    payload = {"sources": entries}
    write_json(payload, output / "licenses.json")
    md_lines = ["# Public sources used by this split", ""]
    if not entries:
        md_lines.append("None.")
        md_lines.append("")
    else:
        for item in entries:
            md_lines.append(f"## {item['dataset_name']} (`{item['source_id']}`)")
            md_lines.append("")
            md_lines.append(f"- Licence: {item['license_spdx']}")
            md_lines.append(f"- Attribution: {item['attribution_text']}")
            md_lines.append(f"- Commercial use: {item['commercial_ok']}")
            md_lines.append("- Slots:")
            for split, games in item["slots"].items():
                for game, n in games.items():
                    md_lines.append(f"  - {split} / {game}: {n}")
            md_lines.append("")
    (output / "licenses.md").write_text("\n".join(md_lines), encoding="utf-8")
    return payload


def copy_split_licenses(split_dir: Path, run_dir: Path) -> bool:
    """Copy the split's ``licenses.json`` into the run folder when present."""
    src = Path(split_dir) / "licenses.json"
    if not src.is_file():
        return False
    dest = Path(run_dir) / "licenses.json"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def update_documents(
    *,
    repo_root: Path,
    data_root: Path,
    sources_path: Path | None = None,
    check: bool = False,
) -> int:
    """Rebuild or check ``THIRD_PARTY_DATA.md`` and the ledger table."""
    repo_root = Path(repo_root)
    data_root = Path(data_root)
    sources_path = sources_path or (repo_root / "config" / "public_sources.json")
    sources = load_sources(sources_path)

    third_party_path = repo_root / "docs" / "THIRD_PARTY_DATA.md"
    ledger_path = repo_root / "docs" / "research" / "public-sources-ledger.md"
    new_third = build_third_party(sources, data_root=data_root, repo_root=repo_root)
    table = build_ledger_table(sources, data_root=data_root, repo_root=repo_root)
    if not ledger_path.is_file():
        raise PublicSourcesError(f"missing {ledger_path}", 1)
    current_ledger = ledger_path.read_text(encoding="utf-8")
    new_ledger = replace_ledger_table(current_ledger, table)

    if check:
        stale = False
        if not third_party_path.is_file() or third_party_path.read_text(encoding="utf-8") != new_third:
            print(f"stale: {third_party_path}", file=sys.stderr)
            stale = True
        if current_ledger != new_ledger:
            print(f"stale: {ledger_path}", file=sys.stderr)
            stale = True
        return 1 if stale else 0

    third_party_path.parent.mkdir(parents=True, exist_ok=True)
    third_party_path.write_text(new_third, encoding="utf-8")
    ledger_path.write_text(new_ledger, encoding="utf-8")
    print(f"wrote {third_party_path.relative_to(repo_root)}")
    print(f"updated ledger table in {ledger_path.relative_to(repo_root)}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gfc-licenses",
        description="Rebuild public-dataset licence and attribution documents.",
    )
    parser.add_argument("--check", action="store_true", help="exit 1 if generated files are stale")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="repository root (default: current working directory)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    repo_root = Path(args.repo_root) if args.repo_root is not None else Path.cwd()
    try:
        return update_documents(
            repo_root=repo_root,
            data_root=args.data_root,
            check=args.check,
        )
    except PublicSourcesError as exc:
        print(f"gfc-licenses: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
