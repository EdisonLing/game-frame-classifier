"""Load and validate the extraction recipe (Frame Export Kit spec §4.1)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import SAMPLER, SCHEMA_RECIPE

X264_PRESETS = (
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow", "placebo",
)
ENCODERS = ("auto", "x264")
FRAME_MODES = ("native", "compact")
HDR_POLICIES = ("tonemap_hable_v1",)
BUDGET_SELECTIONS = ("spread_days_v1",)
DERIVE_ASPECTS = ("pad_16x9",)
SCALE_FLAGS = ("bicubic",)
KNOWN_KEYS = frozenset({
    "schema", "recipe_id", "interval_s", "include_full", "crf_list", "x264_preset",
    "encoder", "gpu_qp", "jpeg_qscale", "frame_mode", "compact_size", "hdr_policy", "derive",
    "video_extensions", "min_duration_s", "footage_budget_min", "budget_selection",
    "games", "questions",
})
DERIVE_KEYS = frozenset({"aspect", "aspect_tolerance", "scale_flags"})
QUESTION_KEYS = frozenset({"key", "prompt", "choices", "default"})
_ID = re.compile(r"[A-Za-z0-9._-]{1,40}")
_GAME = re.compile(r"[A-Za-z0-9_]{1,32}")
_KEY = re.compile(r"[a-z0-9_]{1,32}")
_EXT = re.compile(r"\.[a-z0-9]{1,8}")


class RecipeError(ValueError):
    """recipe.json is missing a field or has an invalid value."""


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    interval_s: float
    include_full: bool
    crf_list: tuple[int, ...]
    x264_preset: str
    encoder: str
    gpu_qp: dict[int, int]
    jpeg_qscale: int
    frame_mode: str
    compact_size: tuple[int, int]
    hdr_policy: str
    derive_aspect: str
    aspect_tolerance: float
    scale_flags: str
    video_extensions: tuple[str, ...]
    min_duration_s: float
    footage_budget_min: int
    budget_selection: str
    games: tuple[str, ...]
    questions: dict[str, list[dict[str, Any]]]

    @property
    def tiers(self) -> tuple[str, ...]:
        full = ("full",) if self.include_full else ()
        return full + tuple(f"crf{n}" for n in self.crf_list)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_RECIPE,
            "recipe_id": self.recipe_id,
            "interval_s": self.interval_s,
            "include_full": self.include_full,
            "crf_list": list(self.crf_list),
            "tiers": list(self.tiers),
            "x264_preset": self.x264_preset,
            "encoder": self.encoder,
            "gpu_qp": {str(crf): qp for crf, qp in sorted(self.gpu_qp.items())},
            "jpeg_qscale": self.jpeg_qscale,
            "frame_mode": self.frame_mode,
            "compact_size": list(self.compact_size),
            "hdr_policy": self.hdr_policy,
            "derive": {
                "aspect": self.derive_aspect,
                "aspect_tolerance": self.aspect_tolerance,
                "scale_flags": self.scale_flags,
            },
            "video_extensions": list(self.video_extensions),
            "min_duration_s": self.min_duration_s,
            "footage_budget_min": self.footage_budget_min,
            "budget_selection": self.budget_selection,
            "games": list(self.games),
            "questions": self.questions,
            "sampler": SAMPLER,
        }


def parse_crf_list(value: Any) -> tuple[int, ...]:
    """Accept "45", "38,45" or a JSON list; return sorted unique CRFs."""
    if isinstance(value, str):
        parts: list[Any] = [p.strip() for p in value.split(",") if p.strip()]
    elif isinstance(value, list):
        parts = value
    else:
        raise RecipeError("crf_list must be a comma-separated string or a list")
    found: set[int] = set()
    for part in parts:
        if isinstance(part, bool):
            raise RecipeError(f"crf_list entry {part!r} is not a whole number")
        if isinstance(part, int):
            crf = part
        elif isinstance(part, str) and part.strip().isdigit():
            crf = int(part.strip())
        else:
            raise RecipeError(f"crf_list entry {part!r} is not a whole number")
        if not 1 <= crf <= 51:
            raise RecipeError(f"crf_list entry {crf} must be from 1 to 51")
        found.add(crf)
    return tuple(sorted(found))


def _gpu_qp(value: Any, crf_list: tuple[int, ...], encoder: str) -> dict[int, int]:
    """{"45": 51}: the constant GPU QP used in place of each x264 CRF tier."""
    if not isinstance(value, dict):
        raise RecipeError('gpu_qp must be an object like {"45": 51}')
    out: dict[int, int] = {}
    for key, qp in value.items():
        if not isinstance(key, str) or not key.isdigit() or not 1 <= int(key) <= 51:
            raise RecipeError(f"gpu_qp key {key!r} must be a CRF from 1 to 51")
        if isinstance(qp, bool) or not isinstance(qp, int) or not 1 <= qp <= 51:
            raise RecipeError(f"gpu_qp value for {key} must be a whole number from 1 to 51")
        out[int(key)] = qp
    missing = [crf for crf in crf_list if crf not in out]
    if encoder == "auto" and missing:
        raise RecipeError(f"gpu_qp has no entry for CRF {missing[0]} (needed when encoder is auto)")
    return out


def _number(d: dict[str, Any], key: str, lo: float, hi: float) -> float:
    value = d[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise RecipeError(f"{key} must be a number from {lo:g} to {hi:g}")
    return float(value)


def _integer(d: dict[str, Any], key: str, lo: int, hi: int) -> int:
    value = d[key]
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise RecipeError(f"{key} must be a whole number from {lo} to {hi}")
    return value


def _choice(d: dict[str, Any], key: str, choices: tuple[str, ...]) -> str:
    value = d[key]
    if not isinstance(value, str) or value not in choices:
        raise RecipeError(f"{key} must be one of: {', '.join(choices)}")
    return value


def _compact_size(value: Any) -> tuple[int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(isinstance(v, bool) or not isinstance(v, int) for v in value)
        or any(v < 16 or v > 3840 or v % 2 for v in value)
    ):
        raise RecipeError("compact_size must be [width, height] with even numbers from 16 to 3840")
    return value[0], value[1]


def _derive(value: Any) -> tuple[str, float, str]:
    if not isinstance(value, dict) or set(value) != DERIVE_KEYS:
        raise RecipeError("derive must have exactly: aspect, aspect_tolerance, scale_flags")
    return (
        _choice(value, "aspect", DERIVE_ASPECTS),
        _number(value, "aspect_tolerance", 0, 0.2),
        _choice(value, "scale_flags", SCALE_FLAGS),
    )


def _extensions(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise RecipeError('video_extensions must be a non-empty list like [".mp4"]')
    out: list[str] = []
    for ext in value:
        if not isinstance(ext, str) or not _EXT.fullmatch(ext.lower()):
            raise RecipeError(f'video_extensions entry {ext!r} must look like ".mp4"')
        if ext.lower() not in out:
            out.append(ext.lower())
    return tuple(out)


def _games(value: Any) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(g, str) or not _GAME.fullmatch(g) for g in value)
        or len(set(value)) != len(value)
        or "Other" in value
    ):
        raise RecipeError("games must be a list of unique names using letters, digits and _ (not Other)")
    return tuple(value)


def _questions(value: Any, games: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        raise RecipeError("questions must be an object")
    out: dict[str, list[dict[str, Any]]] = {}
    for group, items in value.items():
        if group != "all" and group not in games:
            raise RecipeError(f"questions group {group!r} must be 'all' or a game in games")
        if not isinstance(items, list):
            raise RecipeError(f"questions.{group} must be a list")
        clean: list[dict[str, Any]] = []
        for q in items:
            if not isinstance(q, dict) or set(q) != QUESTION_KEYS:
                raise RecipeError("each question needs exactly: key, prompt, choices, default")
            choices = q["choices"]
            if (
                not isinstance(q["key"], str)
                or not _KEY.fullmatch(q["key"])
                or not isinstance(q["prompt"], str)
                or not q["prompt"].strip()
                or not isinstance(choices, list)
                or not choices
                or any(not isinstance(c, str) or not c for c in choices)
                or q["default"] not in choices
            ):
                raise RecipeError(
                    f"question {q.get('key')!r} is invalid (key a-z0-9_, prompt text, "
                    "choices list, default one of the choices)"
                )
            clean.append({"key": q["key"], "prompt": q["prompt"], "choices": list(choices), "default": q["default"]})
        out[group] = clean
    return out


def recipe_from_dict(data: Any, overrides: dict[str, Any] | None = None) -> Recipe:
    """Validate a recipe dict strictly; unknown and missing fields are errors."""
    if not isinstance(data, dict):
        raise RecipeError("recipe must be a JSON object")
    d = {**data, **(overrides or {})}
    unknown = sorted(set(d) - KNOWN_KEYS)
    if unknown:
        raise RecipeError(f"unknown field: {unknown[0]}")
    missing = sorted(KNOWN_KEYS - set(d))
    if missing:
        raise RecipeError(f"missing field: {missing[0]}")
    if d["schema"] != SCHEMA_RECIPE:
        raise RecipeError(f"schema must be {SCHEMA_RECIPE}")
    if not isinstance(d["recipe_id"], str) or not _ID.fullmatch(d["recipe_id"]):
        raise RecipeError("recipe_id must be 1-40 letters, digits, '.', '_' or '-'")
    if not isinstance(d["include_full"], bool):
        raise RecipeError("include_full must be true or false")
    crf_list = parse_crf_list(d["crf_list"])
    if not d["include_full"] and not crf_list:
        raise RecipeError("no tiers: set include_full to true or add a crf_list value")
    aspect, tolerance, flags = _derive(d["derive"])
    games = _games(d["games"])
    return Recipe(
        recipe_id=d["recipe_id"],
        interval_s=_number(d, "interval_s", 0.5, 60),
        include_full=d["include_full"],
        crf_list=crf_list,
        x264_preset=_choice(d, "x264_preset", X264_PRESETS),
        encoder=_choice(d, "encoder", ENCODERS),
        gpu_qp=_gpu_qp(d["gpu_qp"], crf_list, d["encoder"]),
        jpeg_qscale=_integer(d, "jpeg_qscale", 2, 31),
        frame_mode=_choice(d, "frame_mode", FRAME_MODES),
        compact_size=_compact_size(d["compact_size"]),
        hdr_policy=_choice(d, "hdr_policy", HDR_POLICIES),
        derive_aspect=aspect,
        aspect_tolerance=tolerance,
        scale_flags=flags,
        video_extensions=_extensions(d["video_extensions"]),
        min_duration_s=_number(d, "min_duration_s", 0, 3600),
        footage_budget_min=_integer(d, "footage_budget_min", 0, 100_000),
        budget_selection=_choice(d, "budget_selection", BUDGET_SELECTIONS),
        games=games,
        questions=_questions(d["questions"], games),
    )


def load_recipe(path: Path, overrides: dict[str, Any] | None = None) -> Recipe:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise RecipeError(f"cannot read {path.name}: {exc.strerror}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecipeError(f"{path.name} is not valid JSON (line {exc.lineno})") from exc
    return recipe_from_dict(data, overrides)
