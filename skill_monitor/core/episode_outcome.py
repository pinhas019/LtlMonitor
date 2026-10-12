"""Pure episode-outcome classification for the G1 ablation — no ROS, unit-testable.

Combines the three terminal signals a nav episode produces into one outcome:
  - Nav2 action status (/navigate_to_pose/_action/status): succeeded | aborted | canceled
  - a monitor SAFETY fault (fell_over / collision_imminent), via the same VIOLATED-safety
    check the supervisor uses (reused from supervisor_logic)
  - a wall/step timeout

Success = Nav2 reached the goal AND the robot never fell or collided. A safety fault
dominates (a fall is a failure even if Nav2 later reports success).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from skill_monitor.core.supervisor_logic import decide_intervention

_NAV_FAIL = frozenset({"aborted", "canceled"})

#: action_msgs/GoalStatus codes, by the names classify_outcome reads.
NAV_STATUS_NAMES = {1: "accepted", 2: "executing", 3: "canceling",
                    4: "succeeded", 5: "canceled", 6: "aborted"}


class GoalStatusTracker:
    """The status of *this* episode's Nav2 goal, ignoring every goal from before it.

    Nav2's action status topic keeps finished goals in its list for a while, so reading
    the last entry -- as the runner used to -- can report the previous episode's
    `succeeded` the instant the next one starts, and end it before the robot moves.
    Goals are told apart by id: every id seen before `begin()` is ignored afterwards.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._ignored: set[str] = set()
        self.status = ""

    def begin(self) -> None:
        """Start a new episode: every goal seen so far belongs to an earlier one."""
        self._ignored = set(self._seen)
        self.status = ""

    def observe(self, entries: Iterable[tuple[str, int]]) -> None:
        """`entries`: (goal id, status code) pairs from one GoalStatusArray, in order."""
        fresh = []
        for goal_id, code in entries:
            self._seen.add(goal_id)
            if goal_id not in self._ignored:
                fresh.append(code)
        if fresh:
            self.status = NAV_STATUS_NAMES.get(fresh[-1], "")


@dataclass(frozen=True)
class Outcome:
    terminal: bool
    success: bool = False
    cause: str = ""


def safety_fault_from_state(state_desc: dict) -> str | None:
    """Name of the active VIOLATED safety failure mode, or None (reuses the supervisor check)."""
    return decide_intervention(state_desc).reason


def classify_outcome(
    nav_status: str, safety_fault: str | None, timed_out: bool
) -> Outcome:
    """Return a terminal Outcome, or Outcome(terminal=False) to keep the episode running."""
    if safety_fault:
        return Outcome(True, False, safety_fault)  # fell_over / collision — dominates
    if nav_status == "succeeded":
        return Outcome(True, True, "reached_goal")
    if nav_status in _NAV_FAIL:
        return Outcome(True, False, "nav_failed")
    if timed_out:
        return Outcome(True, False, "timeout")
    return Outcome(False)
