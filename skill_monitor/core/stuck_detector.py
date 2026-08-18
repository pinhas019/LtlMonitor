"""Pure predicate + debounce counter for nav_stuck, shared by every adapter that
surfaces the canonical mode/state/finished vocabulary (whether native, as on the real
robot's /path_manager/status, or translated from Nav2 via nav2_status_map.py in sim).
No ROS import, unit-testable.
"""

from __future__ import annotations

import math

_BLOCKED_STATES = frozenset({"no_traversable", "unreachable", "no_path_found"})


def is_blocked_state(state: str) -> bool:
    return state in _BLOCKED_STATES


def threshold_from_seconds(debounce_s: float, tick_hz: float) -> int:
    """A debounce duration in SECONDS -> the integer tick count that realises it.

    The descriptor declares a duration because a duration is what the operator means
    ("blocked for ten seconds"); the counter needs ticks. Resolving here, once, at
    load, is what stops the two drifting: the resolved integer is published in
    `AdapterSpec.manifest()`, so the "10+ consecutive ticks" prose in a spec can be
    read off the wire instead of being maintained by hand.

    Rounds UP -- a debounce must never fire earlier than declared -- and floors at one
    tick, since a debounce shorter than the tick period is still one observation.
    """
    if not debounce_s > 0:
        raise ValueError(f"debounce_s must be positive, got {debounce_s!r}")
    if not tick_hz > 0:
        raise ValueError(f"tick_hz must be positive, got {tick_hz!r}")
    # round() before ceil(): 1.1 * 10 is 11.000000000000002 in binary floating point,
    # and a bare ceil() would silently turn a declared 11 ticks into 12.
    return max(1, math.ceil(round(debounce_s * tick_hz, 9)))


class StuckStreak:
    """Counts consecutive blocked-state ticks; nav_stuck fires once >= threshold.

    A single self-recovering bad tick does not trigger nav_stuck -- the underlying
    state can flicker, and main.py evaluates conditions as instantaneous booleans
    every tick with no built-in debounce, so the debounce has to live here.
    """

    def __init__(self, threshold: int = 10):
        self.threshold = threshold
        self._count = 0

    def update(self, state: str) -> None:
        self._count = self._count + 1 if is_blocked_state(state) else 0

    @property
    def is_stuck(self) -> bool:
        return self._count >= self.threshold

    @property
    def count(self) -> int:
        return self._count
