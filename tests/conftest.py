"""Pytest fixtures and path setup."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_PERSONAL_VIDEO = ROOT / "VALORANT_replay_2026.11.07-23.36.mp4"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "personal: uses a local personal clip; skipped unless available",
    )


@pytest.fixture
def personal_video_path() -> Path:
    """
    Personal smoke-test clip.

    Resolution order:
      1. env GFC_TEST_VIDEO
      2. repo-root VALORANT_replay_*.mp4 (temporary local drop)
    """
    env = os.environ.get("GFC_TEST_VIDEO")
    if env:
        path = Path(env)
        if not path.is_file():
            pytest.skip(f"GFC_TEST_VIDEO not found: {path}")
        return path.resolve()

    if DEFAULT_PERSONAL_VIDEO.is_file():
        return DEFAULT_PERSONAL_VIDEO.resolve()

    pytest.skip(
        "No personal test video (set GFC_TEST_VIDEO or place clip at repo root)"
    )
