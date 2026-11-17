"""Streaming hashes, quick ids and the JPEG size reader."""

import hashlib

import pytest
from PIL import Image

from game_frame_classifier.sourcing.hashing import jpeg_size, quick_id, sha256_file


def test_sha256_matches_hashlib(tmp_path):
    data = bytes(range(256)) * 9000
    p = tmp_path / "a.bin"
    p.write_bytes(data)
    assert sha256_file(p) == hashlib.sha256(data).hexdigest()


def test_quick_id_small_files(tmp_path):
    a, b, c = tmp_path / "a.bin", tmp_path / "b.bin", tmp_path / "c.bin"
    a.write_bytes(b"hello")
    b.write_bytes(b"hello")
    c.write_bytes(b"hellp")
    assert quick_id(a) == quick_id(b) != quick_id(c)
    assert len(quick_id(a)) == 16


def test_quick_id_reads_only_the_ends(tmp_path):
    size = 3 << 20
    base = bytearray(size)
    middle = bytearray(base)
    middle[size // 2] = 1
    end = bytearray(base)
    end[-1] = 1
    paths = []
    for name, data in (("a", base), ("b", middle), ("c", end)):
        p = tmp_path / f"{name}.bin"
        p.write_bytes(bytes(data))
        paths.append(p)
    assert quick_id(paths[0]) == quick_id(paths[1])
    assert quick_id(paths[0]) != quick_id(paths[2])


@pytest.mark.parametrize("progressive", [False, True])
def test_jpeg_size(tmp_path, progressive):
    p = tmp_path / "x.jpg"
    Image.new("RGB", (37, 21), (10, 20, 30)).save(p, "JPEG", progressive=progressive)
    assert jpeg_size(p) == (37, 21)


def test_jpeg_size_rejects_non_jpeg(tmp_path):
    p = tmp_path / "x.jpg"
    p.write_bytes(b"\x89PNG....")
    with pytest.raises(ValueError):
        jpeg_size(p)
