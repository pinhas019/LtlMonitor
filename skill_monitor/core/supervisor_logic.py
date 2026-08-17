"""Pure intervention decision for the G1 safety supervisor — no ROS, unit-testable.

Reads the monitor's ``/ltl/state_description`` payload (see main.py: it carries
``named_failure_modes`` = [{name, fault_category, status, ...}] and an optional ``risk``
block = {severity, steps_to_timeout, violations_to_fault, trigger_confidence, warn}) and
maps it to a graded action (see monitor_action.grade_action):

- A VIOLATED failure mode is an already-breached fault (imminence 0); safety modes are
  preferred and grade to HALT/ABORT.
- Otherwise the predictive ``risk`` block drives a *pre-emptive* rung (WARN/SLOW/REPLAN)
  before the hard fault. ``halt`` stays True only for actions at HALT or above, so the
  existing "VIOLATED safety ⇒ halt" contract is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass

from skill_monitor.core.monitor_action import Action, grade_action

SAFETY_CATEGORIES = frozenset({"SAFETY", "INVARIANT"})


@dataclass(frozen=True)
class Intervention:
    halt: bool
    reason: str | None = None
    category: str | None = None
    action: Action = Action.CONTINUE


def decide_intervention(
    state_desc: dict,
    safety_categories=SAFETY_CATEGORIES,
    *,
    min_confidence: float = 0.5,
    warn_steps: int = 3,
) -> Intervention:
    """Grade the monitor state into an action; halt iff the action is HALT or above."""
    modes = state_desc.get("named_failure_modes") or []

    # A VIOLATED failure mode = an already-breached fault (imminence 0). Prefer safety.
    violated = next(
        (
            fm
            for fm in modes
            if fm.get("status") == "VIOLATED"
            and fm.get("fault_category") in safety_categories
        ),
        None,
    ) or next((fm for fm in modes if fm.get("status") == "VIOLATED"), None)

    if violated:
        action = grade_action(
            violated.get("fault_category"),
            imminence=0,
            confidence=float(violated.get("confidence", 1.0)),
            min_confidence=min_confidence,
            warn_steps=warn_steps,
        )
        return Intervention(
            halt=action >= Action.HALT,
            reason=violated.get("name"),
            category=violated.get("fault_category"),
            action=action,
        )

    # No breach yet — pre-emptive grading from the predictive risk block (engine.last_risk).
    risk = state_desc.get("risk") or {}
    if risk.get("severity"):
        imminence = risk.get("steps_to_timeout")
        if imminence is None:
            imminence = risk.get("violations_to_fault")
        action = grade_action(
            risk["severity"],
            imminence=imminence,
            confidence=float(risk.get("trigger_confidence", 1.0)),
            min_confidence=min_confidence,
            warn_steps=warn_steps,
        )
        return Intervention(
            halt=action >= Action.HALT,
            reason=risk["severity"],
            category=risk["severity"],
            action=action,
        )

    return Intervention(halt=False, action=Action.CONTINUE)
