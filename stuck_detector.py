"""Pure predicate + debounce counter for nav_stuck, shared by every adapter that
surfaces the canonical mode/state/finished vocabulary (whether native, as on the real
robot's /path_manager/status, or translated from Nav2 via nav2_status_map.py in sim).
No ROS import, unit-testable.
"""

from __future__ import annotations

_BLOCKED_STATES = frozenset({"no_traversable", "unreachable", "no_path_found"})


def is_blocked_state(state: str) -> bool:
    return state in _BLOCKED_STATES


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
