"""Static checks that keep the Frame Export Kit stdlib-only and free of risky calls."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "game_frame_classifier"
FILES = sorted([*(SRC / "sourcing").glob("*.py"), *(SRC / "frame_export").glob("*.py")])
EXPECTED = {
    "sourcing/__init__.py", "sourcing/recipe.py", "sourcing/ffbin.py", "sourcing/probe.py",
    "sourcing/sampler.py", "sourcing/timeinfo.py", "sourcing/budget.py", "sourcing/hashing.py",
    "sourcing/labels.py", "sourcing/manifests.py", "sourcing/extract.py", "sourcing/derive.py",
    "sourcing/packzip.py", "sourcing/gpu.py", "frame_export/__init__.py", "frame_export/__main__.py", "frame_export/paths.py",
    "frame_export/settings.py", "frame_export/scan.py", "frame_export/run.py", "frame_export/cli.py",
}
ALLOWED_MODULES = {
    "__future__", "argparse", "bisect", "collections", "copy", "csv", "dataclasses", "datetime", "hashlib",
    "json", "math", "os", "pathlib", "platform", "re", "shutil", "struct", "subprocess", "sys",
    "threading", "time", "typing", "uuid", "zipfile", "game_frame_classifier",
}
SUBPROCESS_ALLOWED = {"sourcing/ffbin.py", "frame_export/cli.py"}
BANNED_NAMES = {"eval", "exec", "compile", "__import__", "breakpoint"}
BANNED_OS = {
    "system", "popen", "startfile", "execl", "execle", "execlp", "execv", "execve", "execvp",
    "spawnl", "spawnv", "spawnve", "fork", "kill", "symlink", "link", "chdir",
}
BANNED_ATTRS = {"home", "expanduser", "symlink_to", "hardlink_to", "gettempdir"}


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imports(path: Path) -> list[tuple[str, int]]:
    found = []
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            found += [(alias.name, 0) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level))
    return found


def test_every_module_is_checked():
    assert {rel(p) for p in FILES} == EXPECTED


@pytest.mark.parametrize("path", FILES, ids=rel)
def test_only_allowlisted_imports(path):
    bad = [name for name, level in imports(path) if level == 0 and name.split(".")[0] not in ALLOWED_MODULES]
    assert bad == []


@pytest.mark.parametrize("path", FILES, ids=rel)
def test_relative_imports_stay_in_package(path):
    assert all(level <= 1 for _, level in imports(path))


@pytest.mark.parametrize("path", FILES, ids=rel)
def test_package_imports_point_only_at_sourcing(path):
    absolute = [n for n, level in imports(path) if level == 0 and n.startswith("game_frame_classifier")]
    if rel(path).startswith("sourcing/"):
        assert absolute == []
    else:
        assert all(
            n == "game_frame_classifier.sourcing" or n.startswith("game_frame_classifier.sourcing.")
            for n in absolute
        )


@pytest.mark.parametrize("path", FILES, ids=rel)
def test_subprocess_only_where_allowed(path):
    uses = any(name.split(".")[0] == "subprocess" for name, level in imports(path) if level == 0)
    assert not uses or rel(path) in SUBPROCESS_ALLOWED


@pytest.mark.parametrize("path", FILES, ids=rel)
def test_no_dynamic_code_shell_or_escape_hatches(path):
    bad = []
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_NAMES:
                bad.append(node.func.id)
            if any(kw.arg == "shell" for kw in node.keywords):
                bad.append("shell=")
        if isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRS:
                bad.append(node.attr)
            if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in BANNED_OS:
                bad.append(f"os.{node.attr}")
    assert bad == []
