"""Build stable session-aware split manifests from cleaned slots and clip metadata.

Reads the stage-one manifests and writes split tables under ``data/manifests/splits``;
the complete contract is in ``docs/roadmap/tools/dataset-splitter.md``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from game_frame_classifier.sourcing.labels import GAMES
from game_frame_classifier.sourcing.manifests import write_json, write_table

SPLITS = ("train", "val", "test_session", "test_source")
ASSIGNABLE_SPLITS = SPLITS[:3]
SPLIT_RANK = {name: index for index, name in enumerate(SPLITS)}
# Below this many groups in a game the median of their counts is just their mean, so one small
# source would cut a large one in half; with one or two groups the share cap is not applied.
MEDIAN_MIN_GROUPS = 3
SPLIT_COLUMNS = (
    "slot_id", "clip_key", "bucket", "target_time_s", "game", "label", "source",
    "source_kind", "session", "split", "tier", "path", "path_full", "path_low",
    "public_examples_ok",
)
LEDGER_COLUMNS = ("clip_key", "split", "first_assigned_utc", "note")
SESSION_COLUMNS = (
    "clip_key", "game", "source", "session", "recorded_start_utc",
    "recorded_start_source", "duration_s", "slots_kept", "split",
)
COUNT_COLUMNS = (
    "game", "split", "slots", "slots_full", "slots_low", "slots_quick", "clips",
    "sessions", "sources", "groups",
)
SOURCE_COLUMNS = ("game", "source", "group", "source_kind", "split", "slots", "share")
UNUSED_COLUMNS = ("slot_id", "clip_key", "game", "source", "session", "split", "reason")
REASSIGNED_COLUMNS = ("clip_key", "from_split", "to_split", "run_utc", "reason")


class SplitterError(RuntimeError):
    """An expected policy or input error with a command exit code."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_time(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SplitterError(f"invalid recorded_start_utc {value!r}", 2) from exc


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise SplitterError(f"missing input: {path}", 2)
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def load_config(path: Path) -> dict[str, Any]:
    """Load and minimally validate a split policy."""
    if not path.is_file():
        raise SplitterError(f"missing config: {path}", 2)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SplitterError(f"invalid JSON config: {path}", 2) from exc
    required = {"schema", "split_id", "seed", "targets", "session_gap_min", "holdout_sources", "max_source_share", "test_design"}
    missing = required - set(config)
    if missing or config.get("schema") != "gfc.split/1":
        raise SplitterError(f"invalid split config; missing {sorted(missing)} or unsupported schema", 2)
    if set(config["targets"]) != set(ASSIGNABLE_SPLITS):
        raise SplitterError("targets must contain train, val and test_session", 2)
    config.setdefault("max_slots_per_source", 0)
    config.setdefault("source_slots", {})
    config.setdefault("train_slots_per_source", 0)
    config.setdefault("source_groups", {})
    limits = [config["max_slots_per_source"], config["train_slots_per_source"], *config["source_slots"].values()]
    if not isinstance(config["source_slots"], dict) or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in limits
    ):
        raise SplitterError("max_slots_per_source, train_slots_per_source and source_slots values must be whole numbers >= 0", 2)
    _validate_source_groups_shape(config["source_groups"])
    return config


def _validate_source_groups_shape(source_groups: Any) -> None:
    if not isinstance(source_groups, dict):
        raise SplitterError("source_groups must be an object of group name to source lists", 2)
    seen: dict[str, str] = {}
    for group, members in source_groups.items():
        if not isinstance(group, str) or not group:
            raise SplitterError("source_groups keys must be non-empty strings", 2)
        if not isinstance(members, list) or not members or any(not isinstance(member, str) or not member for member in members):
            raise SplitterError(f"source_groups[{group!r}] must be a non-empty list of source names", 2)
        for member in members:
            if member in seen:
                raise SplitterError(f"source {member!r} is in source_groups {seen[member]!r} and {group!r}", 2)
            seen[member] = group


def resolve_source_groups(source_groups: dict[str, list[str]], sources: Iterable[str]) -> dict[str, str]:
    """Map each source to its group; unlisted sources are their own group.

    A group name that equals a source name is allowed only when that source is the group's
    sole member. Duplicate membership is rejected by ``_validate_source_groups_shape``.
    """
    known = set(sources)
    for members in source_groups.values():
        known.update(members)
    source_to_group: dict[str, str] = {source: source for source in known}
    for group, members in source_groups.items():
        if group in known and members != [group]:
            raise SplitterError(
                f"source_groups[{group!r}] reuses a source name but is not that source alone", 2,
            )
        for member in members:
            source_to_group[member] = group
    return source_to_group


