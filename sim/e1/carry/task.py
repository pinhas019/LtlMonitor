"""E1b's skill: walk to an object, pick it up, carry it to a drop-off station, put it down.

    task = generate("drop", seed=3)                 # deterministic per (family, seed)
    ex = CarryExecutor(sim, nav, task)
    ex.update(t)                                    # every control period
    ex.status                                       # executing | succeeded | aborted
    ex.replan(t)                                    # what the runner's `recover` does

The executor is deliberately **open-loop**, as a plain behaviour tree is: it plans from what
it perceived when it planned, runs grasp and release as actions that "return", and reports
success when its sequence finishes. It never checks that the grasp took or that the object
is still in the gripper -- that gap is exactly what a runtime monitor is for. `replan()`
re-perceives: if the object is held it carries on to the drop-off, otherwise it goes to
wherever the object is now.

Task faults (the monitor's propositions must catch them; the executor will not):
  grasp_fail    the first grasp does not take (the object slips from the fingers)
  drop          the object falls `after_s` seconds into the first carry
  skip_pickup   the first plan skips the pick-up: straight to the drop-off, empty-handed
  object_moved  at `onset_s` the object is moved elsewhere before the robot reaches it
plus the simulator's `stall` and `push`, at a random moment of the task.

The legs-only G1 has no arm: a grasp attaches the object if the pelvis is within
`GRASP_REACH_M` of it (sim.G1Sim.grasp). The monitor never sees that attachment: it sees
the object only through `perceive_object`, and infers "held" from where the object is.
"""

from __future__ import annotations

import math
import random
from collections import deque

FAMILIES = ("clear", "cluttered", "grasp_fail", "drop", "skip_pickup", "object_moved",
            "stall", "push")
ARENA = 3.4
DURATION_S = 150.0
DWELL_S = 2.0                   # standing still for a grasp or a release

#: The perception stand-in: what an object detector would report. Not a camera -- the
#: simulator's object position with per-axis noise and missed detections -- but the
#: monitor gets nothing else about the object: no gripper flag, no executor state.
PERCEPTION_NOISE_M = 0.02
PERCEPTION_MISS = 0.05

#: The closed-loop executor's own "is it held" rule -- the same one the evaluator's
#: `object_held` extractor applies, on the same perception.
HELD_LIFT_MIN_M = 0.3
HELD_REACH_M = 0.5
CHECK_WINDOW = 3                # consecutive detections a check needs
DELIVERED_M = 0.5
MAX_RECHECKS = 4


def perceive_object(sim, rng, *, noise_m: float = PERCEPTION_NOISE_M,
                    miss: float = PERCEPTION_MISS):
    """(x, y, z) of the object as a detector would see it, or None for a missed frame."""
    if miss and rng.random() < miss:
        return None
    x, y, z = sim.object_position()
    if noise_m:
        x, y, z = (v + rng.gauss(0.0, noise_m) for v in (x, y, z))
    return x, y, z


def _point(rng, near=None, lo=0.0, hi=0.0):
    while True:
        if near is None:
            p = (rng.uniform(-ARENA, ARENA), rng.uniform(-ARENA, ARENA))
        else:
            a = rng.uniform(-math.pi, math.pi)
            r = rng.uniform(lo, hi)
            p = (near[0] + r * math.cos(a), near[1] + r * math.sin(a))
        if abs(p[0]) <= ARENA and abs(p[1]) <= ARENA:
            return round(p[0], 3), round(p[1], 3)


def generate(family: str, seed: int) -> dict:
    if family not in FAMILIES:
        raise ValueError(f"family must be one of {FAMILIES}")
    rng = random.Random(f"carry:{family}:{seed}")
    start = _point(rng)
    obj = _point(rng, start, 2.5, 4.0)
    while True:
        drop = _point(rng, obj, 2.5, 4.0)
        if math.dist(drop, start) > 1.0:
            break
    yaw = round(rng.uniform(-math.pi, math.pi), 4)

    faults, task_faults = [], []
    if family == "grasp_fail":
        task_faults.append({"type": "grasp_fail", "onset_s": 0.0})
    elif family == "drop":
        task_faults.append({"type": "drop", "onset_s": 0.0,
                            "after_s": round(rng.uniform(1.0, 5.0), 2)})
    elif family == "skip_pickup":
        task_faults.append({"type": "skip_pickup", "onset_s": 0.0})
    elif family == "object_moved":
        task_faults.append({"type": "object_moved", "onset_s": round(rng.uniform(2.0, 6.0), 2),
                            "to": list(_point(rng, obj, 1.2, 2.0))})
    elif family == "stall":
        faults.append({"type": "stall", "onset_s": round(rng.uniform(5.0, 45.0), 2),
                       "params": {"scale": round(rng.uniform(0.0, 0.2), 3)}})
    elif family == "push":
        faults.append({"type": "push", "onset_s": round(rng.uniform(3.0, 45.0), 2),
                       "params": {"force_n": round(rng.uniform(250.0, 400.0), 1)}})

    obstacles = []
    if family == "cluttered":
        keep = [start, obj, drop] + [t["to"] for t in task_faults if "to" in t]
        for _ in range(200):
            if len(obstacles) == 3:
                break
            x, y = _point(rng)
            if all(math.dist((x, y), k) > 0.9 for k in keep) and \
                    all(math.dist((x, y), o["pos"]) > 1.0 for o in obstacles):
                obstacles.append({"type": "cylinder", "pos": [x, y], "radius": 0.18,
                                  "height": 1.0})

    return {
        "name": f"carry_{family}_{seed:03d}", "seed": seed,
        "scenario": {"name": f"carry_{family}_{seed:03d}", "seed": seed, "map_size": [10, 10],
                     "start": {"x": start[0], "y": start[1], "yaw": yaw},
                     "goals": [list(drop)], "obstacles": obstacles, "walls": True,
                     "duration_s": DURATION_S, "faults": faults},
        "object": list(obj), "dropoff": list(drop), "task_faults": task_faults,
        "duration_s": DURATION_S,
    }


