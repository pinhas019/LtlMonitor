"""A scenario: everything that differs between two episodes, as data.

Pure Python. The ROS bridge receives one as JSON on its reset topic, the episode runner
reads one from `sim/scenarios/`, the world builder turns it into geometry and
`occupancy.py` turns the same object into Nav2's map -- so the lidar and the planner can
no longer disagree about where an obstacle is.

    {
      "name": "clear", "seed": 0, "map_size": [10, 10],
      "start": {"x": 0, "y": 0, "yaw": 0},
      "goals": [[3, 0]],
      "obstacles": [{"type": "box", "pos": [1.5, 0.8], "size": [0.2, 0.2, 0.5]},
                    {"type": "cylinder", "pos": [2, -1], "radius": 0.15, "height": 1.0}],
      "walls": true, "duration_s": 120,
      "faults": []
    }

`size` is MuJoCo's: half-extents. Each fault is `{type, onset_s, params?}`, validated
here against the table in `fault_spec.py` and applied by `faults.py`, e.g.
`{"type": "weaken", "onset_s": 4.0, "params": {"scale": 0.4}}`.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import fault_spec

#: Keep the robot's footprint this far from any obstacle at start and at every goal.
CLEARANCE_M = 0.4

_KEYS = {"name", "seed", "map_size", "start", "goals", "obstacles", "walls",
         "duration_s", "faults"}


class ScenarioError(ValueError):
    """Every problem with a scenario, reported together."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("invalid scenario: " + "; ".join(problems))


@dataclass(frozen=True)
class Obstacle:
    kind: str                       # "box" | "cylinder"
    x: float
    y: float
    #: box: (half_x, half_y, half_z); cylinder: (radius, half_height)
    size: tuple[float, ...]

    @property
    def height(self) -> float:
        return 2.0 * self.size[-1]

    def distance_to(self, px: float, py: float) -> float:
        """Planar distance from a point to this obstacle's footprint (0 inside)."""
        if self.kind == "cylinder":
            return max(0.0, math.hypot(px - self.x, py - self.y) - self.size[0])
        dx = max(abs(px - self.x) - self.size[0], 0.0)
        dy = max(abs(py - self.y) - self.size[1], 0.0)
        return math.hypot(dx, dy)

    def to_dict(self) -> dict:
        if self.kind == "cylinder":
            return {"type": "cylinder", "pos": [self.x, self.y],
                    "radius": self.size[0], "height": self.height}
        return {"type": "box", "pos": [self.x, self.y], "size": list(self.size)}


@dataclass(frozen=True)
class Scenario:
    name: str
    seed: int = 0
    map_size: tuple[float, float] = (10.0, 10.0)
    start: tuple[float, float, float] = (0.0, 0.0, 0.0)          # x, y, yaw
    goals: tuple[tuple[float, float], ...] = ((3.0, 0.0),)
    obstacles: tuple[Obstacle, ...] = ()
    walls: bool = True
    duration_s: float = 120.0
    faults: tuple[dict, ...] = field(default=())

    def layout_key(self) -> tuple:
        """What forces a model rebuild. Start, goals, seed and faults do not."""
        return (self.map_size, self.obstacles, self.walls)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "seed": self.seed, "map_size": list(self.map_size),
            "start": {"x": self.start[0], "y": self.start[1], "yaw": self.start[2]},
            "goals": [list(g) for g in self.goals],
            "obstacles": [o.to_dict() for o in self.obstacles],
            "walls": self.walls, "duration_s": self.duration_s,
            "faults": [dict(f) for f in self.faults],
        }


