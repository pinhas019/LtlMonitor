"""Unit tests for supervisor_logic — pure, no ROS. Run: python3 -m pytest test_supervisor_logic.py"""

from skill_monitor.core.monitor_action import Action
from skill_monitor.core.supervisor_logic import decide_intervention


def _fm(name, category, status):
    return {"name": name, "fault_category": category, "status": status}


def test_no_failure_modes_no_halt():
    assert decide_intervention({}).halt is False
    assert decide_intervention({"named_failure_modes": []}).halt is False


def test_violated_safety_fault_halts():
    state = {"named_failure_modes": [_fm("fell_over", "SAFETY", "VIOLATED")]}
    d = decide_intervention(state)
    assert d.halt is True and d.reason == "fell_over" and d.category == "SAFETY"


def test_collision_safety_halts():
    state = {"named_failure_modes": [_fm("collision_imminent", "SAFETY", "VIOLATED")]}
    assert decide_intervention(state).halt is True


def test_non_safety_violation_does_not_halt():
    # a PROGRESS/DEADLOCK fault is not a hard-stop safety fault
    state = {"named_failure_modes": [_fm("stall", "PROGRESS", "VIOLATED")]}
    assert decide_intervention(state).halt is False


def test_safety_mode_not_yet_violated_does_not_halt():
    state = {"named_failure_modes": [_fm("fell_over", "SAFETY", "INCONCLUSIVE")]}
    assert decide_intervention(state).halt is False


def test_first_violated_safety_wins():
    state = {
        "named_failure_modes": [
            _fm("fell_over", "SAFETY", "INCONCLUSIVE"),
            _fm("collision_imminent", "SAFETY", "VIOLATED"),
        ]
    }
    assert decide_intervention(state).reason == "collision_imminent"


def test_violated_safety_action_is_hard_stop():
    state = {"named_failure_modes": [_fm("fell_over", "SAFETY", "VIOLATED")]}
    d = decide_intervention(state)
    assert d.halt is True and d.action is Action.ABORT  # already breached => abort


def test_risk_block_replans_before_timeout():
    # No breach yet; predictive risk block warns of an imminent, confident timeout.
    state = {
        "risk": {
            "severity": "TIMEOUT",
            "steps_to_timeout": 2,
            "trigger_confidence": 0.9,
            "warn": True,
        }
    }
    d = decide_intervention(state)
    assert d.halt is False and d.action is Action.REPLAN and d.category == "TIMEOUT"


def test_risk_block_low_confidence_only_warns():
    state = {
        "risk": {
            "severity": "TIMEOUT",
            "steps_to_timeout": 2,
            "trigger_confidence": 0.2,
        }
    }
    d = decide_intervention(state)
    assert d.halt is False and d.action is Action.WARN


def test_violated_mode_takes_priority_over_risk():
    state = {
        "named_failure_modes": [_fm("fell_over", "SAFETY", "VIOLATED")],
        "risk": {
            "severity": "TIMEOUT",
            "steps_to_timeout": 2,
            "trigger_confidence": 0.9,
        },
    }
    assert decide_intervention(state).action is Action.ABORT
