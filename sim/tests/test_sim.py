"""G1Sim under real physics: it stands, walks, turns, falls when pushed, and resets."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from g1sim import from_dict, load

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
REPO = Path(__file__).resolve().parents[2]


def _heading_progress(start, end, yaw):
    return (end[0] - start[0]) * math.cos(yaw) + (end[1] - start[1]) * math.sin(yaw)


@pytest.fixture
def clear(sim):
    scenario = load(SCENARIOS / "clear.json")
    sim.reset(scenario)
    return scenario


def test_after_reset_it_stands_at_the_start_pose(sim, clear):
    x, y, z, yaw = sim.base_pose()
    assert math.hypot(x - clear.start[0], y - clear.start[1]) < 0.2
    assert abs(yaw - clear.start[2]) < 0.2
    assert sim.upright() and sim.time == pytest.approx(0.0)


def test_with_no_command_it_stays_up_and_roughly_in_place(sim, clear):
    start = sim.base_position()
    sim.step(5.0)
    assert sim.upright()
    assert np.linalg.norm(sim.base_position()[:2] - start[:2]) < 0.5


def test_it_walks_forward_at_the_commanded_speed(sim, clear):
    start, yaw = sim.base_position(), sim.base_pose()[3]
    sim.set_command(0.5, 0.0, 0.0)
    sim.step(5.0)
    assert sim.upright()
    assert _heading_progress(start, sim.base_position(), yaw) > 1.5
    assert sim.linear_velocity_body()[0] == pytest.approx(0.5, abs=0.2)


def test_it_turns_at_the_commanded_rate(sim, clear):
    yaw0 = sim.base_pose()[3]
    sim.set_command(0.0, 0.0, 0.5)
    sim.step(4.0)
    turned = (sim.base_pose()[3] - yaw0 + math.pi) % (2 * math.pi) - math.pi
    assert sim.upright() and turned > 1.0


def test_a_hard_push_knocks_it_over_and_reset_stands_it_back_up(sim, clear):
    """The fall is real now: the old kinematic bridge pinned the height, so `upright`
    could never go false and `fell_over` could never fire."""
    sim.push([0.0, 300.0, 0.0], duration_s=0.3)
    sim.step(3.0)
    assert not sim.upright()
    assert sim.base_height() > 0.0, "the torso capsule must stop it sinking through the floor"

    sim.reset(clear)
    assert sim.upright()


def test_the_same_scenario_twice_gives_the_same_trajectory(sim, clear):
    def run():
        sim.reset(clear)
        sim.set_command(0.4, 0.0, 0.2)
        sim.step(3.0)
        return sim.data.qpos.copy()
    first = run()
    sim.set_command(0.8, 0.3, -0.5)          # pollute the state between runs
    sim.step(2.0)
    assert np.array_equal(run(), first), "reset left state behind (LSTM memory, forces)"


def test_commands_are_clipped_to_what_the_policy_can_follow(sim, clear):
    used = sim.set_command(5.0, -5.0, 9.0)
    assert np.allclose(used, [sim.command_limits[0], -sim.command_limits[1],
                              sim.command_limits[2]])
    assert np.allclose(sim.set_command(float("nan"), 0, 0), 0.0)


def test_a_reset_with_the_same_layout_reuses_the_model(sim, clear):
    model = sim.model
    sim.reset(from_dict({**clear.to_dict(), "start": {"x": 1.0, "y": 1.0, "yaw": 0.5}}))
    assert sim.model is model
    sim.reset(load(SCENARIOS / "box_in_path.json"))
    assert sim.model is not model


# =============================================================================
# The scan
# =============================================================================

def test_the_scan_sees_an_obstacle_ahead_and_never_the_robot(sim):
    scenario = from_dict({"name": "one_box", "walls": False, "goals": [[-3.0, 0.0]],
                          "obstacles": [{"type": "box", "pos": [1.5, 0.0],
                                         "size": [0.2, 0.5, 0.5]}]})
    sim.reset(scenario)
    ranges = sim.ranges()
    ahead = ranges[len(ranges) // 2]                 # angle 0 is the middle ray
    x = sim.base_position()[0]
    assert ahead == pytest.approx(1.5 - 0.2 - x, abs=0.05)
    behind = ranges[0]
    assert math.isinf(behind), "a ray with nothing in front of it must be inf"


def test_with_no_walls_or_obstacles_the_scan_is_empty(sim):
    sim.reset(from_dict({"name": "void", "walls": False, "goals": [[3.0, 0.0]]}))
    assert np.all(np.isinf(sim.ranges())), "the scan hit the robot or the floor"


def test_the_walls_are_where_the_map_says(sim):
    sim.reset(load(SCENARIOS / "clear.json"))
    x = sim.base_position()[0]
    assert sim.min_range() == pytest.approx(5.0 - 0.1 - abs(x), abs=0.3)


def test_upright_uses_the_monitors_thresholds():
    """The sim's notion of a fall and the monitor's must not drift apart."""
    from g1sim.sim import UPRIGHT_HEIGHT_MIN, UPRIGHT_TILT_MAX
    path = REPO / "skill_monitor/adapters/mujoco.json"
    if not path.is_file():
        pytest.skip("needs the repository checkout (the simulator image has no "
                    "skill_monitor/); runs from the repo root")
    descriptor = json.loads(path.read_text(encoding="utf-8"))
    steps = [step for src in descriptor["sources"] for step in src.get("steps", [])
             if step.get("fn") == "upright"]
    assert len(steps) == 1
    assert steps[0]["args"] == {"tilt_max": UPRIGHT_TILT_MAX,
                                "height_min": UPRIGHT_HEIGHT_MIN}