def grouped_sources(source_to_group: dict[str, str]) -> dict[str, list[str]]:
    """Invert source→group into group→sorted sources."""
    groups: dict[str, list[str]] = defaultdict(list)
    for source, group in sorted(source_to_group.items()):
        groups[group].append(source)
    return dict(groups)


def expand_holdout_sources(
    holdout_sources: dict[str, list[str]],
    source_to_group: dict[str, str],
) -> dict[str, set[str]]:
    """Resolve holdout names (group or source) to source sets; reject a split group."""
    groups = grouped_sources(source_to_group)
    heldout: dict[str, set[str]] = {}
    for game, names in holdout_sources.items():
        resolved: set[str] = set()
        for name in names:
            if name in groups:
                resolved.update(groups[name])
            else:
                resolved.add(name)
        for group, members in groups.items():
            member_set = set(members)
            overlap = resolved & member_set
            if overlap and overlap != member_set:
                raise SplitterError(
                    f"group {group} would be split between held-out and training", 1,
                )
        # A name that is not a known source yet (footage to come) stays in the set as its own group.
        heldout[game] = resolved
    return heldout


def source_limit(config: dict[str, Any], source: str) -> int:
    """Most kept slots one source may contribute to one game; 0 = no limit."""
    return int(config["source_slots"].get(source, config["max_slots_per_source"]))


