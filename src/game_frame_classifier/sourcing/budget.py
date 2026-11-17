"""Footage budget spread across recording days (spread_days_v1, friend-pack spec §5.2a)."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable


@dataclass(frozen=True)
class Candidate:
    key: str
    duration_s: float
    start: datetime


def select_within_budget(
    candidates: list[Candidate],
    budget_s: float,
    day_of: Callable[[datetime], date],
) -> tuple[list[str], list[str]]:
    """Return (selected keys, over-budget keys), both in recording order."""
    ordered = sorted(candidates, key=lambda c: (c.start, c.key))
    if budget_s <= 0 or sum(c.duration_s for c in ordered) <= budget_s:
        return [c.key for c in ordered], []
    days: dict[date, deque[Candidate]] = defaultdict(deque)
    for c in sorted(candidates, key=lambda c: c.key):
        days[day_of(c.start)].append(c)
    queues = [days[d] for d in sorted(days)]
    chosen: set[str] = set()
    used = 0.0
    progress = True
    while progress:
        progress = False
        for queue in queues:
            while queue:
                c = queue.popleft()
                if used + c.duration_s <= budget_s:
                    chosen.add(c.key)
                    used += c.duration_s
                    progress = True
                    break
    if not chosen:
        chosen.add(min(ordered, key=lambda c: (c.duration_s, c.key)).key)
    return [c.key for c in ordered if c.key in chosen], [c.key for c in ordered if c.key not in chosen]
