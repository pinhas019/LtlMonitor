"""The headless Nav2 stand-in: it plans around what the map and the scan know, follows
the plan, arrives within tolerance, and gives up the way Nav2's progress checker does."""

from __future__ import annotations

import math

import pytest

np = pytest.importorskip("numpy")

from g1sim import from_dict                                      # noqa: E402
from g1sim.navigator import Navigator, scan_points               # noqa: E402


def scenario(obstacles=()):
    return from_dict({"name": "n", "start": {"x": -3, "y": 0, "yaw": 0}, "goals": [[3, 0]],
                      "obstacles": list(obstacles)})


def clearance(path, ox, oy):
    return min(math.hypot(x - ox, y - oy) for x, y in path)


def test_a_clear_route_is_nearly_straight():
    nav = Navigator(scenario())
    path = nav.plan((-3, 0), (3, 0), 0.0)
    assert path[-1] == (3, 0)
    length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
    assert length < 6.3


def test_the_plan_goes_around_a_mapped_obstacle_with_the_robot_radius():
    box = {"type": "box", "pos": [0, 0], "size": [0.3, 0.6, 0.5]}
    nav = Navigator(scenario([box]))
    path = nav.plan((-3, 0), (3, 0), 0.0)
    # Every point keeps the box's footprint at least the robot radius away.
    worst = min(max(abs(x) - 0.3, 0) ** 2 + max(abs(y) - 0.6, 0) ** 2 for x, y in path)
    assert math.sqrt(worst) >= 0.3


def test_a_scanned_obstacle_the_map_does_not_have_is_avoided_then_forgotten():
    nav = Navigator(scenario())
    wall = np.array([[0.0, y] for y in np.arange(-1.5, 1.55, 0.05)])
    nav.set_goal(3, 0, 0.0)
    nav.update(0.0, (-3, 0, 0.0), wall)
    assert clearance(nav.path, 0.0, 0.0) > 1.4          # around the end of the wall
    assert nav.plan((-3, 0), (3, 0), 10.0) is not None
    assert clearance(nav.plan((-3, 0), (3, 0), 10.0), 0.0, 0.0) < 0.2   # memory expired


def test_arrival_within_tolerance_is_success():
    nav = Navigator(scenario())
    nav.set_goal(3, 0, 0.0)
    assert nav.update(0.0, (2.8, 0.0, 0.0)) == (0.0, 0.0)
    assert nav.status == "succeeded"


def test_no_progress_for_the_window_aborts_like_nav2s_progress_checker():
    nav = Navigator(scenario())
    nav.set_goal(3, 0, 0.0)
    for t in range(0, 32):
        nav.update(float(t), (-3.0, 0.0, 0.0))
    assert nav.status == "aborted"


def test_restart_resumes_an_aborted_goal():
    nav = Navigator(scenario())
    nav.set_goal(3, 0, 0.0)
    for t in range(0, 32):
        nav.update(float(t), (-3.0, 0.0, 0.0))
    nav.restart(40.0)
    assert nav.status == "executing"
    vx, _ = nav.update(40.0, (-3.0, 0.0, 0.0))
    assert vx > 0


def test_an_unreachable_goal_aborts_after_repeated_failures():
    walled = {"type": "box", "pos": [2, 0], "size": [0.2, 5.0, 0.5]}
    nav = Navigator(from_dict({"name": "n", "start": {"x": -3, "y": 0, "yaw": 0},
                               "goals": [[3.5, 0]], "obstacles": [walled]}))
    nav.set_goal(3.5, 0, 0.0)
    for t in range(6):
        nav.update(float(t), (-3.0, 0.0, 0.0))
    assert nav.status == "aborted"


def test_the_follower_turns_before_walking_when_facing_away():
    nav = Navigator(scenario())
    nav.set_goal(3, 0, 0.0)
    vx, wz = nav.update(0.0, (-3.0, 0.0, math.pi))
    assert vx == 0.0 and abs(wz) == pytest.approx(0.6)


def test_it_plans_from_the_reported_pose_so_drift_fools_it():
    """Arrival is judged where odometry says the robot is, as with Nav2."""
    nav = Navigator(scenario())
    nav.set_goal(3, 0, 0.0)
    nav.update(0.0, (3.1, 0.0, 0.0))                     # reported at the goal
    assert nav.status == "succeeded"


def test_scan_points_are_placed_in_the_world_frame():
    ranges = np.full(360, np.inf)
    ranges[180] = 2.0                                    # straight ahead in the base frame
    pts = scan_points(ranges, (1.0, 1.0, math.pi / 2))
    assert pts.shape == (1, 2)
    assert pts[0] == pytest.approx([1.0, 3.0], abs=1e-6)
