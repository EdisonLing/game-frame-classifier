"""Pack zip writer and validator (friend-pack spec §6.1, §11)."""

import json
import os
import zipfile

import pytest

from game_frame_classifier.sourcing.packzip import PackZipError, validate_pack_zip, write_pack_zip

ROOT_NAME = "gfc_pack_0123abcd"


def make_pack(tmp_path):
    pack = tmp_path / ROOT_NAME
    files = {
        "frames/c000000000000/full/c000000000000_full_b000000.jpg": b"\xff\xd8" + b"x" * 100,
        "clips.csv": b"clip_key\n",
        "run_log.txt": b"ok\n",
    }
    for rel, data in files.items():
        path = pack / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {
        "schema": "gfc.pack/1",
        "output": {"file_count": len(files), "uncompressed_bytes": sum(len(d) for d in files.values())},
    }
    (pack / "pack_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return pack


def entries(extra=(), count_delta=0, declared=None):
    body = [(f"{ROOT_NAME}/frames/a.jpg", b"\xff\xd8" + b"x" * 50), (f"{ROOT_NAME}/clips.csv", b"clip_key\n"), *extra]
    total = sum(len(d) for _, d in body) if declared is None else declared
    manifest = {"schema": "gfc.pack/1", "output": {"file_count": len(body) + count_delta, "uncompressed_bytes": total}}
    return [(f"{ROOT_NAME}/pack_manifest.json", json.dumps(manifest).encode("utf-8")), *body]


def raw_zip(path, items, deflate=(), attrs=None):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in items:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED if name in deflate else zipfile.ZIP_STORED
            if attrs and name in attrs:
                info.external_attr = attrs[name]
            zf.writestr(info, data)
    return path


def test_write_then_validate(tmp_path):
    out = tmp_path / "out.zip"
    write_pack_zip(make_pack(tmp_path), out)
    assert out.is_file() and not (tmp_path / "out.zip.part").exists()
    with zipfile.ZipFile(out) as zf:
        assert all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())
        assert all(i.filename.startswith(f"{ROOT_NAME}/") for i in zf.infolist())
    (manifest,) = validate_pack_zip(out, tmp_path / "scratch")
    assert manifest["output"]["file_count"] == 3


def test_valid_raw_zip(tmp_path):
    assert len(validate_pack_zip(raw_zip(tmp_path / "z.zip", entries()), tmp_path / "s")) == 1


@pytest.mark.parametrize(
    "name",
    [f"{ROOT_NAME}/../evil.jpg", "/abs.jpg", "C:/x.jpg", f"{ROOT_NAME}/caf\u00e9.jpg", f"{ROOT_NAME}//double.jpg"],
)
def test_unsafe_names_rejected(tmp_path, name):
    z = raw_zip(tmp_path / "z.zip", entries(extra=[(name, b"\xff\xd8")]))
    with pytest.raises(PackZipError):
        validate_pack_zip(z, tmp_path / "s")


def test_symlink_rejected(tmp_path):
    name = f"{ROOT_NAME}/link.jpg"
    z = raw_zip(tmp_path / "z.zip", entries(extra=[(name, b"target")]), attrs={name: 0o120777 << 16})
    with pytest.raises(PackZipError, match="symlink"):
        validate_pack_zip(z, tmp_path / "s")


def test_disallowed_extension(tmp_path):
    z = raw_zip(tmp_path / "z.zip", entries(extra=[(f"{ROOT_NAME}/run.exe", b"MZ")]))
    with pytest.raises(PackZipError, match="not allowed"):
        validate_pack_zip(z, tmp_path / "s")


def test_deflate_bomb_rejected(tmp_path):
    name = f"{ROOT_NAME}/frames/big.jpg"
    z = raw_zip(tmp_path / "z.zip", entries(extra=[(name, b"\0" * (1 << 20))]), deflate={name})
    with pytest.raises(PackZipError, match="ratio"):
        validate_pack_zip(z, tmp_path / "s")


def test_count_mismatch(tmp_path):
    z = raw_zip(tmp_path / "z.zip", entries(count_delta=1))
    with pytest.raises(PackZipError, match="file_count"):
        validate_pack_zip(z, tmp_path / "s")


def test_larger_than_declared(tmp_path):
    big = (f"{ROOT_NAME}/frames/big.jpg", os.urandom(17 << 20))
    z = raw_zip(tmp_path / "z.zip", entries(extra=[big], declared=10))
    with pytest.raises(PackZipError, match="larger"):
        validate_pack_zip(z, tmp_path / "s")


def test_wrong_root(tmp_path):
    items = [(n.replace(ROOT_NAME, "pack"), d) for n, d in entries()]
    with pytest.raises(PackZipError, match="root"):
        validate_pack_zip(raw_zip(tmp_path / "z.zip", items), tmp_path / "s")


def test_two_roots(tmp_path):
    z = raw_zip(tmp_path / "z.zip", entries(extra=[("gfc_pack_ffffffff/x.jpg", b"\xff\xd8")]))
    with pytest.raises(PackZipError, match="one root"):
        validate_pack_zip(z, tmp_path / "s")


def test_zip_of_packs(tmp_path):
    a = raw_zip(tmp_path / "a.zip", entries())
    b = raw_zip(tmp_path / "b.zip", entries())
    outer = raw_zip(tmp_path / "outer.zip", [("a.zip", a.read_bytes()), ("b.zip", b.read_bytes())])
    assert len(validate_pack_zip(outer, tmp_path / "scratch")) == 2
    assert list((tmp_path / "scratch").iterdir()) == []


def test_two_nesting_levels_rejected(tmp_path):
    inner = raw_zip(tmp_path / "a.zip", entries())
    middle = raw_zip(tmp_path / "m.zip", [("a.zip", inner.read_bytes())])
    outer = raw_zip(tmp_path / "o.zip", [("m.zip", middle.read_bytes())])
    with pytest.raises(PackZipError, match="one level"):
        validate_pack_zip(outer, tmp_path / "s")


def test_not_a_zip(tmp_path):
    p = tmp_path / "x.zip"
    p.write_bytes(b"nope")
    with pytest.raises(PackZipError):
        validate_pack_zip(p, tmp_path / "s")
