"""E1b's descriptor (sim/e1/carry/mujoco_carry.json): the monitor learns whether the object
is held only from where perception sees it, never from a gripper flag or the executor.

`object_held` is the inference; the guard below keeps the descriptor from growing a
subscription that would hand the monitor the answer instead.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as _ns

import pytest

from skill_monitor.core import adapter_spec
from test_planner_independence import ADMITTED, planner_sources

DESCRIPTOR = Path(__file__).resolve().parents[1] / "sim" / "e1" / "carry" / "mujoco_carry.json"

#: E1b's own inputs, on top of P12's: the commanded task and the object as a detector sees it.
CARRY_INPUTS = {"/task", "/object/pose"}


@pytest.fixture
def spec():
    return adapter_spec.load(str(DESCRIPTOR))


def test_reads_no_planner_executor_or_gripper_topic(spec):
    assert not planner_sources(spec)
    topics = {s.topic for s in spec.sources}
    assert not any("gripper" in t or t.startswith("/task/") for t in topics), topics
    assert topics <= ADMITTED | CARRY_INPUTS, topics - ADMITTED - CARRY_INPUTS


def _odom(x, y=0.0):
    return _ns(pose=_ns(pose=_ns(position=_ns(x=x, y=y, z=0.78),
                                 orientation=_ns(x=0.0, y=0.0, z=0.0, w=1.0))),
               twist=_ns(twist=_ns(linear=_ns(x=0.0, y=0.0, z=0.0),
                                   angular=_ns(x=0.0, y=0.0, z=0.0))))


def _seen(x, y, z):
    return _ns(point=_ns(x=x, y=y, z=z))


def held_after(state, robot_x, obj=None):
    state.update("odom", _odom(robot_x))
    if obj is not None:
        state.update("object", _seen(*obj))
    return state.tick()["holding"]


def test_holding_is_inferred_from_object_pose_and_odometry(spec):
    state = adapter_spec.SensorState(spec)
    assert held_after(state, 0.0, (0.3, 0.0, 0.08)) is False      # on the floor, in reach
    assert held_after(state, 0.0, (0.3, 0.0, 0.70)) is True       # lifted, in front
    assert held_after(state, 1.0, (1.3, -0.05, 0.69)) is True     # carried along
    assert held_after(state, 2.0, (1.6, 0.0, 0.08)) is False      # dropped behind


def test_lifted_far_away_is_not_held(spec):
    state = adapter_spec.SensorState(spec)
    assert held_after(state, 0.0, (2.0, 0.0, 0.70)) is False


def test_a_missed_detection_keeps_the_last_answer(spec):
    state = adapter_spec.SensorState(spec)
    assert held_after(state, 0.0, (0.3, 0.0, 0.70)) is True
    assert held_after(state, 0.1) is True                         # no /object/pose this tick


def test_object_held_extractor_edges():
    f = adapter_spec.EXTRACTORS["object_held"](reach=0.5, lift_min=0.3)
    assert f(0.0, 0.0, 0.5, 0.0, 0.3) is True                     # both bounds inclusive
    assert f(0.0, 0.0, 0.51, 0.0, 0.7) is False
    assert f(0.0, 0.0, 0.2, 0.0, 0.29) is False
    assert f(None, 0.0, 0.2, 0.0, 0.7) is None