def apply_source_limits(slots: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep at most the configured number of slots per (game, source), all splits together.

    Slots are ranked by sha256("<seed>:<slot_id>") and the first N kept, so the slots used at a
    lower limit are always a subset of those used at a higher one, and every clip is thinned
    about evenly.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for slot in slots:
        groups[(slot["game"], slot["source"])].append(slot)
    dropped_ids: set[str] = set()
    dropped: list[dict[str, Any]] = []
    for (game, source), group in groups.items():
        limit = source_limit(config, source)
        if not limit or len(group) <= limit:
            continue
        ranked = sorted(group, key=lambda slot: _sha256_text(f"{config['seed']}:{slot['slot_id']}"))
        for slot in ranked[limit:]:
            dropped_ids.add(slot["slot_id"])
            dropped.append({
                "slot_id": slot["slot_id"], "clip_key": slot["clip_key"], "game": game,
                "source": source, "session": "", "split": "", "reason": "source_limit",
            })
    return [slot for slot in slots if slot["slot_id"] not in dropped_ids], dropped


def build_sessions(clips: list[dict[str, str]], gap_min: float) -> list[dict[str, Any]]:
    """Group clips by game/source and recording-time overlap or gap."""
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for clip in clips:
        grouped[(clip["game"], clip["source"])].append(clip)
    sessions: list[dict[str, Any]] = []
    for (game, source), group in sorted(grouped.items()):
        timed = sorted((row for row in group if row.get("recorded_start_utc")), key=lambda row: (row["recorded_start_utc"], row["clip_key"]))
        untimed = sorted((row for row in group if not row.get("recorded_start_utc")), key=lambda row: row["clip_key"])
        batches: list[list[dict[str, str]]] = []
        latest_end: dt.datetime | None = None
        for clip in timed:
            start = _parse_time(clip["recorded_start_utc"])
            assert start is not None
            duration = float(clip.get("duration_s") or 0)
            if not batches or latest_end is None or start > latest_end + dt.timedelta(minutes=gap_min):
                batches.append([clip])
                latest_end = start + dt.timedelta(seconds=duration)
            else:
                batches[-1].append(clip)
                latest_end = max(latest_end, start + dt.timedelta(seconds=duration))
        batches.extend([[clip] for clip in untimed])
        for index, batch in enumerate(batches, 1):
            sessions.append({"game": game, "source": source, "session": f"{source}:{game}:s{index:03d}", "clips": batch})
    return sessions


def tier_for_slot(clip_key: str, bucket: int, path_low: str) -> str:
    """Return the stable tier selected for a slot."""
    if not path_low:
        return "full"
    offset = int(_sha256_text(clip_key)[:8], 16)
    return "crf45" if (bucket + offset) % 2 == 1 else "full"


def _load_ledger(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    rows = _load_csv(path)
    ledger = {row["clip_key"]: row for row in rows}
    if len(ledger) != len(rows):
        raise SplitterError("ledger contains duplicate clip_key entries", 1)
    if any(row.get("split") not in SPLIT_RANK for row in rows):
        raise SplitterError("ledger contains an invalid split", 1)
    return ledger


def _validate_ledger(ledger: dict[str, dict[str, str]], clips: dict[str, dict[str, str]], heldout: dict[str, set[str]]) -> None:
    for clip_key, entry in ledger.items():
        clip = clips.get(clip_key)
        if clip is None:
            continue
        should_holdout = clip["source"] in heldout.get(clip["game"], set())
        if (entry["split"] in {"train", "val"} and should_holdout) or (entry["split"] == "test_source" and not should_holdout):
            raise SplitterError("ledger contradicts holdout_sources; use a new split_id", 1)


def _choose_split(current: dict[str, int], sessions: dict[str, int], targets: dict[str, float]) -> str:
    """Greedy fill for one game: first any split with no session yet (train, val, test_session),
    then the split with the largest deficit of kept slots."""
    for split in ASSIGNABLE_SPLITS:
        if not sessions[split]:
            return split
    total = sum(current[split] for split in ASSIGNABLE_SPLITS)
    deficits = {split: targets[split] - (current[split] / total if total else 0.0) for split in ASSIGNABLE_SPLITS}
    return max(ASSIGNABLE_SPLITS, key=lambda split: (deficits[split], -ASSIGNABLE_SPLITS.index(split)))


def _source_kind(source: str) -> str:
    if source.startswith("contributor_"):
        return "contributor"
    if source.startswith("public_"):
        return "public"
    return "personal"


def _write_counts(
    output: Path, used: list[dict[str, Any]], source_to_group: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    mapping = source_to_group or {}
    rows: list[dict[str, Any]] = []
    for game in (*GAMES, "ALL"):
        for split in (*SPLITS, "ALL"):
            subset = [slot for slot in used if (game == "ALL" or slot["game"] == game) and (split == "ALL" or slot["split"] == split)]
            rows.append({
                "game": game, "split": split, "slots": len(subset),
                "slots_full": sum(slot["tier"] == "full" for slot in subset),
                "slots_low": sum(slot["tier"] == "crf45" for slot in subset),
                "slots_quick": sum(not slot["path_low"] for slot in subset),
                "clips": len({slot["clip_key"] for slot in subset}),
                "sessions": len({slot["session"] for slot in subset}),
                "sources": len({slot["source"] for slot in subset}),
                "groups": len({mapping.get(slot["source"], slot["source"]) for slot in subset}),
            })
    write_table(rows, COUNT_COLUMNS, output / "counts.csv", output / "counts.json")
    return rows


def _write_sources(
    output: Path, used: list[dict[str, Any]], source_to_group: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    mapping = source_to_group or {}
    rows: list[dict[str, Any]] = []
    for game, split in ((game, split) for game in GAMES for split in SPLITS):
        subset = [slot for slot in used if slot["game"] == game and slot["split"] == split]
        total = len(subset)
        for source in sorted({slot["source"] for slot in subset}):
            source_slots = [slot for slot in subset if slot["source"] == source]
            rows.append({
                "game": game, "source": source,
                "group": mapping.get(source, source),
                "source_kind": source_slots[0]["source_kind"], "split": split,
                "slots": len(source_slots), "share": len(source_slots) / total if total else 0,
            })
    write_table(rows, SOURCE_COLUMNS, output / "sources.csv", output / "sources.json")
    return rows


def _apply_source_cap(
    slots: list[dict[str, Any]], seed: int, requested_cap: float, train_slots_cap: int = 0,
    source_to_group: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Thin train slots only, per game, so no person (source group) dominates (D33).

    1. ``train_slots_cap`` (when > 0): at most that many train slots per group.
    2. Share cap: with k groups, ``requested_cap`` when it is at least 1/k. A lower cap cannot be
       met (it would trim everyone to the smallest group), so each group is instead capped at
       the median of the game's per-group train counts, when k >= 3; with one or two groups no
       share cap applies (the median of two counts is their mean).

    Within a group, slots are pooled across its sources and the highest sha256("<seed>:<slot_id>")
    are dropped first. With an empty ``source_groups`` each source is its own group.
    """
    mapping = source_to_group or {}
    dropped: list[dict[str, Any]] = []
    removed: set[int] = set()

    def drop(group_slots: list[dict[str, Any]], counts: dict[str, int], group: str) -> None:
        candidate = group_slots[len(group_slots) - counts[group]]
        counts[group] -= 1
        removed.add(id(candidate))
        dropped.append({
            "slot_id": candidate["slot_id"], "clip_key": candidate["clip_key"],
            "game": candidate["game"], "source": candidate["source"],
            "session": candidate["session"], "split": "train", "reason": "source_cap",
        })

    for game in GAMES:
        by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for slot in slots:
            if slot["game"] == game and slot["split"] == "train":
                group = mapping.get(slot["source"], slot["source"])
                by_group[group].append(slot)
        if not by_group:
            continue
        # Highest hash first: each group drops from the front of its pooled list.
        for group_slots in by_group.values():
            group_slots.sort(key=lambda slot: _sha256_text(f"{seed}:{slot['slot_id']}"), reverse=True)
        counts = {group: len(group_slots) for group, group_slots in by_group.items()}
        if train_slots_cap > 0:
            for group in counts:
                while counts[group] > train_slots_cap:
                    drop(by_group[group], counts, group)
        k = len(counts)
        if float(requested_cap) >= 1 / k:
            total = sum(counts.values())
            while True:
                offenders = [group for group, count in counts.items() if count > requested_cap * total]
                if not offenders:
                    break
                group = max(offenders, key=lambda name: (counts[name], name))
                drop(by_group[group], counts, group)
                total -= 1
        elif k >= MEDIAN_MIN_GROUPS:
            limit = int(statistics.median(counts.values()))
            for group in counts:
                while counts[group] > limit:
                    drop(by_group[group], counts, group)
    return [slot for slot in slots if id(slot) not in removed], dropped


def _print_plan(sessions: list[dict[str, Any]], slot_by_clip: dict[str, list[dict[str, Any]]]) -> None:
    per_source: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for session in sessions:
        size = sum(len(slot_by_clip[clip["clip_key"]]) for clip in session["clips"])
        print(f"{session['session']}: {len(session['clips'])} clip(s), {size} kept slot(s)")
        totals = per_source[(session["game"], session["source"])]
        totals[0] += 1
        totals[1] += len(session["clips"])
        totals[2] += size
    print("per source:")
    for (game, source), (n_sessions, n_clips, n_slots) in sorted(per_source.items()):
        print(f"  {game} / {source}: {n_sessions} session(s), {n_clips} clip(s), {n_slots} kept slot(s)")


def run_split(data_root: Path, config_path: Path, *, plan: bool = False, reset: bool = False, freeze: bool = False) -> dict[str, Any]:
    """Build or report a stable split according to a policy."""
    config = load_config(config_path)
    manifests = data_root / "manifests"
    slots_path, clips_path = manifests / "slots_clean.csv", manifests / "clips_index.csv"
    raw_slots, raw_clips = _load_csv(slots_path), _load_csv(clips_path)
    clips = {row["clip_key"]: row for row in raw_clips}
    slots = [dict(row) for row in raw_slots if _as_bool(row.get("keep", ""))]
    for slot in slots:
        clip = clips.get(slot.get("clip_key", ""))
        if clip is None:
            raise SplitterError(f"slot references absent clip: {slot.get('clip_key')}", 2)
        slot.update({key: clip.get(key, "") for key in ("game", "source", "public_examples_ok")})
        slot["source_kind"] = clip.get("source_kind") or _source_kind(slot["source"])
        slot["bucket"] = int(slot["bucket"])
    unknown = sorted({clip["game"] for clip in clips.values()} - set(GAMES))
    if unknown:
        raise SplitterError(f"clips_index has games outside the label set: {', '.join(unknown)}", 2)
    slots, limited = apply_source_limits(slots, config)
    source_to_group = resolve_source_groups(
        config["source_groups"],
        {clip["source"] for clip in clips.values()},
    )
    resolved_groups = grouped_sources(source_to_group)
    sessions = build_sessions(list(clips.values()), float(config["session_gap_min"]))
    slot_by_clip: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for slot in slots:
        slot_by_clip[slot["clip_key"]].append(slot)
    output = manifests / "splits" / config["split_id"]
    ledger_path, freeze_path = output / "ledger.csv", output / "freeze.json"
    frozen = freeze_path.is_file()
    if reset and frozen:
        raise SplitterError("--reset is refused for a frozen split", 1)
    if plan:
        _print_plan(sessions, slot_by_clip)
        return {"sessions": sessions}
    if reset and ledger_path.exists():
        ledger_path.unlink()
    ledger = _load_ledger(ledger_path)
    heldout = expand_holdout_sources(config["holdout_sources"], source_to_group)
    _validate_ledger(ledger, clips, heldout)
    now, reassigned, unused = _now(), [], list(limited)
    assigned_slots: list[dict[str, Any]] = []
    session_of: dict[str, str] = {}
    filled = {game: {split: 0 for split in SPLITS} for game in GAMES}
    filled_sessions = {game: {split: 0 for split in SPLITS} for game in GAMES}

    def has_known(item: dict[str, Any]) -> bool:
        return any(clip["clip_key"] in ledger for clip in item["clips"])

    # Sessions with ledger entries first, so new sessions are filled against every existing
    # assignment; new sessions then in seeded hash order.
    visit = sorted(sessions, key=lambda item: (
        not has_known(item),
        _sha256_text(f"{config['seed']}:{min(clip['clip_key'] for clip in item['clips'])}"),
        item["game"], item["source"],
    ))
    for session in visit:
        session_clips = session["clips"]
        known = [ledger[clip["clip_key"]] for clip in session_clips if clip["clip_key"] in ledger]
        is_holdout = session["source"] in heldout.get(session["game"], set())
        known_splits = {entry["split"] for entry in known}
        bridge = len(known_splits) > 1
        if is_holdout:
            chosen = "test_source"
        elif known:
            chosen = max(known_splits, key=SPLIT_RANK.__getitem__)
        else:
            chosen = _choose_split(filled[session["game"]], filled_sessions[session["game"]], config["targets"])
        landed: set[str] = set()
        for clip in session_clips:
            clip_key = clip["clip_key"]
            old = ledger.get(clip_key)
            if frozen and bridge and old is None:
                for slot in slot_by_clip[clip_key]:
                    unused.append({"slot_id": slot["slot_id"], "clip_key": clip_key, "game": session["game"], "source": session["source"], "session": session["session"], "split": "", "reason": "bridges_splits"})
                continue
            split = old["split"] if frozen and old else chosen
            if old and not frozen and SPLIT_RANK[old["split"]] < SPLIT_RANK[chosen]:
                reassigned.append({"clip_key": clip_key, "from_split": old["split"], "to_split": chosen, "run_utc": now, "reason": "bridges_splits"})
                old["split"] = chosen
                split = chosen
            elif old and not frozen:
                split = old["split"] if SPLIT_RANK[old["split"]] >= SPLIT_RANK[chosen] else chosen
            if old is None:
                ledger[clip_key] = {"clip_key": clip_key, "split": split, "first_assigned_utc": now, "note": ""}
            # A frozen bridged session keeps its old clips in different splits; label each part
            # separately so no session label spans two splits.
            assigned_session = f"{session['session']}.{split}" if frozen and bridge else session["session"]
            session_of[clip_key] = assigned_session
            filled[session["game"]][split] += len(slot_by_clip[clip_key])
            if split not in landed:
                landed.add(split)
                filled_sessions[session["game"]][split] += 1
            for slot in slot_by_clip[clip_key]:
                row = dict(slot)
                row.update({"session": assigned_session, "split": split})
                row["tier"] = tier_for_slot(clip_key, int(row["bucket"]), row.get("path_low", ""))
                row["path"] = row["path_low"] if row["tier"] == "crf45" else row["path_full"]
                row["label"] = GAMES.index(row["game"])
                assigned_slots.append(row)

    assigned_slots, capped_unused = _apply_source_cap(
        assigned_slots, int(config["seed"]), float(config["max_source_share"]),
        int(config["train_slots_per_source"]), source_to_group,
    )
    unused.extend(capped_unused)
    output.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        rows = [
            {column: slot.get(column, "") for column in SPLIT_COLUMNS}
            for slot in sorted((slot for slot in assigned_slots if slot["split"] == split), key=lambda row: row["slot_id"])
        ]
        write_table(rows, SPLIT_COLUMNS, output / f"{split}.csv", output / f"{split}.json")
    ledger_rows = [ledger[key] for key in sorted(ledger)]
    write_table(ledger_rows, LEDGER_COLUMNS, ledger_path, output / "ledger.json")
    session_rows = []
    for session in sessions:
        for clip in session["clips"]:
            clip_key = clip["clip_key"]
            entry = ledger.get(clip_key)
            session_rows.append({
                "clip_key": clip_key, "game": session["game"], "source": session["source"],
                "session": session_of.get(clip_key, session["session"]),
                "recorded_start_utc": clip.get("recorded_start_utc", ""),
                "recorded_start_source": clip.get("recorded_start_source", ""),
                "duration_s": clip.get("duration_s", ""),
                "slots_kept": len(slot_by_clip[clip_key]), "split": entry["split"] if entry else "",
            })
    write_table(sorted(session_rows, key=lambda row: row["clip_key"]), SESSION_COLUMNS, output / "sessions.csv", output / "sessions.json")
    counts = _write_counts(output, assigned_slots, source_to_group)
    sources = _write_sources(output, assigned_slots, source_to_group)
    write_table(unused, UNUSED_COLUMNS, output / "unused.csv", output / "unused.json")
    write_table(reassigned, REASSIGNED_COLUMNS, output / "reassigned.csv", output / "reassigned.json")
    warnings: list[str] = []
    for game in GAMES:
        normal_sessions = [item for item in sessions if item["game"] == game and item["source"] not in heldout.get(game, set())]
        if len(normal_sessions) < 3:
            warnings.append(f"{game}: fewer than three non-held-out sessions")
        for split in SPLITS:
            game_slots = [slot for slot in assigned_slots if slot["game"] == game and slot["split"] == split]
            if not game_slots and (split != "test_source" or heldout.get(game)):
                warnings.append(f"{game}: empty {split}")
            elif len(game_slots) >= 200:
                low_share = sum(slot["tier"] == "crf45" for slot in game_slots) / len(game_slots)
                if not .45 <= low_share <= .55:
                    warnings.append(f"{game}/{split}: crf45 share outside 45-55%")
        train_slots = [slot for slot in assigned_slots if slot["game"] == game and slot["split"] == "train"]
        if train_slots:
            by_group: dict[str, int] = defaultdict(int)
            for slot in train_slots:
                by_group[source_to_group.get(slot["source"], slot["source"])] += 1
            if max(by_group.values()) / len(train_slots) > 1 / 15:
                warnings.append(f"{game}: a group exceeds 1/15 of train slots")
        game_clips = [clip for clip in clips.values() if clip["game"] == game]
        untimed = sum(not clip.get("recorded_start_utc") for clip in game_clips)
        low_trust = sum(clip.get("recorded_start_source") == "mtime" for clip in game_clips)
        if untimed:
            warnings.append(f"{game}: {untimed} clip(s) without a recording time (one session each)")
        if low_trust:
            warnings.append(f"{game}: {low_trust} clip(s) timed from file modification time (low trust)")
    summary = {
        "config": config, "source_groups": resolved_groups,
        "input_hashes": {"slots_clean.csv": _file_hash(slots_path), "clips_index.csv": _file_hash(clips_path)},
        "split_hashes": {split: _file_hash(output / f"{split}.csv") for split in SPLITS},
        "counts": counts, "sources": sources, "warnings": warnings, "frozen": frozen,
    }
    if freeze and not frozen:
        if not config["test_design"].strip():
            raise SplitterError("--freeze requires a non-empty test_design", 1)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
        write_json({"time": now, "git_commit": commit, "test_design": config["test_design"]}, freeze_path)
        summary["frozen"] = True
    write_json(summary, output / "summary.json")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Build stable, session-aware dataset split manifests.")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--config", type=Path, default=Path("config/split.json"))
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--freeze", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    """Run the dataset splitter command."""
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    try:
        summary = run_split(args.data_root, args.config, plan=args.plan, reset=args.reset, freeze=args.freeze)
    except SplitterError as exc:
        print(f"gfc-split: {exc}", file=sys.stderr)
        return exc.exit_code
    if not args.plan:
        print(f"wrote split {summary['config']['split_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
