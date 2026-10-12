"""What a fault may be, as data. Pure Python, so a scenario validates anywhere -- the Nav2
image builds its map from scenarios and has neither numpy nor mujoco.

Defaults were chosen by measurement on the walking G1 (sim/README.md, "Faults"):
`weaken` below about 0.6 of nominal torque collapses the robot rather than slowing it,
so it is a collapse fault; friction must drop on the feet as well as the floor, because
MuJoCo combines a contact's friction as the max of the pair; and `stall` -- the legs no
longer execute the commanded velocity while the planner keeps commanding it -- is the
one fault the planner cannot see, which is exactly what sensor-grounded progress exists
to catch.
"""

from __future__ import annotations

import math

#: type -> default params. A param left out takes its default; `None` means required.
FAULTS: dict[str, dict] = {
    "push":         {"force_n": 300.0, "angle": math.pi / 2, "duration_s": 0.3},
    "slip":         {"mu": 0.1},
    "weaken":       {"scale": 0.5},
    "stall":        {"scale": 0.0},
    "obstacle":     {"pos": None, "size": [0.25, 0.25, 0.5], "yaw": 0.0},
    "block_route":  {"pos": None, "size": [0.15, 1.5, 0.5], "yaw": 0.0},
    "odom_drift":   {"rate_m_s": 0.05, "angle": 0.0},
    "scan_dropout": {"duration_s": None},
}

#: Faults that make a box appear, each using one of the world's spare bodies.
SPAWNING = ("obstacle", "block_route")
#: How many spare bodies the world carries, so at most this many spawning faults.
SPARE_BODIES = 2

#: Params that must be present even though the table above lists a key for them.
REQUIRED = {"obstacle": {"pos"}, "block_route": {"pos"}}
#: Params whose `None` default means "for the rest of the episode".
OPTIONAL_NONE = {"scan_dropout": {"duration_s"}}


def _num(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def resolved_params(fault: dict) -> dict:
    """The fault's params with every default filled in. Assumes `validate` passed."""
    return {**FAULTS[fault["type"]], **(fault.get("params") or {})}


def validate(fault, where: str = "fault") -> list[str]:
    """Problems with one `{type, onset_s, params?}` entry; empty means valid."""
    if not isinstance(fault, dict):
        return [f"{where}: must be an object"]
    problems = []
    kind = fault.get("type")
    if kind not in FAULTS:
        return [f"{where}: type must be one of {sorted(FAULTS)}, got {kind!r}"]
    for key in sorted(set(fault) - {"type", "onset_s", "params"}):
        problems.append(f"{where}: unknown key {key!r}")
    if not (_num(fault.get("onset_s")) and fault["onset_s"] >= 0):
        problems.append(f"{where}: onset_s must be a number >= 0")
    params = fault.get("params", {})
    if not isinstance(params, dict):
        return problems + [f"{where}: params must be an object"]
    for key in sorted(set(params) - set(FAULTS[kind])):
        problems.append(f"{where}: {kind} has no param {key!r}; "
                        f"known: {sorted(FAULTS[kind])}")
    for key in sorted(REQUIRED.get(kind, ())):
        if key not in params:
            problems.append(f"{where}: {kind} requires param {key!r}")

    merged = {**FAULTS[kind], **params}
    for key, value in merged.items():
        if key in params or value is not None:
            problems.extend(_check(kind, key, value, where))
    return problems


def _check(kind: str, key: str, value, where: str) -> list[str]:
    label = f"{where}: {kind}.{key}"
    if key == "pos":
        ok = isinstance(value, (list, tuple)) and len(value) == 2 and all(map(_num, value))
        return [] if ok else [f"{label} must be [x, y]"]
    if key == "size":
        ok = (isinstance(value, (list, tuple)) and len(value) == 3
              and all(_num(v) and v > 0 for v in value))
        return [] if ok else [f"{label} must be three positive half-extents"]
    if value is None and key in OPTIONAL_NONE.get(kind, ()):
        return []
    if not _num(value):
        return [f"{label} must be a number"]
    if key in ("force_n", "mu", "duration_s") and value <= 0:
        return [f"{label} must be > 0"]
    if key in ("rate_m_s",) and value < 0:
        return [f"{label} must be >= 0"]
    if key == "scale" and not 0.0 <= value <= 1.0:
        return [f"{label} must be within [0, 1]"]
    return []
