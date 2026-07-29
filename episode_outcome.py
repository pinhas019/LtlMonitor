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

from supervisor_logic import decide_intervention

_NAV_FAIL = frozenset({"aborted", "canceled"})


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
