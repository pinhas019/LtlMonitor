"""Pure intervention decision for the G1 safety supervisor — no ROS, unit-testable.

Reads the monitor's ``/ltl/state_description`` payload (see main.py: it carries
``named_failure_modes`` = [{name, fault_category, status, ...}] where ``status`` is the
MonitorStatus name) and decides whether to intervene. A safety failure mode (e.g.
``fell_over``, ``collision_imminent``) whose G(...) formula is VIOLATED triggers a halt.
"""

from __future__ import annotations

from dataclasses import dataclass

SAFETY_CATEGORIES = frozenset({"SAFETY"})


@dataclass(frozen=True)
class Intervention:
    halt: bool
    reason: str | None = None
    category: str | None = None


def decide_intervention(
    state_desc: dict, safety_categories=SAFETY_CATEGORIES
) -> Intervention:
    """Halt on the first VIOLATED failure mode in a safety category; else no action."""
    for fm in state_desc.get("named_failure_modes") or []:
        if (
            fm.get("status") == "VIOLATED"
            and fm.get("fault_category") in safety_categories
        ):
            return Intervention(
                halt=True, reason=fm.get("name"), category=fm.get("fault_category")
            )
    return Intervention(halt=False)
