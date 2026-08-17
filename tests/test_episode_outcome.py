"""Unit tests for episode_outcome — pure, no ROS. Run: python3 -m pytest test_episode_outcome.py"""

from skill_monitor.core.episode_outcome import classify_outcome, safety_fault_from_state


def _state(fault=None):
    if fault is None:
        return {}
    return {
        "named_failure_modes": [
            {"name": fault, "fault_category": "SAFETY", "status": "VIOLATED"}
        ]
    }


def test_reached_goal_is_success():
    o = classify_outcome("succeeded", None, False)
    assert o.terminal and o.success and o.cause == "reached_goal"


def test_safety_fault_dominates_even_if_succeeded():
    o = classify_outcome("succeeded", "fell_over", False)
    assert o.terminal and not o.success and o.cause == "fell_over"


def test_nav_aborted_is_failure():
    assert classify_outcome("aborted", None, False) == classify_outcome(
        "aborted", None, False
    )
    o = classify_outcome("aborted", None, False)
    assert o.terminal and not o.success and o.cause == "nav_failed"


def test_timeout_is_failure():
    o = classify_outcome("executing", None, True)
    assert o.terminal and not o.success and o.cause == "timeout"


def test_still_running_is_not_terminal():
    o = classify_outcome("executing", None, False)
    assert o.terminal is False


def test_safety_fault_from_state_reuses_supervisor_check():
    assert safety_fault_from_state(_state("collision_imminent")) == "collision_imminent"
    assert safety_fault_from_state(_state()) is None
