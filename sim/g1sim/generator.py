"""Procedural scenarios: `generate(family, seed)` -> a validated Scenario, the same one for
the same arguments on every machine.

    python sim/generate_scenarios.py --family weaken --seeds 0-19 --out sim/scenarios/generated

A family fixes *what* happens; the seed varies *where* and *when*: the start pose, the
goal 3-6 m away, the clutter, and -- for a fault family -- the fault's onset and
parameters. So twenty seeds of one family are twenty different worlds with the same kind
of trouble in them, not one world replayed twenty times.

Families: `clear` (no obstacles, no fault), `cluttered` (obstacles, no fault), and one
per fault type in `fault_spec.FAULTS`. Fault ranges follow the measurements behind the
defaults there: `weaken` and `slip` are drawn from the range that actually brings the
robot down or stops it, so a fault episode is a fault and not a near miss.

Pure Python, like `scenario.py`: the Nav2 image generates maps from these.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from . import fault_spec
from .scenario import CLEARANCE_M, Obstacle, Scenario, from_dict

MAP_SIZE_M = 10.0
#: Start and goal stay this far inside the walls.
ARENA_HALF_M = 3.5
ROUTE_M = (3.0, 6.0)
#: A spawning fault needs room ahead of the robot for the box.
SPAWN_ROUTE_M = (4.0, 6.0)
ONSET_S = (2.0, 10.0)
#: A box must appear before the robot can reach it: at most 0.8 m/s for this long, so
#: it never materialises on top of the robot.
SPAWN_ONSET_S = (1.0, 2.0)
SPAWN_AHEAD_M = 2.2
DURATION_S = 60.0

FAMILIES = ("clear", "cluttered", *fault_spec.FAULTS)


def _fault_params(kind: str, rng: random.Random) -> dict:
    """Randomised params for everything but a spawned box's placement."""
    if kind == "push":
        return {"force_n": round(rng.uniform(250.0, 400.0), 1),
                "angle": round(rng.choice((1, -1)) * math.pi / 2, 4),
                "duration_s": 0.3}
    if kind == "slip":
        return {"mu": round(rng.uniform(0.05, 0.12), 3)}
    if kind == "weaken":
        return {"scale": round(rng.uniform(0.3, 0.6), 3)}
    if kind == "stall":
        return {"scale": round(rng.uniform(0.0, 0.2), 3)}
    if kind == "odom_drift":
        return {"rate_m_s": round(rng.uniform(0.03, 0.1), 3),
                "angle": round(rng.uniform(-math.pi, math.pi), 4)}
    if kind == "scan_dropout":
        return {"duration_s": round(rng.uniform(5.0, 15.0), 2)}
    return {}


def _route(rng: random.Random, length_range) -> tuple[tuple, tuple]:
    """A start pose and a goal `length_range` metres away, both inside the arena."""
    while True:
        sx, sy = (rng.uniform(-ARENA_HALF_M, ARENA_HALF_M) for _ in range(2))
        heading = rng.uniform(-math.pi, math.pi)
        length = rng.uniform(*length_range)
        gx, gy = sx + length * math.cos(heading), sy + length * math.sin(heading)
        if abs(gx) <= ARENA_HALF_M and abs(gy) <= ARENA_HALF_M:
            # The robot starts roughly, not exactly, facing the goal: Nav2 turns it.
            yaw = heading + rng.uniform(-math.pi / 2, math.pi / 2)
            yaw = math.atan2(math.sin(yaw), math.cos(yaw))
            return (round(sx, 3), round(sy, 3), round(yaw, 4)), (round(gx, 3), round(gy, 3))


def _spawn(kind: str, start, goal, rng: random.Random) -> dict:
    """Where a spawned box goes: on the straight route, ahead of the robot."""
    sx, sy, _ = start
    gx, gy = goal
    length = math.hypot(gx - sx, gy - sy)
    heading = math.atan2(gy - sy, gx - sx)
    half = fault_spec.FAULTS[kind]["size"]
    # Ahead of the robot by SPAWN_AHEAD_M, and clear of the goal by CLEARANCE_M.
    far = length - CLEARANCE_M - math.hypot(half[0], half[1])
    along = rng.uniform(SPAWN_AHEAD_M, max(SPAWN_AHEAD_M, far))
    return {"pos": [round(sx + along * math.cos(heading), 3),
                    round(sy + along * math.sin(heading), 3)],
            "size": list(half), "yaw": round(heading, 4)}


