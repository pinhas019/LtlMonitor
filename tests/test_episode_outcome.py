"""Unit tests for episode_outcome — pure, no ROS. Run: python3 -m pytest test_episode_outcome.py"""

import pytest

from skill_monitor.core.episode_outcome import (
    ARRIVAL_RADIUS_M, POLICIES, classify_outcome, decide_step, intervention_from_verdict,
    safety_fault_from_state,
)


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


# =============================================================================
# decide_step: the ablation's per-step decision
# =============================================================================


def _step(**overrides):
    base = dict(policy="detect", nav_status="executing", intervention=None, fell=False,
                dist_to_goal=None, timed_out=False, recoveries=0, max_recoveries=2)
    return decide_step(**(base | overrides))


def test_nothing_happening_continues():
    assert _step().action == "continue"


@pytest.mark.parametrize("policy", POLICIES)
def test_a_fall_ends_the_episode_whatever_the_policy_and_whatever_nav2_says(policy):
    d = _step(policy=policy, fell=True, nav_status="succeeded", dist_to_goal=0.1,
              intervention="fell_over")
    assert (d.action, d.outcome.success, d.outcome.cause) == ("end", False, "fell")


def test_off_ignores_an_intervention():
    assert _step(policy="off", intervention="TIMEOUT").action == "continue"


def test_detect_stops_on_an_intervention_even_with_recoveries_left():
    d = _step(policy="detect", intervention="no_progress")
    assert (d.action, d.outcome.cause) == ("end", "monitor:no_progress")


def test_recover_replans_until_its_budget_is_spent():
    assert _step(policy="recover", intervention="x", recoveries=1).action == "recover"
    d = _step(policy="recover", intervention="x", recoveries=2)
    assert (d.action, d.outcome.cause) == ("end", "monitor:x")


def test_an_intervention_outranks_a_simultaneous_nav2_success():
    """The monitor acting on this tick is what the policy did; Nav2's report arriving
    on the same spin does not undo it."""
    assert _step(policy="detect", intervention="x", nav_status="succeeded").action == "end"
    assert _step(policy="detect", intervention="x",
                 nav_status="succeeded").outcome.cause == "monitor:x"


@pytest.mark.parametrize("dist,success,cause", [
    (None, True, "reached_goal"),                     # no ground truth: Nav2's word
    (ARRIVAL_RADIUS_M, True, "reached_goal"),
    (ARRIVAL_RADIUS_M + 0.01, False, "false_arrival"),
])
def test_nav2_success_is_checked_against_the_true_distance(dist, success, cause):
    d = _step(nav_status="succeeded", dist_to_goal=dist)
    assert (d.action, d.outcome.success, d.outcome.cause) == ("end", success, cause)


@pytest.mark.parametrize("status", ["aborted", "canceled"])
def test_nav2_giving_up_is_a_failure(status):
    assert _step(nav_status=status).outcome.cause == "nav_failed"


def test_the_clock_is_last():
    assert _step(timed_out=True).outcome.cause == "timeout"
    assert _step(timed_out=True, nav_status="succeeded").outcome.cause == "reached_goal"


def test_an_unknown_policy_is_refused():
    with pytest.raises(ValueError):
        _step(policy="panic")


@pytest.mark.parametrize("verdict,name", [
    ({}, None),
    (None, None),
    ({"intervention": {"action": "WARN", "category": "SAFETY"}}, None),
    ({"intervention": {"action": "SLOW", "category": "PROGRESS"}}, None),
    ({"intervention": {"action": "BOGUS"}}, None),
    ({"intervention": {"action": "REPLAN", "category": "TIMEOUT"}}, "TIMEOUT"),
    ({"intervention": {"action": "ABORT", "category": "SAFETY"},
      "failure_modes": [{"name": "fell_over", "fault_category": "SAFETY",
                         "status": "VIOLATED"}]}, "fell_over"),
    ({"terminal": "FAILURE", "intervention": {"action": "CONTINUE"}}, "terminal_failure"),
    ({"terminal": "SUCCESS", "intervention": {"action": "CONTINUE"}}, None),
])
def test_what_counts_as_an_intervention(verdict, name):
    assert intervention_from_verdict(verdict) == name
