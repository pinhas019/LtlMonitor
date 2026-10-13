"""E1b's task executor, open loop and with the closed-loop checks, against a scripted world.

No physics: a fake simulator holds the object's position and the gripper, a fake navigator
arrives wherever it is sent on the next update. Perception is fed to `observe` by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e1" / "carry"))

from task import CarryExecutor, generate  # noqa: E402


class FakeSim:
    def __init__(self):
        self.time = 0.0
        self.holding = False
        self.obj = (0.0, 0.0, 0.08)
        self.robot = (0.0, 0.0)
        self.grasp_works = True

    def place_object(self, x, y):
        self.obj = (x, y, 0.08)

    def place_dropoff(self, x, y):
        pass

    def object_position(self):
        return self.obj

    def grasp(self):
        near = abs(self.obj[0] - self.robot[0]) + abs(self.obj[1] - self.robot[1]) < 0.6
        if self.grasp_works and near:
            self.holding = True
        return self.holding

    def release(self):
        if self.holding:
            self.holding = False
            self.obj = (self.robot[0] + 0.3, self.robot[1], 0.08)

    def drop(self):
        self.holding = False


class FakeNav:
    TRAVEL_S = 3.0

    def __init__(self):
        self.goal, self.status, self._arrive = None, "idle", 0.0
        self.max_speed, self.goals = 0.26, []

    def set_goal(self, x, y, t):
        self.goal, self.status, self._arrive = (x, y), "executing", t + self.TRAVEL_S
        self.goals.append((round(x, 3), round(y, 3)))

    def tick(self, sim, t):
        if self.status == "executing" and t >= self._arrive:
            self.status = "succeeded"
            sim.robot = self.goal


def world(family="clear", **kw):
    task = generate(family, 0)
    sim = FakeSim()
    sim.robot = (task["scenario"]["start"]["x"], task["scenario"]["start"]["y"])
    ex = CarryExecutor(sim, FakeNav(), task, **kw)
    return task, sim, ex


def run(ex, sim, task, until=60.0, dt=0.1, perceive=True):
    """Step the executor; the robot stands where the navigator was last sent, and sees the
    object (in its hand when held, else where it lies)."""
    t = 0.0
    while t < until and ex.status == "executing":
        t = round(t + dt, 3)
        sim.time = t
        ex.nav.tick(sim, t)
        ex.update(t)
        rx, ry = sim.robot
        if sim.holding:
            sim.obj = (rx + 0.3, ry, 0.7)
        if perceive:
            ex.observe(sim.obj, (rx, ry))
    return t


def test_open_loop_reports_success_after_a_failed_grasp():
    task, sim, ex = world("grasp_fail")
    run(ex, sim, task)
    assert ex.status == "succeeded" and not sim.holding
    assert ex.rechecks == []


def test_closed_loop_goes_back_after_a_failed_grasp():
    task, sim, ex = world("grasp_fail", closed_loop=True)
    run(ex, sim, task)
    assert ex.status == "succeeded"
    assert [r["reason"] for r in ex.rechecks][:1] == ["not holding the object while carrying"]
    assert ex._grasps == 2                                     # the retry took


def test_closed_loop_catches_a_skipped_pickup():
    task, sim, ex = world("skip_pickup", closed_loop=True)
    run(ex, sim, task)
    assert ex.rechecks and ex.rechecks[0]["t"] < 1.0           # within a few detections
    assert ex.rechecks[0]["reason"] == "not holding the object while carrying"
    assert ex.status == "succeeded" and ex._grasps == 1


def test_closed_loop_on_a_clean_run_never_rechecks():
    task, sim, ex = world("clear", closed_loop=True)
    run(ex, sim, task)
    assert ex.status == "succeeded" and ex.rechecks == []


def test_missed_detections_alone_never_trigger_a_check():
    task, sim, ex = world("skip_pickup", closed_loop=True)
    run(ex, sim, task, until=5.0, perceive=False)
    assert ex.rechecks == []


def test_rechecks_are_bounded():
    task, sim, ex = world("clear", closed_loop=True, max_rechecks=2)
    sim.grasp_works = False                                    # it never takes
    run(ex, sim, task, until=120.0)
    assert len(ex.rechecks) == 2
    assert ex.status == "succeeded"                            # then open loop again


@pytest.mark.parametrize("family", ["clear", "drop", "grasp_fail", "skip_pickup"])
def test_closed_loop_never_reports_success_while_holding(family):
    task, sim, ex = world(family, closed_loop=True)
    run(ex, sim, task)
    assert not (ex.status == "succeeded" and sim.holding)


# ------------------------------------------------------- faults no check was written for

from task import UNANTICIPATED  # noqa: E402


@pytest.mark.parametrize("family", UNANTICIPATED)
def test_unanticipated_families_are_deterministic_per_seed(family):
    assert generate(family, 3) == generate(family, 3)
    assert generate(family, 3) != generate(family, 4)


def test_wrong_dropoff_fools_the_closed_loop_check():
    task, sim, ex = world("wrong_dropoff", closed_loop=True)
    run(ex, sim, task)
    believed = tuple(task["task_faults"][0]["believed"])
    assert ex.status == "succeeded" and ex.rechecks == []       # its own check passes...
    ox, oy, _ = sim.obj
    tx, ty = task["dropoff"]
    assert ((ox - tx) ** 2 + (oy - ty) ** 2) ** 0.5 > 1.0       # ...far from the commanded one
    assert ex.nav.goals[-1] == believed


def test_detour_goes_via_the_waypoint_then_on_to_the_dropoff():
    task, sim, ex = world("detour", closed_loop=True)
    run(ex, sim, task)
    via = tuple(task["task_faults"][0]["via"])
    goals = ex.nav.goals
    assert via in goals and goals.index(via) < goals.index(tuple(task["dropoff"]))
    assert ex.status == "succeeded" and ex.rechecks == []


def test_slow_nav_cuts_the_speed_once_at_its_onset():
    task = generate("slow_nav", 0)
    f = task["task_faults"][0]
    f["onset_s"] = 1.0                       # the fake world finishes in ~10 s
    sim = FakeSim()
    ex = CarryExecutor(sim, FakeNav(), task)
    run(ex, sim, task, until=30.0)
    assert ex.nav.max_speed == pytest.approx(0.26 * f["factor"])
    assert [e["type"] for e in ex.fired] == ["slow_nav"]
