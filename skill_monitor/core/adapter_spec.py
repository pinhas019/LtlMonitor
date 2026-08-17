"""An adapter as DATA: which topics a robot publishes, and how their fields become
sensor_eval keys. Pure -- no ROS -- so the whole mapping is unit-testable and the
generator (which runs on a host with no ROS) can read a robot's schema without
importing the module that subscribes to it.

A descriptor (skill_monitor/adapters/*.json) has:

    schema    "nav_schema.json" or an inline {key: {doc, default}} dict
    defaults  optional per-robot overrides of the schema defaults
    sources   one per topic: {id, topic, type, decode, qos, tracked, steps}
    describe  which keys to surface in the evaluator's console block

and each step turns one message into one or more sensor_eval keys:

    {"key": "linear_vel", "field": "twist.twist.linear.x", "round": 2}
    {"keys": ["base_roll","base_pitch"], "fn": "quat_to_roll_pitch",
     "field": "pose.pose.orientation"}
    {"key": "nav_stuck", "fn": "stuck_streak", "inputs": ["nav_state"],
     "args": {"threshold": 10}}

Field paths and `inputs` are the whole vocabulary for plumbing; anything that needs
real math (quaternions, point clouds, debounce) is a NAMED function in EXTRACTORS
below. That split is deliberate: making the JSON expressive enough to hold the math
would just be inventing a worse Python.

Arguments handed to `fn`: the values named by `inputs` if present, else the value at
`field`, else the whole decoded message. An extractor returning None leaves the keys
untouched -- that is how a Nav2 status array with no goals in it reports nothing
rather than reporting a wrong state.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import skill_monitor.core.g1_sensors as g1_sensors
from skill_monitor.core.g1_real_frame import remap_optical_to_body
from skill_monitor.core.nav2_status_map import nav2_status_to_state
from skill_monitor.core.stuck_detector import StuckStreak

ADAPTERS_DIR = Path(__file__).resolve().parent.parent / "adapters"

_MISSING = object()

#: Decoders are applied in the ROS layer (they need message-type specific APIs);
#: named here so a descriptor can be validated without ROS installed.
DECODERS = frozenset({"json", "pointcloud_xyz", "laserscan_ranges", "goal_status"})

CASTS = {"bool": bool, "int": int, "float": float, "str": str}


# ------------------------------------------------------------------ extractors

def _fn_quat_to_roll_pitch():
    def f(q):
        roll, pitch, _yaw = g1_sensors.quat_to_euler(
            _attr(q, "x"), _attr(q, "y"), _attr(q, "z"), _attr(q, "w"))
        return roll, pitch
    return f


def _fn_upright(tilt_max=0.5, height_min=0.5):
    return lambda roll, pitch, height: (
        1.0 if g1_sensors.base_upright(roll, pitch, height,
                                       tilt_max=tilt_max, height_min=height_min) else 0.0
    )


def _fn_min_range_points(z_lo=0.1, z_hi=1.5, default=10.0, frame="body"):
    def f(points):
        pts = remap_optical_to_body(points) if frame == "optical" else points
        return g1_sensors.min_range_from_points(pts, z_lo=z_lo, z_hi=z_hi, default=default)
    return f


def _fn_min_range_scan(default=10.0):
    def f(ranges):
        # inf/NaN/0.0 are LaserScan's "no return" encodings, not obstacles at 0 m.
        valid = [r for r in ranges if r > 0.0 and math.isfinite(r)]
        return min(valid) if valid else default
    return f


def _fn_stuck_streak(threshold=10):
    streak = StuckStreak(threshold=threshold)     # per-instance state, see AdapterSpec

    def f(state):
        streak.update(state)
        return streak.is_stuck
    f.streak = streak                              # exposed for describe()
    return f


def _fn_nav2_status():
    return lambda status: None if status is None else nav2_status_to_state(status)


def _fn_const(value=None):
    return lambda *_: value


def _fn_eq(to=None):
    return lambda v: v == to


EXTRACTORS = {
    "quat_to_roll_pitch": _fn_quat_to_roll_pitch,
    "upright": _fn_upright,
    "min_range_points": _fn_min_range_points,
    "min_range_scan": _fn_min_range_scan,
    "stuck_streak": _fn_stuck_streak,
    "nav2_status": _fn_nav2_status,
    "const": _fn_const,
    "eq": _fn_eq,
}


# ------------------------------------------------------------------- accessors

def _attr(obj, name):
    """One hop of a field path. Messages are objects, decoded JSON is a dict, and a
    descriptor should not have to care which."""
    if isinstance(obj, dict):
        return obj.get(name, _MISSING)
    return getattr(obj, name, _MISSING)


def _path(obj, dotted: str):
    for part in dotted.split("."):
        if obj is _MISSING or obj is None:
            return _MISSING
        obj = _attr(obj, part)
    return obj


# ----------------------------------------------------------------------- model

class Step:
    def __init__(self, raw: dict, source_id: str):
        self.source_id = source_id
        keys = raw.get("keys") or ([raw["key"]] if "key" in raw else [])
        if not keys:
            raise ValueError(f"{source_id}: step declares neither 'key' nor 'keys': {raw}")
        self.keys = tuple(keys)
        self.field = raw.get("field")
        self.inputs = tuple(raw.get("inputs") or ())
        self.round = raw.get("round")
        self.cast = raw.get("cast")
        self.default = raw.get("default", _MISSING)
        fn_name = raw.get("fn")
        if fn_name is not None and fn_name not in EXTRACTORS:
            raise ValueError(
                f"{source_id}: unknown extractor {fn_name!r}; "
                f"available: {sorted(EXTRACTORS)}")
        if self.cast is not None and self.cast not in CASTS:
            raise ValueError(f"{source_id}: unknown cast {self.cast!r}")
        if fn_name is None and len(self.keys) != 1:
            raise ValueError(f"{source_id}: a step with no 'fn' produces exactly one key")
        self.fn_name = fn_name
        self.fn = EXTRACTORS[fn_name](**(raw.get("args") or {})) if fn_name else None

    def apply(self, payload, values: dict) -> dict:
        """Values this step contributes, given a decoded message and the current
        sensor state. Empty when the field is absent and no default covers it."""
        if self.inputs:
            args = [values.get(k) for k in self.inputs]
        elif self.field is not None:
            v = _path(payload, self.field)
            if v is _MISSING:
                if self.default is _MISSING:
                    return {}
                v = self.default
            args = [v]
        else:
            args = [payload]

        out = self.fn(*args) if self.fn else args[0]
        if out is None:
            return {}
        vals = out if isinstance(out, tuple) else (out,)
        if len(vals) != len(self.keys):
            raise ValueError(
                f"{self.source_id}: {self.fn_name} returned {len(vals)} value(s) for "
                f"keys {list(self.keys)}")
        return {k: self._coerce(v) for k, v in zip(self.keys, vals)}

    def _coerce(self, v):
        if self.cast is not None:
            v = CASTS[self.cast](v)
        if self.round is not None and isinstance(v, float):
            v = round(v, self.round)
        return v


class Source:
    def __init__(self, raw: dict):
        self.id = raw["id"]
        self.topic = raw["topic"]
        self.type = raw["type"]
        self.decode = raw.get("decode")
        self.qos = raw.get("qos", 10)
        self.tracked = bool(raw.get("tracked", True))
        if self.decode is not None and self.decode not in DECODERS:
            raise ValueError(
                f"{self.id}: unknown decode {self.decode!r}; available: {sorted(DECODERS)}")
        self.steps = [Step(s, self.id) for s in raw.get("steps") or []]

    @property
    def keys(self) -> set:
        return {k for s in self.steps for k in s.keys}


class AdapterSpec:
    """A loaded descriptor. Holds the per-run state of its stateful extractors, so
    load it once per adapter instance rather than sharing one across robots."""

    def __init__(self, raw: dict, schema: dict):
        self.raw = raw
        self.name = raw.get("name", "adapter")
        self.doc = raw.get("doc", "")
        self.schema = schema                      # key -> {"doc":…, "default":…}
        self.sources = [Source(s) for s in raw.get("sources") or []]
        self.describe_keys = list(raw.get("describe") or [])
        self._defaults = {
            k: v.get("default") for k, v in schema.items()
        } | dict(raw.get("defaults") or {})
        self._validate()

    # -- introspection the rest of the system consumes ------------------------

    def keys(self) -> frozenset:
        return frozenset(self.schema)

    def docs(self) -> dict:
        """key -> prose. What the spec generator writes rules over, and what
        spec_contract validates generated rules against."""
        return {k: v.get("doc", "") for k, v in self.schema.items()}

    def defaults(self) -> dict:
        return dict(self._defaults)

    def manifest(self) -> dict:
        """The JSON this adapter announces on the wire. Everything a client needs to
        render or validate against it, with no import of this package."""
        return {
            "adapter": self.name,
            "doc": self.doc,
            "schema": {k: dict(v) for k, v in self.schema.items()},
            "sources": [
                {"id": s.id, "topic": s.topic, "type": s.type,
                 "tracked": s.tracked, "keys": sorted(s.keys)}
                for s in self.sources
            ],
        }

    def _validate(self):
        produced = set()
        for src in self.sources:
            for step in src.steps:
                unknown = set(step.keys) - set(self.schema)
                if unknown:
                    raise ValueError(
                        f"{self.name}/{src.id}: step writes {sorted(unknown)}, which the "
                        f"schema does not declare; declared: {sorted(self.schema)}")
                bad_inputs = set(step.inputs) - set(self.schema)
                if bad_inputs:
                    raise ValueError(
                        f"{self.name}/{src.id}: step reads {sorted(bad_inputs)}, which the "
                        f"schema does not declare")
                produced |= set(step.keys)
        missing_default = [
            k for k in set(self.schema) - produced
            if self._defaults.get(k) is None and k not in (self.raw.get("defaults") or {})
        ]
        if missing_default:
            raise ValueError(
                f"{self.name}: schema keys {sorted(missing_default)} are never produced by "
                f"any source and have no default -- they would read as None at runtime")


class SensorState:
    """Applies a descriptor's steps to incoming messages and holds the result.

    Nothing here knows about ROS: `update(source_id, payload)` takes an already
    decoded payload, which is exactly what makes the mapping testable with plain
    objects instead of a live graph.
    """

    def __init__(self, spec: AdapterSpec):
        self.spec = spec
        self.values = spec.defaults()
        self._by_id = {s.id: s for s in spec.sources}

    def update(self, source_id: str, payload) -> dict:
        src = self._by_id.get(source_id)
        if src is None:
            raise KeyError(f"unknown source {source_id!r}; have {sorted(self._by_id)}")
        for step in src.steps:
            self.values.update(step.apply(payload, self.values))
        return self.values

    def sensor_eval(self) -> dict:
        return dict(self.values)


# ------------------------------------------------------------------- loading

def load(name_or_path) -> AdapterSpec:
    """Load a descriptor by adapter name ('real_g1'), file name, or path."""
    path = Path(name_or_path)
    if not path.suffix:
        path = ADAPTERS_DIR / f"{name_or_path}.json"
    elif not path.is_absolute() and not path.exists():
        path = ADAPTERS_DIR / path.name
    if not path.exists():
        raise FileNotFoundError(
            f"no adapter descriptor {path.name!r} (have: {available()})")
    raw = json.loads(path.read_text())
    return from_dict(raw, base_dir=path.parent)


def from_dict(raw: dict, base_dir: Path = ADAPTERS_DIR) -> AdapterSpec:
    schema = raw.get("schema")
    if isinstance(schema, str):
        schema = json.loads((base_dir / schema).read_text())["keys"]
    if not isinstance(schema, dict) or not schema:
        raise ValueError(f"adapter {raw.get('name')!r} declares no schema")
    return AdapterSpec(raw, schema)


def available() -> list:
    return sorted(
        p.stem for p in ADAPTERS_DIR.glob("*.json") if not p.stem.endswith("_schema"))
