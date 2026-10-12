"""`goal_active`, `closing_speed`, `no_progress` -- progress measured from odometry against
the commanded goal, never from the planner (docs/packages/P12).

Before these, the only progress signals were the planner's own: `moving_towards_target`
and `nav_stuck` both read Nav2/TRAV status, so a robot whose legs gave out while the planner
still said "following" violated nothing. Driven here through the shipped MuJoCo descriptor
and `SensorState.tick()`, exactly as the evaluator folds them.
"""

from __future__ import annotations

from types import SimpleNamespace as _ns

import pytest

from skill_monitor.core import adapter_spec


def _odom(x, y=0.0):
    return _ns(pose=_ns(pose=_ns(position=_ns(x=x, y=y, z=0.78),
                                 orientation=_ns(x=0.0, y=0.0, z=0.0, w=1.0))),
               twist=_ns(twist=_ns(linear=_ns(x=0.0, y=0.0, z=0.0),
                                   angular=_ns(x=0.0, y=0.0, z=0.0))))


def _goal(x, y=0.0):
    return _ns(pose=_ns(position=_ns(x=x, y=y, z=0.0)))


@pytest.fixture
def state():
    return adapter_spec.SensorState(adapter_spec.load("mujoco"))


def tick_at(state, x, *, goal=None):
    """One tick: the robot at `x` (and optionally a goal message), then the fold."""
    state.update("odom", _odom(x))
    if goal is not None:
        state.update("goal", _goal(goal))
    return state.tick()


def test_every_descriptor_derives_the_progress_keys():
    for name in adapter_spec.available():
        keys = adapter_spec.load(name).keys()
        assert {"goal_active", "closing_speed", "no_progress"} <= keys, name


def test_closing_speed_is_the_drop_in_distance_per_second(state):
    tick_at(state, 0.0, goal=5.0)
    values = tick_at(state, 0.5)
    assert values["goal_active"] is True
    assert values["dist_to_goal"] == pytest.approx(4.5)
    assert values["closing_speed"] == pytest.approx(0.5)
    assert tick_at(state, 0.3)["closing_speed"] == pytest.approx(-0.2), "moving away"


def test_a_stall_far_from_the_goal_becomes_no_progress_after_the_debounce(state):
    tick_at(state, 0.0, goal=5.0)
    for x in (0.5, 1.0, 1.5):
        assert tick_at(state, x)["no_progress"] is False
    threshold = 10                              # debounce_s 10 at the default 1 Hz
    stalled = [tick_at(state, 1.5)["no_progress"] for _ in range(threshold)]
    assert stalled == [False] * (threshold - 1) + [True], "fires on the 10th stalled tick"
    assert tick_at(state, 2.0)["no_progress"] is False, "progress resumes, the streak clears"


def test_standing_still_at_the_goal_is_arrival_not_a_stall(state):
    tick_at(state, 0.0, goal=1.0)
    tick_at(state, 0.7)                         # 0.3 m away: inside the arrival radius
    assert not any(tick_at(state, 0.7)["no_progress"] for _ in range(20))


def test_without_a_goal_standing_still_is_not_a_stall(state):
    """Before any goal arrives, dist_to_goal is the distance to the odometry origin --
    the trap the schema doc warns about. `goal_active` is what closes it."""
    values = [tick_at(state, 3.0) for _ in range(15)]
    assert values[-1]["goal_active"] is False
    assert not any(v["no_progress"] for v in values)


def test_reset_clears_the_rate_and_the_streak_for_the_next_episode(state):
    tick_at(state, 0.0, goal=5.0)
    for _ in range(9):
        tick_at(state, 1.0)                     # nine stalled ticks banked
    state.reset()
    values = tick_at(state, 1.0, goal=5.0)
    assert values["goal_active"] is True and values["closing_speed"] == 0.0
    assert tick_at(state, 1.0)["no_progress"] is False, "the old streak carried over"


@pytest.mark.parametrize("tick_hz", [1.0, 4.0])
def test_the_rate_is_per_second_at_any_tick_rate(tick_hz):
    step = adapter_spec.Step({"key": "closing_speed", "fn": "rate_of_decrease",
                              "on": "tick", "inputs": ["dist_to_goal"]}, "goal",
                             tick_hz=tick_hz)
    assert step.fn(4.0) == 0.0
    assert step.fn(3.5) == pytest.approx(0.5 * tick_hz)


def test_the_debounce_is_published_as_ticks(state):
    schema = adapter_spec.load("mujoco").manifest()["schema"]
    assert schema["no_progress"]["debounce_ticks"] == 10


def test_a_descriptor_cannot_restate_the_tick_rate_by_hand():
    with pytest.raises(ValueError, match="tick_hz"):
        adapter_spec.Step({"key": "closing_speed", "fn": "rate_of_decrease", "on": "tick",
                           "inputs": ["dist_to_goal"], "args": {"tick_hz": 5}}, "goal")
