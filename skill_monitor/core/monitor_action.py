"""Graded intervention ladder — pure, no ROS, actor-agnostic. Unit-testable.

The monitor emits a fault category (SAFETY / INVARIANT / TIMEOUT / PROGRESS), an
`imminence` (steps-to-violation; 0 = already violated, None = no timing risk) and a
`confidence` in the triggering signal. `grade_action` maps those to one rung of an
ordered ladder so a supervisor can respond proportionally instead of a single halt:

    CONTINUE < WARN < SLOW < REPLAN < HALT < ABORT

Ordered by how drastic the response is: re-planning (try another way) is softer than
HALT (stop the robot), so a supervisor can treat ``action >= HALT`` as "stop actuating".
Actuation stays actor-specific (MiniGrid re-plan vs G1 /cmd_vel halt); only the decision
lives here. Safety is the one thing never softened: a confident safety signal always
halts (or aborts if the breach already happened).
"""

from __future__ import annotations

from enum import IntEnum


class Action(IntEnum):
    CONTINUE = 0  # nothing to do
    WARN = 1  # log/flag only — signal is weak or not yet imminent
    SLOW = 2  # ease off (pre-emptive, recoverable stalling)
    REPLAN = (
        3  # the current plan won't make it — get a new one (does not stop the robot)
    )
    HALT = 4  # stop now to avoid an imminent safety breach
    ABORT = 5  # unrecoverable — stop and fail the mission


def grade_action(
    category: str | None,
    imminence: int | None = None,
    confidence: float = 1.0,
    *,
    min_confidence: float = 0.5,
    warn_steps: int = 3,
) -> Action:
    """Map (category, imminence, confidence) to a ladder rung.

    ``imminence``: steps until the fault (<=0 = already violated, None = no timing risk).
    ``confidence``: [0,1] certainty in the triggering signal; below ``min_confidence`` the
    response is de-escalated to WARN rather than actuating on a shaky verdict.
    """
    if not category:
        return Action.CONTINUE
    cat = str(category).upper()
    sure = confidence >= min_confidence
    imminent = imminence is not None and imminence <= warn_steps
    overdue = imminence is not None and imminence <= 0

    if cat in ("SAFETY", "INVARIANT"):
        if not sure:
            return Action.WARN
        return Action.ABORT if overdue else Action.HALT
    if cat == "TIMEOUT":
        if overdue:
            return Action.REPLAN
        if imminent:
            return Action.REPLAN if sure else Action.WARN
        return Action.CONTINUE
    if cat == "PROGRESS":
        if overdue:
            return (
                Action.REPLAN
            )  # confirmed stall: the plan isn't working, get a new one
        if imminent:
            return Action.SLOW if sure else Action.WARN
        return Action.CONTINUE
    # Unknown category: flag when a confident, imminent signal exists, else carry on.
    return Action.WARN if (imminent and sure) else Action.CONTINUE
