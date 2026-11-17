"""Pack zip writer and validator (friend-pack spec §6.1, §11)."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from . import SCHEMA_PACK

ALLOWED_EXTENSIONS = frozenset({".jpg", ".json", ".csv", ".txt"})
TEXT_EXTENSIONS = frozenset({".json", ".csv", ".txt"})
MAX_ENTRY_BYTES = 64 << 20
MAX_TOTAL_BYTES = 64 << 30
MAX_ENTRIES = 1_000_000
ROOT_PREFIX = "gfc_pack_"
HEX = frozenset("0123456789abcdef")


class PackZipError(ValueError):
    """The zip is not a valid, safe friend pack."""


def write_pack_zip(pack_dir: Path, zip_path: Path) -> None:
    """Stored zip with one root folder; written as .part, verified, then renamed."""
    root = pack_dir.name
    files = sorted(p for p in pack_dir.rglob("*") if p.is_file())
    part = zip_path.with_name(zip_path.name + ".part")
    try:
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for path in files:
                arcname = f"{root}/{path.relative_to(pack_dir).as_posix()}"
                if not arcname.isascii():
                    raise PackZipError(f"non-ASCII entry name: {arcname}")
                zf.write(path, arcname)
        with zipfile.ZipFile(part) as zf:
            infos = zf.infolist()
            if len(infos) != len(files):
                raise PackZipError("entry count changed while writing")
            for info, path in zip(infos, files):
                if info.file_size != path.stat().st_size:
                    raise PackZipError(f"size mismatch for {info.filename}")
            bad = zf.testzip()
            if bad is not None:
                raise PackZipError(f"CRC check failed for {bad}")
        part.replace(zip_path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _check_name(name: str) -> None:
    if not name or not name.isascii() or "\x00" in name:
        raise PackZipError(f"bad entry name: {name!r}")
    if "\\" in name or ":" in name or name.startswith("/"):
        raise PackZipError(f"unsafe entry path: {name}")
    if any(part in ("", ".", "..") for part in name.split("/")):
        raise PackZipError(f"unsafe entry path: {name}")


def _entries(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise PackZipError("too many entries")
    files = []
    for info in infos:
        _check_name(info.filename.rstrip("/") if info.is_dir() else info.filename)
        if info.flag_bits & 0x1:
            raise PackZipError(f"encrypted entry: {info.filename}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise PackZipError(f"symlink entry: {info.filename}")
        if not info.is_dir():
            files.append(info)
    return files


def _check_ratio(info: zipfile.ZipInfo, limit: float) -> None:
    if info.compress_type == zipfile.ZIP_STORED:
        if info.compress_size != info.file_size:
            raise PackZipError(f"stored entry size mismatch: {info.filename}")
    elif info.compress_type == zipfile.ZIP_DEFLATED:
        if info.file_size / max(1, info.compress_size) > limit:
            raise PackZipError(f"compression ratio too high: {info.filename}")
    else:
        raise PackZipError(f"unsupported compression: {info.filename}")


def _validate_pack(zf: zipfile.ZipFile, files: list[zipfile.ZipInfo]) -> dict[str, Any]:
    roots = {info.filename.split("/", 1)[0] for info in files}
    if len(roots) != 1:
        raise PackZipError("a pack must have exactly one root folder")
    root = roots.pop()
    suffix = root[len(ROOT_PREFIX):]
    if not root.startswith(ROOT_PREFIX) or len(suffix) != 8 or not set(suffix) <= HEX:
        raise PackZipError(f"unexpected root folder: {root}")
    manifest_name = f"{root}/pack_manifest.json"
    names = {info.filename for info in files}
    if manifest_name not in names:
        raise PackZipError("pack_manifest.json is missing")
    for info in files:
        if "/" not in info.filename:
            raise PackZipError(f"file outside the root folder: {info.filename}")
        ext = PurePosixPath(info.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise PackZipError(f"file type not allowed: {info.filename}")
        if info.file_size > MAX_ENTRY_BYTES:
            raise PackZipError(f"entry too large: {info.filename}")
        _check_ratio(info, 20.0 if ext in TEXT_EXTENSIONS else 2.0)
    try:
        manifest = json.loads(zf.read(manifest_name).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackZipError("pack_manifest.json is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA_PACK:
        raise PackZipError(f"unknown pack schema (expected {SCHEMA_PACK})")
    output = manifest.get("output") if isinstance(manifest.get("output"), dict) else {}
    count = output.get("file_count")
    declared = output.get("uncompressed_bytes")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (count, declared)):
        raise PackZipError("manifest output.file_count / uncompressed_bytes missing")
    if len(files) != count + 1:
        raise PackZipError(f"entry count {len(files)} does not match file_count {count} + 1")
    total = sum(info.file_size for info in files if info.filename != manifest_name)
    if total > min(MAX_TOTAL_BYTES, int(declared * 1.05) + (16 << 20)):
        raise PackZipError("pack is larger than its manifest declares")
    return manifest


def validate_pack_zip(zip_path: Path, scratch_dir: Path) -> list[dict[str, Any]]:
    """Validate a pack zip (or a zip of pack zips, one level) and return the manifests.

    Inner zips are copied into scratch_dir one at a time and deleted after checking.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            files = _entries(zf)
            if not files:
                raise PackZipError("empty zip")
            if not all(info.filename.lower().endswith(".zip") for info in files):
                return [_validate_pack(zf, files)]
            scratch_dir.mkdir(parents=True, exist_ok=True)
            manifests = []
            for k, info in enumerate(files):
                if "/" in info.filename:
                    raise PackZipError("nested pack zips must be at the top level")
                if info.file_size > MAX_TOTAL_BYTES:
                    raise PackZipError(f"nested zip too large: {info.filename}")
                _check_ratio(info, 2.0)
                inner = scratch_dir / f"inner_{k:03d}.zip"
                try:
                    with zf.open(info) as src, open(inner, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                    with zipfile.ZipFile(inner) as izf:
                        inner_files = _entries(izf)
                        if any(i.filename.lower().endswith(".zip") for i in inner_files):
                            raise PackZipError("only one level of nested zips is allowed")
                        manifests.append(_validate_pack(izf, inner_files))
                finally:
                    inner.unlink(missing_ok=True)
            return manifests
    except zipfile.BadZipFile as exc:
        raise PackZipError(f"not a valid zip: {exc}") from exc
