"""Unit tests for supervisor_logic — pure, no ROS. Run: python3 -m pytest test_supervisor_logic.py"""

from supervisor_logic import decide_intervention


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
