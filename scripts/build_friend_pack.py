"""Fetch pinned binaries and build the friend pack (docs/roadmap/tools/friend-pack.md §12).

  python scripts/build_friend_pack.py fetch
  python scripts/build_friend_pack.py build --collector-name NAME --collector-contact CONTACT
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGING = REPO / "packaging" / "friendpack"
CACHE = REPO / "build" / "friendpack_cache"
STAGE_ROOT = REPO / "build" / "friendpack_stage"
DIST = REPO / "dist"
SRC_PKG = REPO / "src" / "game_frame_classifier"
ALLOWED_HOSTS = frozenset({
    "www.python.org",
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
})
REQUIRED_BUILDCONF = ("--enable-gpl", "--enable-libx264", "--enable-libdav1d", "--enable-libzimg")
CHUNK = 1 << 20
ENTRY_POINT = '''"""Friend pack entry point (started by START HERE.bat)."""

import sys

from game_frame_classifier.friendpack.cli import main

if __name__ == "__main__":
    sys.exit(main())
'''
SMOKE_USER = {
    "schema": "gfc.user/1",
    "contributor_id": "00000000-0000-4000-8000-000000000000",
    "handle": "smoke",
    "consent_data_use": True,
    "consent_public_examples": False,
    "consent_utc": "2026-01-01T00:00:00Z",
    "last_game": "",
    "frame_mode_override": None,
}


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_pins() -> dict:
    return json.loads((PACKAGING / "pins.json").read_text(encoding="utf-8"))


def check_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        fail(f"refusing to download from {parts.scheme}://{parts.hostname}")


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def cached_path(pin: dict) -> Path:
    return CACHE / Path(urllib.parse.urlsplit(pin["url"]).path).name


def verify(path: Path, pin: dict) -> None:
    size = path.stat().st_size
    if size != pin["size"]:
        fail(f"{path.name}: size {size} does not match pinned {pin['size']}")
    digest = sha256_of(path)
    if digest != pin["sha256"]:
        fail(f"{path.name}: sha256 {digest} does not match pinned {pin['sha256']}")


def download(pin: dict) -> Path:
    target = cached_path(pin)
    if target.is_file():
        verify(target, pin)
        print(f"{target.name}  cached  sha256 OK")
        return target
    check_url(pin["url"])
    CACHE.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    opener = urllib.request.build_opener(CheckedRedirect)
    print(f"downloading {pin['url']}")
    with opener.open(pin["url"], timeout=60) as resp, open(part, "wb") as out:
        check_url(resp.geturl())
        shutil.copyfileobj(resp, out, CHUNK)
    try:
        verify(part, pin)
    except SystemExit:
        part.unlink(missing_ok=True)
        raise
    part.replace(target)
    print(f"{target.name}  downloaded  sha256 OK")
    return target


def extract_member(zf: zipfile.ZipFile, name: str, dest: Path) -> None:
    parts = name.replace("\\", "/").split("/")
    if name.startswith(("/", "\\")) or ":" in name or ".." in parts:
        fail(f"unsafe zip member: {name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(name) as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out, CHUNK)


def stage_runtime(py_zip: Path, pin: dict, runtime: Path) -> None:
    remove = set(pin["remove"])
    with zipfile.ZipFile(py_zip) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.filename in remove:
                continue
            if "/" in info.filename:
                fail(f"unexpected folder in the Python embed zip: {info.filename}")
            extract_member(zf, info.filename, runtime / info.filename)
    if not (runtime / "python.exe").is_file():
        fail("python.exe missing from the Python embed zip")
    shutil.copyfile(PACKAGING / "python313._pth", runtime / "python313._pth")


def stage_ffmpeg(ff_zip: Path, pin: dict, stage: Path) -> None:
    top = pin["top_dir"]
    members = (
        (f"{top}/bin/ffmpeg.exe", stage / "bin" / "ffmpeg.exe"),
        (f"{top}/bin/ffprobe.exe", stage / "bin" / "ffprobe.exe"),
        (f"{top}/LICENSE.txt", stage / "LICENSES" / "FFmpeg-LICENSE.txt"),
    )
    with zipfile.ZipFile(ff_zip) as zf:
        for member, dest in members:
            extract_member(zf, member, dest)


def check_ffmpeg(stage: Path, pin: dict) -> None:
    exe = stage / "bin" / "ffmpeg.exe"
    conf = subprocess.run([str(exe), "-hide_banner", "-buildconf"], capture_output=True, text=True, check=True).stdout
    missing = [flag for flag in REQUIRED_BUILDCONF if flag not in conf]
    if missing:
        fail(f"pinned ffmpeg lacks {', '.join(missing)}")
    first = subprocess.run([str(exe), "-version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    if pin["version"] not in first:
        fail(f"unexpected ffmpeg version line: {first}")
    print(f"ffmpeg OK: {first.split(' Copyright')[0]}")


def tool_version() -> str:
    text = (SRC_PKG / "friendpack" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"$', text, re.M)
    if not match:
        fail("cannot read __version__ from friendpack/__init__.py")
    return match.group(1)


def source_commit() -> str:
    head = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/game_frame_classifier/sourcing",
         "src/game_frame_classifier/friendpack", "config/recipe.json", "packaging/friendpack"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return f"{head}-dirty" if dirty else head


def stage_app(stage: Path, commit: str) -> None:
    app_pkg = stage / "app" / "game_frame_classifier"
    app_pkg.mkdir(parents=True)
    (app_pkg / "__init__.py").write_text('"""GFC friend pack application package."""\n', encoding="utf-8")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in ("sourcing", "friendpack"):
        shutil.copytree(SRC_PKG / name, app_pkg / name, ignore=ignore)
    init = app_pkg / "friendpack" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    if text.count('SOURCE_COMMIT = "dev"') != 1:
        fail('friendpack/__init__.py must contain SOURCE_COMMIT = "dev" exactly once')
    init.write_text(text.replace('SOURCE_COMMIT = "dev"', f'SOURCE_COMMIT = "{commit}"'), encoding="utf-8")
    (stage / "app" / "gfc_friendpack.py").write_text(ENTRY_POINT, encoding="utf-8")


def stage_text_files(stage: Path, pins: dict, collector_name: str, collector_contact: str) -> None:
    bat = (PACKAGING / "START HERE.bat").read_text(encoding="utf-8")
    (stage / "START HERE.bat").write_text(bat, encoding="utf-8", newline="\r\n")
    readme = (PACKAGING / "README.txt.tmpl").read_text(encoding="utf-8")
    readme = readme.replace("{collector_name}", collector_name).replace("{collector_contact}", collector_contact)
    if "{" in readme or "}" in readme:
        fail("README template has an unknown placeholder")
    (stage / "README.txt").write_text(readme, encoding="utf-8", newline="\r\n")
    (stage / "config").mkdir()
    shutil.copyfile(REPO / "config" / "recipe.json", stage / "config" / "recipe.json")
    licenses = stage / "LICENSES"
    licenses.mkdir(exist_ok=True)
    shutil.copyfile(stage / "runtime" / "LICENSE.txt", licenses / "Python-LICENSE.txt")
    ff = pins["ffmpeg"]
    (licenses / "FFmpeg-SOURCE.txt").write_text(
        "bin\\ffmpeg.exe and bin\\ffprobe.exe are unmodified FFmpeg builds licensed under the GPL\n"
        "(see FFmpeg-LICENSE.txt).\n"
        f"Version: {ff['version']}\n"
        f"Build: {ff['build_url']}\n"
        f"FFmpeg source for this version: {ff['source_url']}\n"
        "Build scripts and sources of every bundled library: https://github.com/FFmpeg-Builds/FFmpeg-Builds\n",
        encoding="utf-8",
        newline="\r\n",
    )


def smoke_test(stage: Path, commit: str) -> None:
    py = stage / "runtime" / "python.exe"
    blocked = subprocess.run([str(py), "-B", "-c", "import socket"], capture_output=True, text=True)
    if blocked.returncode == 0:
        fail("the bundled Python can still import socket")
    clips = STAGE_ROOT / "smoke_clips" / "Valorant"
    clips.mkdir(parents=True)
    try:
        subprocess.run(
            [str(stage / "bin" / "ffmpeg.exe"), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=s=640x360:r=30:d=21", "-pix_fmt", "yuv420p", "-c:v", "libx264",
             str(clips / "smoke 2026-01-02 10-00-00.mp4")],
            check=True,
        )
        (stage / "config" / "user.json").write_text(json.dumps(SMOKE_USER), encoding="utf-8")
        run = subprocess.run(
            [str(py), "-B", "-X", "utf8", str(stage / "app" / "gfc_friendpack.py"), str(clips),
             "--yes", "--game", "Valorant", "--no-open"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=stage,
        )
        print(run.stdout)
        if run.returncode != 0:
            fail(f"smoke run exited with {run.returncode}\n{run.stderr}")
        zips = sorted((stage / "output").glob("GFC_Valorant_smoke_*.zip"))
        if len(zips) != 1:
            fail(f"expected 1 smoke zip, found {len(zips)}")
        sys.path.insert(0, str(REPO / "src"))
        from game_frame_classifier.sourcing.packzip import validate_pack_zip

        (manifest,) = validate_pack_zip(zips[0], STAGE_ROOT / "smoke_scratch")
        checks = {
            "slots": manifest["output"]["slots"] == 5,
            "tiers": manifest["output"]["tiers"] == ["full", "crf45"],
            "build": manifest["ffmpeg"]["build"] == "bundled",
            "commit": manifest["tool"]["source_commit"] == commit,
        }
        bad = [name for name, ok in checks.items() if not ok]
        if bad:
            fail(f"smoke manifest check failed: {bad}")
        print("smoke test OK: 5 slots, bundled ffmpeg, commit stamped")
    finally:
        for folder in (stage / "output", STAGE_ROOT / "smoke_clips", STAGE_ROOT / "smoke_scratch"):
            if folder.exists():
                shutil.rmtree(folder)
        for name in ("user.json", "history.json"):
            (stage / "config" / name).unlink(missing_ok=True)


def make_dist_zip(stage: Path) -> Path:
    DIST.mkdir(exist_ok=True)
    out = DIST / f"{stage.name}.zip"
    part = out.with_name(out.name + ".part")
    with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                zf.write(path, f"{stage.name}/{path.relative_to(stage).as_posix()}")
    part.replace(out)
    return out


def cmd_fetch(_args: argparse.Namespace) -> None:
    pins = load_pins()
    for key in ("python", "ffmpeg"):
        download(pins[key])


def cmd_build(args: argparse.Namespace) -> None:
    pins = load_pins()
    py_zip, ff_zip = cached_path(pins["python"]), cached_path(pins["ffmpeg"])
    for path, pin in ((py_zip, pins["python"]), (ff_zip, pins["ffmpeg"])):
        if not path.is_file():
            fail(f"{path.name} is not in the cache; run: python scripts/build_friend_pack.py fetch")
        verify(path, pin)
    version, commit = tool_version(), source_commit()
    stage = STAGE_ROOT / f"GFC-FriendPack-v{version}"
    if STAGE_ROOT.exists():
        shutil.rmtree(STAGE_ROOT)
    stage.mkdir(parents=True)
    stage_runtime(py_zip, pins["python"], stage / "runtime")
    stage_ffmpeg(ff_zip, pins["ffmpeg"], stage)
    check_ffmpeg(stage, pins["ffmpeg"])
    stage_app(stage, commit)
    stage_text_files(stage, pins, args.collector_name, args.collector_contact)
    smoke_test(stage, commit)
    out = make_dist_zip(stage)
    print(f"built {out.relative_to(REPO)}  {out.stat().st_size / (1 << 20):.1f} MiB  sha256 {sha256_of(out)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="download and verify the pinned Python and ffmpeg zips").set_defaults(func=cmd_fetch)
    build = sub.add_parser("build", help="stage, smoke-test and zip the friend pack")
    build.add_argument("--collector-name", required=True, help="name shown in README.txt")
    build.add_argument("--collector-contact", required=True, help="contact shown in README.txt")
    build.set_defaults(func=cmd_build)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
