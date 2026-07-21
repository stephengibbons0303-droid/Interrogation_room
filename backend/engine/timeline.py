"""Timeline Validator.

Specified in interrogation_learning_system.md and never built - which is why
reverse chronology could never fire "at a later stage, once the timeline has
been given": nothing knew a timeline existed.

Pure functions over claims. No LLM, no I/O, so the whole thing is unit-testable.
"""
from dataclasses import dataclass, field
from datetime import time
from typing import List, Optional

from scenario.case import LOCATIONS, WINDOW_END, WINDOW_START
from engine.state import Claim


def to_min(t: time) -> int:
    return t.hour * 60 + t.minute


def fmt(minutes: int) -> str:
    h, m = divmod(max(0, minutes), 60)
    return f"{h % 24:02d}:{m:02d}"


WINDOW_START_MIN = to_min(WINDOW_START)
WINDOW_END_MIN = to_min(WINDOW_END)
WINDOW_MINUTES = WINDOW_END_MIN - WINDOW_START_MIN

# A gap smaller than this is conversational slack, not an unaccounted period.
MIN_GAP_MINUTES = 20


@dataclass
class Gap:
    start_min: int
    end_min: int

    @property
    def minutes(self) -> int:
        return self.end_min - self.start_min

    def describe(self) -> str:
        return f"{fmt(self.start_min)} to {fmt(self.end_min)} ({self.minutes} minutes) is unaccounted for"


@dataclass
class Overlap:
    a: Claim
    b: Claim

    def describe(self) -> str:
        return (f"'{self.a.text}' and '{self.b.text}' cover the same time "
                f"in different places")


@dataclass
class ImpossibleMove:
    a: Claim
    b: Claim
    needed: int
    available: int

    def describe(self) -> str:
        return (f"getting from {self.a.location} to {self.b.location} takes about "
                f"{self.needed} minutes, but only {self.available} were available")


@dataclass
class TimelineReport:
    blocks: List[Claim] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)
    overlaps: List[Overlap] = field(default_factory=list)
    impossible: List[ImpossibleMove] = field(default_factory=list)
    covered_minutes: int = 0

    @property
    def coverage(self) -> float:
        return self.covered_minutes / WINDOW_MINUTES if WINDOW_MINUTES else 0.0

    @property
    def complete(self) -> bool:
        """Is there enough of an account to be worth attacking?

        This is the gate for reverse chronology, anchoring and topic switching -
        all of which need something to have been committed to first. Deliberately
        forgiving: three blocks and half the window is an account, even a thin one.
        """
        return len(self.blocks) >= 3 and self.coverage >= 0.5

    @property
    def has_problems(self) -> bool:
        return bool(self.gaps or self.overlaps or self.impossible)

    def summary(self) -> str:
        if not self.blocks:
            return "No timeline given yet."
        parts = [f"Accounted for {int(self.coverage * 100)}% of 17:00-24:00."]
        for g in self.gaps:
            parts.append("GAP: " + g.describe())
        for o in self.overlaps:
            parts.append("CLASH: " + o.describe())
        for m in self.impossible:
            parts.append("IMPOSSIBLE: " + m.describe())
        return " ".join(parts)


def _clip(claim: Claim) -> Optional[tuple]:
    """Clamp a claim to the window, or drop it if it falls entirely outside."""
    start = max(claim.start_min, WINDOW_START_MIN)
    end = min(claim.end_min, WINDOW_END_MIN)
    return (start, end) if end > start else None


def build(claims: List[Claim]) -> TimelineReport:
    """Assemble the live claims into a timeline and find everything wrong with it."""
    report = TimelineReport()

    blocks = sorted(
        [c for c in claims if c.superseded_by is None and c.has_window],
        key=lambda c: c.start_min,
    )
    report.blocks = blocks
    if not blocks:
        return report

    # Coverage, merging overlapping spans so double-counting cannot inflate it.
    spans = []
    for c in blocks:
        clipped = _clip(c)
        if clipped:
            spans.append(clipped)
    merged: List[list] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    report.covered_minutes = sum(e - s for s, e in merged)

    # Gaps between the merged spans, plus the ends of the window.
    cursor = WINDOW_START_MIN
    for start, end in merged:
        if start - cursor >= MIN_GAP_MINUTES:
            report.gaps.append(Gap(cursor, start))
        cursor = max(cursor, end)
    if WINDOW_END_MIN - cursor >= MIN_GAP_MINUTES:
        report.gaps.append(Gap(cursor, WINDOW_END_MIN))

    # Two places at once.
    for i, a in enumerate(blocks):
        for b in blocks[i + 1:]:
            if b.start_min >= a.end_min:
                continue
            if a.location and b.location and a.location != b.location:
                report.overlaps.append(Overlap(a, b))

    # Journeys that could not have been made in the time claimed.
    for a, b in zip(blocks, blocks[1:]):
        if not (a.location and b.location) or a.location == b.location:
            continue
        origin = LOCATIONS.get(a.location)
        if not origin:
            continue
        needed = origin.walk_minutes.get(b.location)
        if needed is None:
            continue
        available = b.start_min - a.end_min
        if available < 0:
            continue                       # already reported as an overlap
        if available + 5 < needed:         # small grace for rounding in speech
            report.impossible.append(ImpossibleMove(a, b, needed, available))

    return report
