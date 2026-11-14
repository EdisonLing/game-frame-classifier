"""Unit tests for quality-tier mapping (no ffmpeg required)."""

from __future__ import annotations

import pytest

from game_frame_classifier.quality_encoder import (
    AUGMENT_CRF_MAX,
    AUGMENT_CRF_MIN,
    TIER_CRF,
    crf_for_tier,
    validate_crf,
)


def test_tier_crf_map_matches_proposal() -> None:
    assert TIER_CRF == {"full": 0, "medium": 28, "low": 38}
    assert AUGMENT_CRF_MIN == 28
    assert AUGMENT_CRF_MAX == 40


@pytest.mark.parametrize(
    ("tier", "crf"),
    [("full", 0), ("FULL", 0), ("medium", 28), ("low", 38)],
)
def test_crf_for_tier(tier: str, crf: int) -> None:
    assert crf_for_tier(tier) == crf


def test_crf_for_tier_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown quality tier"):
        crf_for_tier("ultra")


def test_validate_crf_bounds() -> None:
    assert validate_crf(0) == 0
    assert validate_crf(51) == 51
    with pytest.raises(ValueError):
        validate_crf(-1)
    with pytest.raises(ValueError):
        validate_crf(52)
    with pytest.raises(TypeError):
        validate_crf(True)  # type: ignore[arg-type]