def _num(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _xy(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(map(_num, value))


def _obstacle(raw: Any, where: str, problems: list[str]) -> Obstacle | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: must be an object")
        return None
    kind = raw.get("type")
    if not _xy(raw.get("pos")):
        problems.append(f"{where}: pos must be [x, y]")
        return None
    x, y = (float(v) for v in raw["pos"])
    if kind == "box":
        size = raw.get("size")
        if not (isinstance(size, (list, tuple)) and len(size) == 3
                and all(_num(s) and s > 0 for s in size)):
            problems.append(f"{where}: box size must be three positive half-extents")
            return None
        return Obstacle("box", x, y, tuple(float(s) for s in size))
    if kind == "cylinder":
        radius, height = raw.get("radius"), raw.get("height")
        if not (_num(radius) and radius > 0 and _num(height) and height > 0):
            problems.append(f"{where}: cylinder needs positive radius and height")
            return None
        return Obstacle("cylinder", x, y, (float(radius), float(height) / 2.0))
    problems.append(f"{where}: type must be 'box' or 'cylinder', got {kind!r}")
    return None


def from_dict(raw: Any) -> Scenario:
    """A validated Scenario, or ScenarioError listing every problem at once."""
    if not isinstance(raw, dict):
        raise ScenarioError([f"scenario must be an object, got {type(raw).__name__}"])
    problems: list[str] = []
    for key in sorted(set(raw) - _KEYS):
        problems.append(f"unknown key {key!r}")

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        problems.append("name must be a non-empty string")
    seed = raw.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        problems.append("seed must be an integer")

    map_size = raw.get("map_size", [10.0, 10.0])
    if not (_xy(map_size) and all(s > 0 for s in map_size)):
        problems.append("map_size must be two positive numbers")
        map_size = [10.0, 10.0]
    half_x, half_y = map_size[0] / 2.0, map_size[1] / 2.0

    def inside(px: float, py: float) -> bool:
        return abs(px) < half_x and abs(py) < half_y

    start_raw = raw.get("start", {"x": 0.0, "y": 0.0, "yaw": 0.0})
    start = (0.0, 0.0, 0.0)
    if not (isinstance(start_raw, dict) and set(start_raw) <= {"x", "y", "yaw"}
            and all(_num(start_raw.get(k, 0.0)) for k in ("x", "y", "yaw"))):
        problems.append("start must be {x, y, yaw} numbers")
    else:
        start = tuple(float(start_raw.get(k, 0.0)) for k in ("x", "y", "yaw"))
        if not inside(start[0], start[1]):
            problems.append("start lies outside the map")

    goals_raw = raw.get("goals", [[3.0, 0.0]])
    goals: list[tuple[float, float]] = []
    if not isinstance(goals_raw, list) or not goals_raw:
        problems.append("goals must be a non-empty list of [x, y]")
    else:
        for i, goal in enumerate(goals_raw):
            if not _xy(goal):
                problems.append(f"goals[{i}] must be [x, y]")
            elif not inside(*goal):
                problems.append(f"goals[{i}] lies outside the map")
            else:
                goals.append((float(goal[0]), float(goal[1])))

    obstacles_raw = raw.get("obstacles", [])
    obstacles: list[Obstacle] = []
    if not isinstance(obstacles_raw, list):
        problems.append("obstacles must be a list")
    else:
        for i, item in enumerate(obstacles_raw):
            made = _obstacle(item, f"obstacles[{i}]", problems)
            if made is not None:
                obstacles.append(made)

    walls = raw.get("walls", True)
    if not isinstance(walls, bool):
        problems.append("walls must be a boolean")
    duration = raw.get("duration_s", 120.0)
    if not (_num(duration) and duration > 0):
        problems.append("duration_s must be a positive number")

    faults = raw.get("faults", [])
    if not isinstance(faults, list):
        problems.append("faults must be a list")
        faults = []
    for i, fault in enumerate(faults):
        problems.extend(fault_spec.validate(fault, f"faults[{i}]"))
    spawning = sum(isinstance(f, dict) and f.get("type") in fault_spec.SPAWNING
                   for f in faults)
    if spawning > fault_spec.SPARE_BODIES:
        problems.append(f"at most {fault_spec.SPARE_BODIES} faults may spawn a box "
                        f"({', '.join(fault_spec.SPAWNING)}), got {spawning}")
    for i, fault in enumerate(faults):
        params = fault.get("params") if isinstance(fault, dict) else None
        if isinstance(params, dict) and _xy(params.get("pos")) \
                and not inside(*params["pos"]):
            problems.append(f"faults[{i}]: pos lies outside the map")

    for label, (px, py) in [("start", start[:2]),
                            *((f"goals[{i}]", g) for i, g in enumerate(goals))]:
        for j, obstacle in enumerate(obstacles):
            if obstacle.distance_to(px, py) < CLEARANCE_M:
                problems.append(f"{label} is within {CLEARANCE_M} m of obstacles[{j}]")

    if problems:
        raise ScenarioError(problems)
    return Scenario(
        name=name, seed=seed, map_size=(float(map_size[0]), float(map_size[1])),
        start=start, goals=tuple(goals), obstacles=tuple(obstacles), walls=walls,
        duration_s=float(duration), faults=tuple(dict(f) for f in faults),
    )


def load(path: str | Path) -> Scenario:
    return from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
