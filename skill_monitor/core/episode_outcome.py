"""Pure episode-outcome classification for the G1 ablation — no ROS, unit-testable.

Combines the three terminal signals a nav episode produces into one outcome:
  - Nav2 action status (/navigate_to_pose/_action/status): succeeded | aborted | canceled
  - a monitor SAFETY fault (fell_over / collision_imminent), via the same VIOLATED-safety
    check the supervisor uses (reused from supervisor_logic)
  - a wall/step timeout

Success = Nav2 reached the goal AND the robot never fell or collided. A safety fault
dominates (a fall is a failure even if Nav2 later reports success).

`decide_step` is the ablation's version, and differs in one way that matters: the
outcome is judged from ground truth -- the simulator's own record of a fall and of the
true distance to the goal -- and never from the monitor. The arms of an ablation differ
only in the monitor's specification, so an outcome read off the monitor's verdict would
let the arm under test grade itself. The monitor decides only what the *policy* does:
nothing (`off`), end the episode (`detect`), or re-plan (`recover`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from skill_monitor.core import episode_record, manifest
from skill_monitor.core.monitor_action import Action
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


# =============================================================================
# The ablation's per-step decision
# =============================================================================

POLICIES = episode_record.POLICIES

#: The robot counts as arrived within this true distance of the goal. Wider than Nav2's
#: 0.25 m tolerance, so a robot Nav2 rightly calls arrived is never failed for sway --
#: and narrow enough that odometry drift Nav2 cannot see still fails the episode.
ARRIVAL_RADIUS_M = 0.5


def intervention_from_verdict(verdict: dict | None) -> str | None:
    """What the monitor is asking to be done about, or None if nothing.

    An intervention is a token at REPLAN or above -- the rungs that change the plan or
    stop the robot -- or a `terminal: FAILURE`, which is how a stall reaches the
    verdict (the phase machine's terminal_failure, not a graded failure mode). WARN and
    SLOW are not: a policy that re-planned on every warning would be measuring
    something else. The name is the breached mode, by the same precedence the token was
    graded with (`manifest.breached_mode`), else the token's category.
    """
    verdict = verdict or {}
    intervention = verdict.get("intervention") or {}
    try:
        acts = Action[str(intervention.get("action", "CONTINUE"))] >= Action.REPLAN
    except KeyError:
        acts = False
    failed = verdict.get("terminal") == "FAILURE"
    if not (acts or failed):
        return None
    breached = manifest.breached_mode(verdict.get("failure_modes") or [])
    return ((breached or {}).get("name") or (intervention.get("category") if acts else None)
            or "terminal_failure")


@dataclass(frozen=True)
class Decision:
    action: str                     # "continue" | "end" | "recover"
    outcome: Outcome = Outcome(False)


CONTINUE = Decision("continue")


def decide_step(*, policy: str, nav_status: str, intervention: str | None,
                fell: bool, dist_to_goal: float | None, timed_out: bool,
                recoveries: int, max_recoveries: int) -> Decision:
    """One step of an ablation episode.

    In order: a fall ends it under every policy; then the policy acts on an
    intervention; then Nav2's own ending, checked against the true distance; then the
    clock. `dist_to_goal` None means no ground truth is available, and Nav2's word is
    taken for arrival -- the real robot's case, not the simulator's.
    """
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}, got {policy!r}")
    if fell:
        return Decision("end", Outcome(True, False, "fell"))
    if intervention and policy != "off":
        if policy == "recover" and recoveries < max_recoveries:
            return Decision("recover")
        return Decision("end", Outcome(True, False, f"monitor:{intervention}"))
    if nav_status == "succeeded":
        if dist_to_goal is None or dist_to_goal <= ARRIVAL_RADIUS_M:
            return Decision("end", Outcome(True, True, "reached_goal"))
        return Decision("end", Outcome(True, False, "false_arrival"))
    if nav_status in _NAV_FAIL:
        return Decision("end", Outcome(True, False, "nav_failed"))
    if timed_out:
        return Decision("end", Outcome(True, False, "timeout"))
    return CONTINUE