class CarryExecutor:
    """The task sequence on top of the navigator: open loop by default.

    `closed_loop=True` is the engineering baseline E1b compares the monitor against: the
    checks a careful developer writes into a behaviour tree, reading the same perception
    the monitor gets (`observe`), with no monitor at all --
      * while carrying, if CHECK_WINDOW consecutive detections say the object is not held,
        go back for it (catches a failed grasp, a drop, a skipped pick-up);
      * after putting it down, report success only once a detection shows it at the
        drop-off and not held; otherwise go back for it.
    A check re-plans with `replan()`, the same re-perception the monitor-triggered
    recovery uses, at most `max_rechecks` times.
    """

    def __init__(self, sim, nav, task: dict, *, closed_loop: bool = False,
                 max_rechecks: int = MAX_RECHECKS):
        self.sim, self.nav, self.task = sim, nav, task
        self.closed_loop, self.max_rechecks = closed_loop, max_rechecks
        self.rechecks: list[dict] = []
        self._seen = deque(maxlen=CHECK_WINDOW)
        self.dropoff = tuple(task["dropoff"])
        self.status = "executing"
        self.fired: list[dict] = []
        self._faults = {f["type"]: f for f in task.get("task_faults", [])}
        self._grasps = 0
        self._carry_started = None
        self._dropped = False
        self._moved = False
        self.goal_changed = True
        sim.place_object(*task["object"])
        sim.place_dropoff(*self.dropoff)
        if "skip_pickup" in self._faults:
            self._fire("skip_pickup", 0.0)
            self._go("carry", self.dropoff, sim.time)
        else:
            self._go("to_object", task["object"], sim.time)

    def _fire(self, kind, t):
        self.fired.append({"type": kind, "t": round(t, 3)})

    def _go(self, state, target, t):
        self.state = state
        self.target = tuple(target)
        self.nav.set_goal(*self.target, t)
        self.goal_changed = True
        self._dwell_from = None
        self._seen.clear()                       # a check judges only what came after

    def observe(self, seen, pose) -> None:
        """One perception sample: `seen` = (x, y, z) of the object or None (missed), `pose`
        = the robot's (x, y) from odometry. Only the closed-loop checks read it."""
        if seen is None:
            return
        ox, oy, oz = seen
        held = oz >= HELD_LIFT_MIN_M and math.hypot(ox - pose[0], oy - pose[1]) <= HELD_REACH_M
        at_dropoff = math.hypot(ox - self.dropoff[0], oy - self.dropoff[1]) <= DELIVERED_M
        self._seen.append((held, at_dropoff))

    def _recheck(self, reason: str, t: float) -> bool:
        """Re-plan on a failed check, if any re-plans are left."""
        if len(self.rechecks) >= self.max_rechecks:
            return False
        self.rechecks.append({"reason": reason, "t": round(t, 3)})
        self.replan(t)
        return True

    def replan(self, t: float) -> None:
        """Re-perceive and re-plan: to the drop-off if the object is held, else to it."""
        self.status = "executing"
        if self.sim.holding:
            self._go("carry", self.dropoff, t)
        else:
            ox, oy, _ = self.sim.object_position()
            self._go("to_object", (ox, oy), t)

    def update(self, t: float) -> None:
        sim = self.sim
        f = self._faults
        if "object_moved" in f and not self._moved and t >= f["object_moved"]["onset_s"] \
                and not sim.holding:
            sim.place_object(*f["object_moved"]["to"])
            self._moved = True
            self._fire("object_moved", t)
        if "drop" in f and not self._dropped and self._carry_started is not None \
                and sim.holding and t - self._carry_started >= f["drop"]["after_s"]:
            sim.drop()
            self._dropped = True
            self._fire("drop", t)

        if self.status != "executing":
            return
        if self.nav.status == "aborted":
            self.status = "aborted"
            return
        full = len(self._seen) == CHECK_WINDOW
        if self.closed_loop and self.state == "carry" and full \
                and not any(held for held, _ in self._seen):
            if self._recheck("not holding the object while carrying", t):
                return
        if self.state in ("to_object", "carry") and self.nav.status == "succeeded":
            self.state = "grasp" if self.state == "to_object" else "place"
            self._dwell_from = t
        elif self.state == "grasp" and t - self._dwell_from >= DWELL_S:
            self._grasps += 1
            if "grasp_fail" in f and self._grasps == 1:
                self._fire("grasp_fail", t)
            else:
                sim.grasp()
            if sim.holding and self._carry_started is None:
                self._carry_started = t
            self._go("carry", self.dropoff, t)       # open loop: on to the drop-off
        elif self.state == "place" and t - self._dwell_from >= DWELL_S:
            sim.release()
            if self.closed_loop:
                self.state, self._dwell_from = "verify", t
                self._seen.clear()
            else:
                self.state = "done"
                self.status = "succeeded"            # the sequence finished
        elif self.state == "verify":
            if self._seen:
                held, at_dropoff = self._seen[-1]
                if at_dropoff and not held:
                    self.state, self.status = "done", "succeeded"
                elif not self._recheck("object not at the drop-off after placing", t):
                    self.state, self.status = "done", "succeeded"
            elif t - self._dwell_from >= DWELL_S:     # nothing seen: report as open loop
                self.state, self.status = "done", "succeeded"

    def command(self):
        """What the robot is told to do this period (stand still while dwelling)."""
        return self.state in ("grasp", "place", "verify", "done")
