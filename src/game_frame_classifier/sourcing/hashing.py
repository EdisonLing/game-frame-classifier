"""Streaming hashes and a JPEG size reader (stdlib only)."""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

CHUNK = 1 << 20
SOF_MARKERS = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def quick_id(path: Path) -> str:
    """sha256(size, first 1 MiB, last 1 MiB)[:16]: cheap identity for big libraries."""
    size = os.path.getsize(path)
    digest = hashlib.sha256(f"{size}\n".encode("ascii"))
    with open(path, "rb") as f:
        digest.update(f.read(CHUNK))
        if size > CHUNK:
            f.seek(max(CHUNK, size - CHUNK))
            digest.update(f.read(CHUNK))
    return digest.hexdigest()[:16]


def jpeg_size(path: Path) -> tuple[int, int]:
    """(width, height) from the JPEG frame header."""
    with open(path, "rb") as f:
        if f.read(2) != b"\xff\xd8":
            raise ValueError(f"not a JPEG: {Path(path).name}")
        while True:
            byte = f.read(1)
            while byte and byte != b"\xff":
                byte = f.read(1)
            while byte == b"\xff":
                byte = f.read(1)
            if not byte:
                break
            marker = byte[0]
            if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
                continue
            if marker == 0xD9:
                break
            length_bytes = f.read(2)
            if len(length_bytes) < 2:
                break
            (length,) = struct.unpack(">H", length_bytes)
            if marker in SOF_MARKERS:
                data = f.read(5)
                if len(data) < 5:
                    break
                _, height, width = struct.unpack(">BHH", data)
                return width, height
            f.seek(length - 2, 1)
    raise ValueError(f"no JPEG frame header: {Path(path).name}")