def _footprint(params: dict) -> Obstacle:
    """The spawned box as an obstacle, for keeping the clutter out of its way."""
    x, y = params["pos"]
    r = math.hypot(params["size"][0], params["size"][1])
    return Obstacle("cylinder", x, y, (r, params["size"][2]))


def _clutter(rng: random.Random, count: int, keep_clear: list, avoid: list) -> list[dict]:
    """`count` small boxes and cylinders, none within CLEARANCE_M of `keep_clear` points
    or of the `avoid` obstacles."""
    placed: list[dict] = []
    obstacles: list[Obstacle] = list(avoid)
    for _ in range(200):
        if len(placed) == count:
            break
        x, y = (rng.uniform(-ARENA_HALF_M - 0.5, ARENA_HALF_M + 0.5) for _ in range(2))
        if rng.random() < 0.5:
            half = [round(rng.uniform(0.1, 0.3), 3) for _ in range(2)] + [0.5]
            raw = {"type": "box", "pos": [round(x, 3), round(y, 3)], "size": half}
            made = Obstacle("box", raw["pos"][0], raw["pos"][1], tuple(half))
        else:
            radius = round(rng.uniform(0.1, 0.25), 3)
            raw = {"type": "cylinder", "pos": [round(x, 3), round(y, 3)],
                   "radius": radius, "height": 1.0}
            made = Obstacle("cylinder", raw["pos"][0], raw["pos"][1], (radius, 0.5))
        if any(made.distance_to(px, py) < CLEARANCE_M + 0.1 for px, py in keep_clear):
            continue
        if any(math.hypot(made.x - o.x, made.y - o.y)
               < made.size[0] + o.size[0] + CLEARANCE_M for o in obstacles):
            continue
        placed.append(raw)
        obstacles.append(made)
    return placed


def generate(family: str, seed: int) -> Scenario:
    if family not in FAMILIES:
        raise ValueError(f"family must be one of {list(FAMILIES)}, got {family!r}")
    rng = random.Random(f"g1sim:{family}:{seed}")     # str seeds hash stably
    spawning = family in fault_spec.SPAWNING
    start, goal = _route(rng, SPAWN_ROUTE_M if spawning else ROUTE_M)

    faults, avoid = [], []
    if family in fault_spec.FAULTS:
        params = _fault_params(family, rng)
        onset = rng.uniform(*(SPAWN_ONSET_S if spawning else ONSET_S))
        if spawning:
            params = _spawn(family, start, goal, rng)
            avoid.append(_footprint(params))
        faults.append({"type": family, "onset_s": round(onset, 2), "params": params})

    count = {"clear": 0, "cluttered": rng.randint(2, 4)}.get(family, rng.randint(0, 2))
    obstacles = _clutter(rng, count, [start[:2], goal], avoid)

    return from_dict({
        "name": f"{family}_{seed:03d}", "seed": seed,
        "map_size": [MAP_SIZE_M, MAP_SIZE_M],
        "start": {"x": start[0], "y": start[1], "yaw": start[2]},
        "goals": [list(goal)], "obstacles": obstacles, "walls": True,
        "duration_s": DURATION_S, "faults": faults,
    })


def parse_seeds(text: str) -> list[int]:
    """'0-19' or '3' or '0-4,10,12-13' -> the seeds, in order."""
    seeds: list[int] = []
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        seeds.extend(range(int(lo), int(hi or lo) + 1))
    return seeds


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate procedural G1 scenarios.")
    parser.add_argument("--family", required=True, nargs="+", choices=FAMILIES)
    parser.add_argument("--seeds", default="0-19", help="e.g. 0-19 or 0-4,10")
    parser.add_argument("--out", required=True, help="directory for the .json files")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for family in args.family:
        for seed in parse_seeds(args.seeds):
            scenario = generate(family, seed)
            path = out / f"{scenario.name}.json"
            path.write_text(json.dumps(scenario.to_dict(), indent=2) + "\n",
                            encoding="utf-8")
            written += 1
    print(f"wrote {written} scenarios to {out}")
    return 0
