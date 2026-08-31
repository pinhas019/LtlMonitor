"""An adapter as DATA: which topics a robot publishes, and how their fields become
sensor_eval keys. Pure -- no ROS -- so the whole mapping is unit-testable and the
generator (which runs on a host with no ROS) can read a robot's schema without
importing the module that subscribes to it.

A descriptor (skill_monitor/adapters/*.json) has:

    schema    a schema FRAGMENT, or a list of fragments composed left to right.
              A fragment is either a "*_schema.json" file name or an inline
              {key: {doc, default}} dict, so
                  "nav_schema.json"
                  {"gripper_closed": {"doc": "...", "default": false}}
                  ["pose_schema.json", "nav_schema.json"]
              are all legal and the first two mean exactly what they always did.
    defaults  optional per-robot overrides of the schema defaults
    tick_hz   the observation rate this descriptor is written for (default 1.0)
    sources   one per topic: {id, topic, type, decode, qos, tracked, required,
              expected_hz, max_age_s, steps}
    describe  which keys to surface in the evaluator's console block

and each step turns one message into one or more sensor_eval keys:

    {"key": "linear_vel", "field": "twist.twist.linear.x", "round": 2}
    {"keys": ["base_roll","base_pitch"], "fn": "quat_to_roll_pitch",
     "field": "pose.pose.orientation"}
    {"key": "min_range", "fn": "min_range_scan", "aggregate": "min"}
    {"key": "nav_stuck", "fn": "stuck_streak", "inputs": ["nav_state"],
     "on": "tick", "args": {"debounce_s": 10.0}}

Field paths and `inputs` are the whole vocabulary for plumbing; anything that needs
real math (quaternions, point clouds, debounce) is a NAMED function in EXTRACTORS
below. That split is deliberate: making the JSON expressive enough to hold the math
would just be inventing a worse Python.

Arguments handed to `fn`: the values named by `inputs` if present, else the value at
`field`, else the whole decoded message. An extractor returning None leaves the keys
untouched -- that is how a Nav2 status array with no goals in it reports nothing
rather than reporting a wrong state.

## Schema composition

A shared vocabulary across `real_g1`, `mujoco` and `isaac_lab` is what makes the
monitor EMBODIMENT-agnostic. One vocabulary that is entirely navigation's is what makes
it SKILL-specific: a manipulation skill would have to adopt `nav_stuck` and
`num_waypoints` before it could say anything at all. So a descriptor composes its
schema out of fragments instead of naming one file:

    "schema": ["pose_schema.json", "nav_schema.json"]

`pose_schema.json` -- where the robot is -- belongs to the EMBODIMENT and is what an
inspection or manipulation skill keeps when it drops the navigation fragment.

Fragments merge left to right and a later one wins on collision, which is what makes
"the standard fragment, with this one key retuned for my robot" expressible at all. A
collision that CHANGES a key's meaning -- a different `doc` or a different `default` --
is not silent: it is recorded in `warnings()` and so published in `manifest()`, beside
the other descriptor smells. It is a warning and not an error deliberately. Refusing to
load would make override useless, since an override that changes nothing is not an
override; but a fragment quietly redefining what `min_range` MEANS, or what value it
holds before any message arrives, is precisely the plausible-nonsense class this module
exists to catch, so it has to be visible on the wire rather than only in the diff. A
fragment that re-declares a key IDENTICALLY says nothing new and is passed over in
silence.

## The observation window

Messages arrive event-driven at each sensor's own rate; the trace must be a function
of the DATA, not of how fast messages happened to arrive. So `update()` does not write
the observation. It appends to a per-tick WINDOW, and `tick()` folds that window by
each key's declared `aggregate` policy into the held values. `sensor_eval()` is a pure
read of the held values and may be called any number of times between ticks.

Two live bugs are what this shape exists to kill, both documented in docs/clocking.md:

  * a debounce counted in MESSAGES rather than ticks silently scales with the topic's
    publish rate -- `on: "tick"` plus `debounce_s` fixes it in the descriptor's own
    vocabulary;
  * `last`-wins over a cloud published far faster than the tick discards almost every
    frame, so a transient obstacle is simply never seen -- `aggregate: "min"` fixes it.

Both capabilities ship here. No descriptor in skill_monitor/adapters/ uses them yet:
the navigation schema is being redesigned to stop depending on the planner's own
status stream, and the new schema is what will take them up.
"""

from __future__ import annotations

import json
import math
import threading
import warnings
from collections import ChainMap, Counter
from pathlib import Path

import skill_monitor
import skill_monitor.core.g1_sensors as g1_sensors
from skill_monitor.core.g1_real_frame import remap_optical_to_body
from skill_monitor.core.nav2_status_map import nav2_status_to_state
from skill_monitor.core.stuck_detector import StuckStreak, threshold_from_seconds

#: Retained module-level name -- anything importing `adapter_spec.ADAPTERS_DIR` keeps
#: working. Every lookup below calls `skill_monitor.adapters_dir()` instead, so a
#: /config volume mounted after import is still honoured; this constant is only the
#: packaged fallback and cannot track a later override.
ADAPTERS_DIR = skill_monitor.PACKAGED_ADAPTERS_DIR

_MISSING = object()

#: Decoders are applied in the ROS layer (they need message-type specific APIs);
#: named here so a descriptor can be validated without ROS installed.
DECODERS = frozenset({"json", "pointcloud_xyz", "laserscan_ranges", "goal_status"})

CASTS = {"bool": bool, "int": int, "float": float, "str": str}

#: When a step runs. `message` folds into the window; `tick` runs once per tick over
#: the values the fold just committed -- which is the difference between "blocked for
#: 10 s" and "blocked for 10 s, reported one tick late".
STEP_PHASES = frozenset({"message", "tick"})

DEFAULT_TICK_HZ = 1.0

#: Descriptor keys, listed so a typo raises instead of being silently ignored.
STEP_KEYS = frozenset({
    "key", "keys", "field", "inputs", "fn", "args", "round", "cast", "default",
    "aggregate", "q", "on",
})
SOURCE_KEYS = frozenset({
    "id", "topic", "type", "decode", "qos", "tracked", "required", "expected_hz",
    "max_age_s", "steps",
})
ADAPTER_KEYS = frozenset({
    "name", "doc", "schema", "defaults", "describe", "sources", "tick_hz",
})


# ----------------------------------------------------------------- aggregators

def _mean(xs):
    return sum(xs) / len(xs)


def _quantile(xs, q):
    """Linear-interpolated quantile. `q` is 0.0-1.0; 0.5 is the median."""
    ordered = sorted(xs)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


#: How several samples of one key inside one tick become the single value the trace
#: sees. `last` is the default and reproduces the pre-window behaviour exactly.
AGGREGATORS = {
    "last": lambda xs: xs[-1],
    "first": lambda xs: xs[0],
    "min": min,
    "max": max,
    "mean": _mean,
    "any": lambda xs: any(xs),
    "all": lambda xs: all(xs),
    "quantile": _quantile,
}

#: Aggregates that do arithmetic or ordering comparisons, and so are a load-time error
#: on a key the schema defaults to a str or a bool.
NUMERIC_AGGREGATES = frozenset({"min", "max", "mean", "quantile"})

DEFAULT_AGGREGATE = "last"


# ------------------------------------------------------------------ extractors

def _fn_quat_to_roll_pitch():
    def f(q):
        roll, pitch, _yaw = g1_sensors.quat_to_euler(
            _attr(q, "x"), _attr(q, "y"), _attr(q, "z"), _attr(q, "w"))
        return roll, pitch
    return f


def _fn_quat_to_yaw():
    """Heading about the odometry frame's Z axis, from an orientation quaternion.

    Separate from `quat_to_roll_pitch` rather than a third output of it: roll and pitch
    answer "is the robot still upright", yaw answers "which way is it facing", and the
    two live in different schema fragments now. A descriptor that wants only pose
    should not have to write the tilt keys to get a heading.
    """
    def f(q):
        _roll, _pitch, yaw = g1_sensors.quat_to_euler(
            _attr(q, "x"), _attr(q, "y"), _attr(q, "z"), _attr(q, "w"))
        return yaw
    return f


def _fn_planar_distance():
    """Straight-line distance between two points in the odometry GROUND PLANE, given as
    four already-folded keys: (x0, y0, x1, y1).

    Planar and not 3-D on purpose. The robot walks on a surface, so the z difference
    between it and a commanded goal point is the goal publisher's choice of height, not
    a distance the robot has to cover -- including it would make "arrived" depend on
    what altitude somebody stamped the waypoint at.

    Returns None -- which leaves the key holding its previous value -- if any input is
    None, so a descriptor whose goal keys are nullable does not turn a missing goal into
    a TypeError out of the middle of a tick.
    """
    def f(x0, y0, x1, y1):
        if any(v is None for v in (x0, y0, x1, y1)):
            return None
        return math.hypot(x1 - x0, y1 - y0)
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
    f.threshold = threshold                        # resolved; published in manifest()
    return f


def _fn_nav2_status():
    return lambda status: None if status is None else nav2_status_to_state(status)


def _fn_const(value=None):
    return lambda *_: value


def _fn_eq(to=None):
    return lambda v: v == to


EXTRACTORS = {
    "quat_to_roll_pitch": _fn_quat_to_roll_pitch,
    "quat_to_yaw": _fn_quat_to_yaw,
    "planar_distance": _fn_planar_distance,
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


def _int(value, label: str, minimum: int) -> int:
    """A plain integer, bools excluded because `True` is an int in Python and would
    otherwise silently mean 1 -- a debounce of one observation, or a rounding to one
    decimal place."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}, got {value!r}")
    return value


def _count(value, label: str) -> int:
    """A streak length: at least 1. Zero means "already satisfied before any sample"."""
    return _int(value, label, 1)


def _index(value, label: str) -> int:
    """A number of decimal places: at least 0."""
    return _int(value, label, 0)


def _positive(value, label: str) -> float:
    """`inf` is excluded as well as zero: a rate of infinity makes max_age_s zero, so
    every source is permanently late, and a bool is excluded because a JSON `true`
    would otherwise pass as 1."""
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or not value > 0):
        raise ValueError(f"{label} must be a positive, finite number, got {value!r}")
    return float(value)


# ----------------------------------------------------------------------- model

class Step:
    def __init__(self, raw: dict, source_id: str, tick_hz: float = DEFAULT_TICK_HZ):
        unknown = set(raw) - STEP_KEYS
        if unknown:
            # The highest-value rule of the set: {"agregate": "min"} used to be
            # accepted in silence, leaving the fold on its default and the bug live.
            raise ValueError(
                f"{source_id}: step has unknown key(s) {sorted(unknown)}; "
                f"allowed: {sorted(STEP_KEYS)}")

        self.source_id = source_id
        keys = raw.get("keys") or ([raw["key"]] if "key" in raw else [])
        if not keys:
            raise ValueError(f"{source_id}: step declares neither 'key' nor 'keys': {raw}")
        self.keys = tuple(keys)
        self.field = raw.get("field")
        self.inputs = tuple(raw.get("inputs") or ())
        self.round = raw.get("round")
        if self.round is not None:
            # `round(v, "2")` is a TypeError on the first message, in a callback, on
            # the robot -- not at load, where every other descriptor error surfaces.
            self.round = _index(self.round, f"{source_id}: step {list(keys)}: 'round'")
        self.cast = raw.get("cast")
        self.default = raw.get("default", _MISSING)

        self.on = raw.get("on", "message")
        if self.on not in STEP_PHASES:
            raise ValueError(
                f"{source_id}: step 'on' must be one of {sorted(STEP_PHASES)}, "
                f"got {self.on!r}")

        self.aggregate = raw.get("aggregate", DEFAULT_AGGREGATE)
        if self.aggregate not in AGGREGATORS:
            raise ValueError(
                f"{source_id}: unknown aggregate {self.aggregate!r} for "
                f"{list(self.keys)}; available: {sorted(AGGREGATORS)}")
        self.q = raw.get("q")
        if self.aggregate == "quantile" and self.q is None:
            raise ValueError(
                f"{source_id}: aggregate 'quantile' for {list(self.keys)} requires 'q' "
                f"(0.0-1.0)")
        if self.q is not None and self.aggregate != "quantile":
            raise ValueError(
                f"{source_id}: 'q' is only meaningful with aggregate 'quantile', "
                f"not {self.aggregate!r}")
        if self.q is not None:
            if (isinstance(self.q, bool) or not isinstance(self.q, (int, float))
                    or not math.isfinite(self.q)):
                raise ValueError(
                    f"{source_id}: 'q' must be a finite number between 0.0 and 1.0, "
                    f"got {self.q!r}")
            if not 0.0 <= self.q <= 1.0:
                raise ValueError(
                    f"{source_id}: 'q' must be between 0.0 and 1.0, got {self.q!r}")

        if self.on == "tick":
            # A tick-step has no message to read, so a field path is meaningless and
            # `inputs` is the only way it can say what it consumes.
            if self.field is not None:
                raise ValueError(
                    f"{source_id}: tick-step {list(self.keys)} declares 'field' "
                    f"{self.field!r}, but a tick-step has no message to read it from")
            if not self.inputs:
                raise ValueError(
                    f"{source_id}: tick-step {list(self.keys)} declares no 'inputs'; "
                    f"a tick-step reads the folded observation, so it must name what "
                    f"it consumes")
            if "aggregate" in raw:
                raise ValueError(
                    f"{source_id}: tick-step {list(self.keys)} declares "
                    f"aggregate {self.aggregate!r}, but a tick-step produces exactly one "
                    f"value per tick and is never windowed")

        args = dict(raw.get("args") or {})
        #: Whether the tick count below was DERIVED from a declared duration. A
        #: hand-written `args.threshold` counts whatever the step's phase counts --
        #: messages, on a message-step -- so it is not a tick count and must not be
        #: published as one. See AdapterSpec.resolved_thresholds().
        self.declares_debounce_s = "debounce_s" in args
        self.debounce_s = args.pop("debounce_s", None)
        if self.declares_debounce_s:
            if self.debounce_s is None:
                # `"debounce_s": null` used to fall through to the extractor's own
                # default of 10, in a file that raises on a misspelt "agregate".
                raise ValueError(
                    f"{source_id}: step {list(self.keys)} declares 'debounce_s': null; "
                    f"declare a duration in seconds or omit the key entirely")
            if "threshold" in args:
                raise ValueError(
                    f"{source_id}: step {list(self.keys)} declares both 'threshold' and "
                    f"'debounce_s'; declare the duration only -- the tick count is "
                    f"derived from tick_hz")
            if self.on != "tick":
                raise ValueError(
                    f"{source_id}: step {list(self.keys)} declares 'debounce_s' but runs "
                    f"on {self.on!r}; a debounce in seconds is only meaningful on "
                    f'\'on\': "tick", otherwise it counts messages and scales with the '
                    f"topic's publish rate")
            try:
                args["threshold"] = threshold_from_seconds(self.debounce_s, tick_hz)
            except ValueError as exc:
                raise ValueError(
                    f"{source_id}: step {list(self.keys)}: {exc}") from exc
        elif "threshold" in args:
            # The number all three shipped descriptors actually use. '10', True, 0,
            # -1, nan and None all loaded and then produced a debounce that never
            # fires, or one satisfied before any sample arrived.
            args["threshold"] = _count(
                args["threshold"], f"{source_id}: step {list(self.keys)}: args.threshold")
        #: The resolved tick count, when this step debounces. Published in manifest().
        self.threshold = args.get("threshold")

        fn_name = raw.get("fn")
        if fn_name is not None and fn_name not in EXTRACTORS:
            raise ValueError(
                f"{source_id}: unknown extractor {fn_name!r}; "
                f"available: {sorted(EXTRACTORS)}")
        if self.cast is not None and self.cast not in CASTS:
            raise ValueError(f"{source_id}: unknown cast {self.cast!r}")
        if fn_name is None and len(self.keys) != 1:
            raise ValueError(f"{source_id}: a step with no 'fn' produces exactly one key")
        if fn_name is None and args:
            raise ValueError(
                f"{source_id}: step {list(self.keys)} passes args {sorted(args)} but "
                f"declares no 'fn' to receive them")
        self.fn_name = fn_name
        try:
            self.fn = EXTRACTORS[fn_name](**args) if fn_name else None
        except TypeError as exc:
            # A misspelt kwarg -- `{"z_low": 0.1}` for `z_lo` -- reached the extractor
            # as a TypeError out of the loader, escaping the handling every other bad
            # descriptor gets, and silently left the real argument on its default.
            raise ValueError(
                f"{source_id}: extractor {fn_name!r} rejected args {sorted(args)}: "
                f"{exc}") from exc

    def fold(self, samples: list):
        """Collapse this tick's samples of one key into the single value the trace sees."""
        if self.aggregate == "quantile":
            return _quantile(samples, self.q)
        return AGGREGATORS[self.aggregate](samples)

    def apply(self, payload, values) -> dict:
        """Values this step contributes, given a decoded message and the current
        sensor state. Empty when the field is absent and no default covers it.

        `values` is a read-only mapping -- during a message it is a ChainMap whose
        front layer holds what earlier steps of the SAME message produced, so
        `upright_flag` sees this message's roll/pitch/height rather than last tick's.
        """
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

    def _stateful(self):
        """This step's mutable extractor state, or None. Only `stuck_streak` has any
        today; an extractor grows state by exposing an object with
        snapshot/restore/reset, and everything below keeps working."""
        return getattr(self.fn, "streak", None)

    def snapshot(self):                                   # noqa: D102 - see Step._stateful
        state = self._stateful()
        return None if state is None else state.snapshot()

    def restore(self, snapshot):
        state = self._stateful()
        if state is not None:
            state.restore(snapshot)

    def reset(self):
        """Clear this step's extractor state, if it has any. See AdapterSpec.reset()."""
        state = self._stateful()
        if state is not None:
            state.reset()

    def _coerce(self, v):
        if self.cast is not None:
            v = CASTS[self.cast](v)
        if self.round is not None and isinstance(v, float):
            v = round(v, self.round)
        return v


class Source:
    def __init__(self, raw: dict, tick_hz: float = DEFAULT_TICK_HZ):
        unknown = set(raw) - SOURCE_KEYS
        if unknown:
            raise ValueError(
                f"{raw.get('id', '<no id>')}: source has unknown key(s) "
                f"{sorted(unknown)}; allowed: {sorted(SOURCE_KEYS)}")
        self.id = raw["id"]
        self.topic = raw["topic"]
        self.type = raw["type"]
        self.decode = raw.get("decode")
        self.qos = raw.get("qos", 10)
        self.tracked = bool(raw.get("tracked", True))

        # -- data health, declared per source ---------------------------------
        # `required` is deliberately NOT `tracked`: tracked counts toward the
        # confidence scalar, required decides whether an AP over this source's keys
        # becomes UNKNOWN when it goes unhealthy. They diverge in practice (an
        # optional vision topic is untracked yet its key still feeds an AP), so it is
        # its own field -- defaulting to `tracked` only because that is what today's
        # descriptors mean when they say nothing.
        self.declares_expected_hz = "expected_hz" in raw
        self.expected_hz = (
            _positive(raw["expected_hz"], f"{self.id}: expected_hz")
            if self.declares_expected_hz else float(tick_hz)
        )
        self.required = bool(raw.get("required", self.tracked))
        self.declares_max_age_s = "max_age_s" in raw
        self.max_age_s = (
            _positive(raw["max_age_s"], f"{self.id}: max_age_s")
            if self.declares_max_age_s
            # Two publish periods, but never shorter than a tick: a source slower than
            # the tick would otherwise be permanently "late" by construction.
            else max(2.0 / self.expected_hz, 1.0 / tick_hz)
        )

        if self.decode is not None and self.decode not in DECODERS:
            raise ValueError(
                f"{self.id}: unknown decode {self.decode!r}; available: {sorted(DECODERS)}")
        self.steps = [Step(s, self.id, tick_hz) for s in raw.get("steps") or []]
        self.message_steps = [s for s in self.steps if s.on == "message"]
        self.tick_steps = [s for s in self.steps if s.on == "tick"]

    @property
    def keys(self) -> set:
        return {k for s in self.steps for k in s.keys}

    @property
    def windowed_keys(self) -> set:
        """Keys this source folds -- tick-step outputs are never windowed."""
        return {k for s in self.message_steps for k in s.keys}


class AdapterSpec:
    """A loaded descriptor. Holds the per-run state of its stateful extractors, so
    load it once per adapter instance rather than sharing one across robots."""

    def __init__(self, raw: dict, schema: dict, schema_warnings=()):
        #: Complaints raised while COMPOSING `schema` out of fragments, handed in
        #: because the merge happens in `from_dict()` before this object exists. They
        #: go in front of the descriptor's own warnings: a key that does not mean what
        #: the fragment says it means invalidates everything read off it downstream.
        self._schema_warnings = list(schema_warnings)
        unknown = set(raw) - ADAPTER_KEYS
        if unknown:
            raise ValueError(
                f"{raw.get('name', 'adapter')}: descriptor has unknown key(s) "
                f"{sorted(unknown)}; allowed: {sorted(ADAPTER_KEYS)}")
        self.raw = raw
        self.name = raw.get("name", "adapter")
        self.doc = raw.get("doc", "")
        self.declares_tick_hz = "tick_hz" in raw
        self.tick_hz = (
            _positive(raw["tick_hz"], f"{self.name}: tick_hz")
            if self.declares_tick_hz else DEFAULT_TICK_HZ
        )
        self.schema = schema                      # key -> {"doc":…, "default":…}
        self.sources = [Source(s, self.tick_hz) for s in raw.get("sources") or []]
        self.describe_keys = list(raw.get("describe") or [])
        self._defaults = {
            k: v.get("default") for k, v in schema.items()
        } | dict(raw.get("defaults") or {})
        self._validate()
        self._aggregate_by_key = self._build_aggregate_by_key()
        self._warnings = self._build_warnings()

    # -- introspection the rest of the system consumes ------------------------

    def keys(self) -> frozenset:
        return frozenset(self.schema)

    def docs(self) -> dict:
        """key -> prose. What the spec generator writes rules over, and what
        spec_contract validates generated rules against."""
        return {k: v.get("doc", "") for k, v in self.schema.items()}

    def defaults(self) -> dict:
        return dict(self._defaults)

    def aggregate_by_key(self) -> dict:
        """key -> the fold policy the tick applies to that key's samples."""
        return dict(self._aggregate_by_key)

    def tick_steps(self) -> list:
        """Steps that run once per tick, in declaration order, across all sources."""
        return [s for src in self.sources for s in src.tick_steps]

    def message_steps(self, source_id: str) -> list:
        return self._by_id()[source_id].message_steps

    def resolved_thresholds(self) -> dict:
        """key -> the integer TICK count a declared `debounce_s` resolved to.

        A hand-written `args.threshold` is deliberately not in here. It counts
        whatever its step's phase counts -- MESSAGES, on `on: "message"` -- so
        republishing it as a tick count announces a ten-tick debounce for a streak
        that ten messages inside one tick already trip. Every shipped descriptor
        still carries exactly that, which is why the gate is on the phase AND on the
        provenance rather than on the number being present.

        The runtime number is not hidden: `manifest()` puts it on the step, next to
        the `on` that gives it its unit.
        """
        return {
            k: step.threshold
            for src in self.sources for step in src.steps
            for k in step.keys
            if step.threshold is not None
            and step.on == "tick" and step.declares_debounce_s
        }

    def warnings(self) -> list:
        """Non-fatal descriptor smells, published in the manifest so they are visible
        on the wire rather than only in a log nobody reads."""
        return list(self._warnings)

    def _by_id(self) -> dict:
        return {s.id: s for s in self.sources}

    def _all_steps(self) -> list:
        return [step for src in self.sources for step in src.steps]

    def snapshot(self) -> list:
        """Every stateful extractor's state, in a stable order, so a tick that fails
        part-way can be undone. See SensorState.tick()."""
        return [step.snapshot() for step in self._all_steps()]

    def restore(self, snapshot: list) -> None:
        for step, state in zip(self._all_steps(), snapshot):
            step.restore(state)

    def reset(self):
        """Clear every stateful extractor this descriptor loaded.

        Debounce state lives in the extractor's closure, which belongs to the SPEC and
        not to a SensorState -- so two SensorStates over one AdapterSpec share one
        streak, and reloading the descriptor was the only way to clear it. There is an
        episode boundary in docs/clocking.md (`arm`/`reset` restarts `step`), and
        carrying the previous episode's nine blocked ticks across it fires nav_stuck on
        the first blocked observation of a fresh run: precisely the false positive the
        debounce exists to prevent. `SensorState.reset()` calls this.
        """
        for src in self.sources:
            for step in src.steps:
                step.reset()

    def manifest(self) -> dict:
        """The JSON this adapter announces on the wire, as the keyword arguments
        `core.api.build_adapter` takes -- so P3 publishes it with
        `api.build_adapter(**spec.manifest(), seq=…, t=…)` and the shape cannot drift
        from the wire contract.

        Resolved values only: a `debounce_s` declared in the descriptor appears here
        as `debounce_ticks` on the schema entry for the key it governs, so "10+
        consecutive ticks" can be read off the wire instead of being maintained by
        hand in a spec's prose. ONLY a duration-derived tick-step threshold appears
        there -- a hand-written `args.threshold` is published on the step instead,
        beside the `on` that says what it counts.
        """
        thresholds = self.resolved_thresholds()
        schema = {}
        for key, entry in self.schema.items():
            out = dict(entry)
            if key in thresholds:
                out["debounce_ticks"] = thresholds[key]
            schema[key] = out
        return {
            "adapter": self.name,
            "doc": self.doc,
            "tick_hz": self.tick_hz,
            "warnings": self.warnings(),
            "schema": schema,
            "sources": [
                {"id": s.id, "topic": s.topic, "type": s.type,
                 "expected_hz": s.expected_hz, "max_age_s": s.max_age_s,
                 "required": s.required, "tracked": s.tracked,
                 "keys": sorted(s.keys),
                 "steps": [
                     # Exactly the fields the wire contract declares for a step.
                     {"keys": list(step.keys),
                      # A tick-step is not windowed; it yields one value per tick,
                      # which is what `last` means for a reader folding samples.
                      "aggregate": step.aggregate if step.on == "message" else "last",
                      # The streak length this step actually counts, in units of
                      # `on`: ticks for a tick-step, MESSAGES for a message-step.
                      # null when the step does not debounce.
                      "threshold": step.threshold,
                      "on": step.on}
                     for step in s.steps
                 ]}
                for s in self.sources
            ],
        }

    # -- load-time validation -------------------------------------------------

    def _build_aggregate_by_key(self) -> dict:
        """key -> policy, refusing two sources that fold one key differently.

        Two policies for one key is not a merge conflict the runtime could resolve;
        it means the descriptor's author believed two incompatible things about what
        the number means.
        """
        policy: dict[str, str] = {}
        declared_by: dict[str, str] = {}
        for src in self.sources:
            for step in src.message_steps:
                for key in step.keys:
                    previous = policy.get(key)
                    if previous is not None and previous != step.aggregate:
                        raise ValueError(
                            f"{self.name}: key {key!r} is folded as {previous!r} by "
                            f"{declared_by[key]} and as {step.aggregate!r} by {src.id}; "
                            f"one key has exactly one fold policy")
                    policy[key] = step.aggregate
                    declared_by[key] = src.id
        return policy

    def _build_warnings(self) -> list:
        out = list(self._schema_warnings)
        unrated: dict[str, list] = {}      # source id -> its unrateable 'last' keys
        for src in self.sources:
            if not src.declares_expected_hz:
                out.append(
                    f"source {src.id!r} declares no expected_hz; assuming the tick rate "
                    f"({self.tick_hz} Hz), so its data-health report cannot detect a "
                    f"slow topic")
        for key, policy in sorted(self._aggregate_by_key.items()):
            if policy != "last":
                continue
            # Only measurements. `last` on a state-like value (a planner state string
            # or a bool) is not a bug, it is the right answer -- warning about those
            # trains people to ignore the warnings. An int default is still a
            # measurement: `isinstance(default, float)` alone silently exempted every
            # `"default": 0` key, which is most of them.
            default = self._defaults.get(key)
            if not isinstance(default, (int, float)) or isinstance(default, bool):
                continue
            for src in self.sources:
                if key not in src.windowed_keys:
                    continue
                if not src.declares_expected_hz:
                    unrated.setdefault(src.id, []).append(key)
                elif src.expected_hz > 2 * self.tick_hz:
                    out.append(
                        f"key {key!r} is folded with 'last' from {src.id!r} at "
                        f"{src.expected_hz} Hz against a {self.tick_hz} Hz tick: about "
                        f"{max(0, round(src.expected_hz / self.tick_hz) - 1)} of every "
                        f"{round(src.expected_hz / self.tick_hz)} samples are discarded, "
                        f"so a transient value can be missed entirely")

        # One line per SOURCE, not per key: the discarded-samples test above is the
        # thing that surfaces the transient-obstacle bug, and it can never fire on a
        # source whose expected_hz silently defaulted to the tick rate -- which is
        # exactly the descriptor that declares no rates at all, i.e. every descriptor
        # shipped today. Saying nothing there reports a clean bill of health for the
        # file the check exists to catch.
        for src in self.sources:
            keys = unrated.get(src.id)
            if keys:
                out.append(
                    f"measured key(s) {sorted(keys)} are folded with 'last' from "
                    f"{src.id!r}, which declares no expected_hz: the discarded-samples "
                    f"check cannot run for {src.id!r} at all, so a transient value may "
                    f"be being missed and nothing here can tell you. Declare "
                    f"expected_hz on {src.id!r}, or declare the fold")
        return out

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
                if step.on == "message":
                    # A message-step chained onto another source's key reads a value
                    # held from a different topic's cadence -- silently mixing two
                    # time bases. A TICK-step legitimately reads the whole folded
                    # observation, so the rule applies here only.
                    foreign = set(step.inputs) - src.keys
                    if foreign:
                        raise ValueError(
                            f"{self.name}/{src.id}: step {list(step.keys)} reads "
                            f"{sorted(foreign)}, produced by another source; a "
                            f"message-step may only chain on keys from its own source "
                            f"(use 'on': \"tick\" to read the folded observation)")
                for key in step.keys:
                    default = self._defaults.get(key)
                    if (step.aggregate in NUMERIC_AGGREGATES
                            and isinstance(default, (str, bool))):
                        raise ValueError(
                            f"{self.name}/{src.id}: key {key!r} defaults to "
                            f"{default!r} but is folded with the numeric aggregate "
                            f"{step.aggregate!r}")
                produced |= set(step.keys)
        missing_default = [
            k for k in set(self.schema) - produced
            if self._defaults.get(k) is None and k not in (self.raw.get("defaults") or {})
        ]
        if missing_default:
            raise ValueError(
                f"{self.name}: schema keys {sorted(missing_default)} are never produced by "
                f"any source and have no default -- they would read as None at runtime")
        self._validate_input_order()

    def _validate_input_order(self):
        """`inputs` must name values that are already computed when the step runs.

        Nothing else enforces this. Steps execute in declaration order -- message-steps
        within their source, then `tick_steps()`, which is source-order x step-order --
        so a consumer declared before its producer reads LAST TICK's value, silently,
        for the whole life of the descriptor. Swapping two `sources` entries, or
        putting `upright_flag` above `base_height`, currently loads without complaint
        and makes every derived value one tick stale.

        A step reading a key it also writes is allowed: that is an accumulator reading
        its own previous value, which is a real pattern and unambiguous. Only a
        STRICTLY LATER producer is an error.
        """
        def offend(consumer, key, producer, why):
            raise ValueError(
                f"{self.name}: step {list(consumer.keys)} reads {key!r}, which is "
                f"produced later in the same tick by step {list(producer.keys)} "
                f"({why}); `inputs` may only name values already computed this tick, "
                f"so as declared it reads the PREVIOUS tick's value")

        for src in self.sources:
            for i, step in enumerate(src.message_steps):
                for key in step.inputs:
                    for later in src.message_steps[i + 1:]:
                        if key in later.keys:
                            offend(step, key, later,
                                   f"a later message-step of {src.id!r}")
                    for tick_step in src.tick_steps:
                        if key in tick_step.keys:
                            offend(step, key, tick_step,
                                   "a tick-step, which runs after every message-step")

        ordered_tick_steps = self.tick_steps()
        for i, step in enumerate(ordered_tick_steps):
            for key in step.inputs:
                for later in ordered_tick_steps[i + 1:]:
                    if key in later.keys:
                        offend(step, key, later,
                               f"a later tick-step (from source {later.source_id!r})")


class SensorState:
    """Applies a descriptor's steps to incoming messages and holds the result.

    Nothing here knows about ROS: `update(source_id, payload)` takes an already
    decoded payload, which is exactly what makes the mapping testable with plain
    objects instead of a live graph.

    The held values are TICK-STABLE. `update()` only appends to the open window;
    `tick()` is the sole writer of the observation, and `sensor_eval()` is a pure read
    of it. That separation is what makes the trace a function of the data rather than
    of how many messages happened to arrive between two ticks.
    """

    def __init__(self, spec: AdapterSpec):
        self.spec = spec
        #: The held observation. REBOUND by every tick, never mutated in place, which
        #: is what makes a tick atomic: a reader can never see a half-updated dict.
        #: The consequence is that `values` is a SNAPSHOT, not a live view -- caching
        #: the dict object gives you a frozen observation that will never change
        #: again. Re-read the attribute, or use `sensor_eval()`, which returns a copy
        #: under the lock and is the supported read.
        self.values = spec.defaults()
        self._by_id = {s.id: s for s in spec.sources}
        self._aggregate = spec.aggregate_by_key()
        self._quantile_by_key = {
            k: step.q
            for src in spec.sources for step in src.message_steps
            for k in step.keys
            if step.aggregate == "quantile"
        }
        #: key -> this tick's samples, in arrival order. Cleared by every tick.
        self._window: dict[str, list] = {}
        self._refreshed: frozenset = frozenset()
        self._refreshed_sources: frozenset = frozenset()
        #: source id -> messages folded into the OPEN window. A Counter and not a set
        #: because `data_health.samples_this_tick` has to say HOW MANY arrived, not
        #: just that something did: one sample and forty samples in a tick are the
        #: difference between a topic limping and a topic keeping up, and the count
        #: is the only place that shows it. Counted here rather than in the adapter
        #: so it is cleared by the same tick that clears the window it describes.
        self._window_sources: Counter = Counter()
        #: source id -> count, for the tick just CLOSED. The read side of the above.
        self._samples_this_tick: dict = {}
        #: Closed ticks. -1 until the first tick, so `ticks` is the index of the tick
        #: `sensor_eval()` is currently describing.
        self.ticks = -1
        self._updates_since_tick = 0
        self._warned_unticked = False
        # A caller that never calls tick() gets a monitor whose sensor values are the
        # schema defaults forever, and it is SILENT: sensor_eval() returns a full,
        # plausible dict and every test stays green. DeclarativeAdapter is in exactly
        # that state on dev today (P3 is what will call tick()), so this is a live
        # regression rather than a hypothetical one -- make it detectable.
        #
        # The budget is derived rather than picked: a hundred times the messages the
        # declared rates say one tick should hold, floored well above any plausible
        # burst, so it cannot fire on a fast topic that is being ticked normally.
        expected_per_tick = sum(s.expected_hz for s in spec.sources) / spec.tick_hz
        self._untick_budget = max(1000, int(100 * expected_per_tick))
        # Uncontended under the default single-threaded executor, and load-bearing the
        # moment anyone adds a callback group, a MultiThreadedExecutor, or the server
        # tier's network thread: without it a message landing mid-tick can append to a
        # window that fold() has already read and clear() is about to drop, silently
        # losing the sample.
        self._lock = threading.Lock()

    # -- write side ----------------------------------------------------------

    def update(self, source_id: str, payload) -> dict:
        """Fold one decoded message into the OPEN window. Does not touch the held
        values -- the observation changes only on `tick()`.

        Returns this message's contribution layered over the held values: useful for
        debugging and for a raw echo, but it is not the trace. The authoritative read
        is `sensor_eval()`.
        """
        src = self._by_id.get(source_id)
        if src is None:
            raise KeyError(f"unknown source {source_id!r}; have {sorted(self._by_id)}")
        with self._lock:
            # Arrival is recorded BEFORE any step runs, and unconditionally. ARRIVAL
            # and extraction YIELD are different questions: a Nav2 status whose
            # status_list is empty decodes to nothing, and a step that RAISES --
            # quat_to_roll_pitch on a malformed orientation -- produces nothing and
            # never reaches the end of this method. In both cases the topic is alive.
            # Recording it afterwards, or gating it on `scratch`, reports a live
            # source as silent, which under three-valued APs promotes every AP over
            # it to UNKNOWN and freezes the automaton. `refreshed_keys()` is what
            # says no key got a sample.
            self._window_sources[source_id] += 1
            self._updates_since_tick += 1
            if self._updates_since_tick > self._untick_budget and not self._warned_unticked:
                self._warned_unticked = True      # once per un-ticked stretch, not per message
                warnings.warn(
                    f"{self.spec.name}: {self._updates_since_tick} messages have been "
                    f"folded into the open window with no intervening tick(). Only "
                    f"tick() writes the observation, so sensor_eval() is still "
                    f"returning the schema defaults and the window is growing without "
                    f"bound -- whoever owns this SensorState is not driving the clock",
                    RuntimeWarning, stacklevel=2)

            # Scratch in front of the held values: later steps of THIS message see
            # what earlier steps of this same message produced, so upright_flag is
            # computed from this message's roll/pitch/height and not last tick's.
            scratch: dict = {}
            chained = ChainMap(scratch, self.values)
            for step in src.message_steps:
                scratch.update(step.apply(payload, chained))
            for key, value in scratch.items():
                self._window.setdefault(key, []).append(value)
            return dict(self.values) | scratch

    def tick(self, t: float | None = None) -> dict:
        """Close the open window and produce the observation for this tick.

        fold -> run the tick-steps over a CANDIDATE observation -> publish everything
        at once. The whole tick is atomic: nothing -- held values, `refreshed_keys()`,
        `refreshed_sources()`, `ticks` -- is visible until every step of the tick has
        succeeded. A tick-step that raises therefore leaves the previous observation
        AND the seam that describes it consistent with each other; committing the fold
        first would leave `sensor_eval()` returning tick k's values while
        `refreshed_keys()` still described tick k-1.

        A tick-step writes into the candidate, never into the window, so its output
        goes straight to the held values and is never itself windowed.

        Fires whether or not any message arrived: a tick with no data is precisely the
        tick that has to report that nothing arrived. A key with no sample holds its
        previous value -- zero-order hold -- and `refreshed_keys()` is what says the
        number is stale rather than steady.

        That includes state INSIDE an extractor. A tick-step's streak advances as a
        side effect, so a tick that raises after `stuck_streak` has already counted
        used to leave the advance behind permanently -- and since the streak is what
        the debounce compares against, `nav_stuck` then fired N ticks EARLY, where N
        is the number of failed ticks in its history. A declared ten-second debounce
        firing after seven observations is the same false positive `reset()` exists to
        prevent, arriving through a different door, on a safety-relevant AP. So the
        extractors are checkpointed before the attempt and restored if it fails.
        """
        with self._lock:
            extractors = self.spec.snapshot()
            try:
                folded = {}
                for key, samples in self._window.items():
                    step_aggregate = self._aggregate.get(key, DEFAULT_AGGREGATE)
                    value = self._fold(key, step_aggregate, samples)
                    if value is not _MISSING:
                        folded[key] = value

                candidate = dict(self.values)
                candidate.update(folded)
                for step in self.spec.tick_steps():
                    candidate.update(step.apply(None, candidate))
            except Exception:
                # Nothing has been committed, so the previous tick is intact and
                # self-consistent -- including any streak a tick-step advanced before
                # a later one raised. Drop the window anyway: a poisoned sample must
                # cost exactly one window, not raise out of every tick from here on.
                self.spec.restore(extractors)
                self._window.clear()
                self._window_sources.clear()
                self._updates_since_tick = 0
                self._warned_unticked = False
                raise

            self.values = candidate
            self._refreshed = frozenset(folded)
            self._refreshed_sources = frozenset(self._window_sources)
            self._samples_this_tick = dict(self._window_sources)
            self.ticks += 1
            self._window.clear()
            self._window_sources.clear()
            self._updates_since_tick = 0
            self._warned_unticked = False
            return dict(self.values)

    def reset(self):
        """Back to the pre-episode state: defaults held, window empty, tick index
        before the first tick, and every stateful extractor cleared.

        docs/clocking.md gives the episode a `step` index that `arm`/`reset` restarts.
        Without this there was no way to restart anything but the values: the debounce
        streak lives in the extractor's closure on the SPEC, so it survived
        constructing a new SensorState, and the previous episode's blocked ticks
        counted toward the next episode's nav_stuck.
        """
        with self._lock:
            self.values = self.spec.defaults()
            self._window.clear()
            self._window_sources.clear()
            self._refreshed = frozenset()
            self._refreshed_sources = frozenset()
            self._samples_this_tick = {}
            self.ticks = -1
            self._updates_since_tick = 0
            self._warned_unticked = False
            self.spec.reset()

    def _fold(self, key: str, policy: str, samples: list):
        """The single value this key's samples collapse to, or `_MISSING` when the
        window held no usable sample -- in which case the key holds and is not
        reported as refreshed."""
        if policy in NUMERIC_AGGREGATES:
            # NaN is not an ordering. `min([1.0, nan, 0.5])` is 0.5 but
            # `min([nan, 1.0, 0.5])` is nan, and `sorted()` over a list with a NaN in
            # it is not sorted -- so under `min` or `quantile` the ARRIVAL ORDER of a
            # window would decide the observation. min_range is monocular-depth
            # derived, so a non-finite sample is a thing that happens, not a
            # hypothetical. Drop them explicitly instead.
            usable = [
                s for s in samples
                if not (isinstance(s, float) and not math.isfinite(s))
            ]
            if not usable:
                return _MISSING
            samples = usable
        try:
            if policy == "quantile":
                return _quantile(samples, self._quantile_by_key[key])
            return AGGREGATORS[policy](samples)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{self.spec.name}: folding key {key!r} with {policy!r} over "
                f"{len(samples)} sample(s) failed: {exc}") from exc

    # -- read side (pure) ----------------------------------------------------

    def sensor_eval(self) -> dict:
        """The observation for the last closed tick. A PURE read: call it any number
        of times between ticks and get the same dict, and calling it never consumes
        the window."""
        with self._lock:
            return dict(self.values)

    def refreshed_keys(self) -> frozenset:
        """Keys that got a real sample in the tick just closed.

        Everything else in `sensor_eval()` is held over from an earlier tick. This is
        the seam three-valued APs will use: a held number is not a wrong number, but
        it is not evidence either.
        """
        return self._refreshed

    def refreshed_sources(self) -> frozenset:
        """Source ids that delivered at least one message in the tick just closed."""
        return self._refreshed_sources

    def samples_this_tick(self) -> dict:
        """Source id -> messages folded into the tick just closed. Absent means zero.

        `refreshed_sources()` is this, thresholded at one. Both exist because
        `data_health` reports the count and the boolean separately, and deriving the
        boolean from the count is cheaper than the other way round.
        """
        return dict(self._samples_this_tick)

    def pending_samples(self) -> int:
        """Samples sitting in the OPEN window. Zero right after any tick -- an idle
        period must not accumulate."""
        with self._lock:
            return sum(len(v) for v in self._window.values())

    @property
    def untick_budget(self) -> int:
        """How many messages may pile into one open window before `update()` warns.
        Derived from the descriptor's declared rates; exposed so a caller can report
        it rather than guess at it."""
        return self._untick_budget

    @property
    def updates_since_tick(self) -> int:
        """Messages folded into the OPEN window. Grows without bound exactly when
        nobody is calling tick(), which is the one broken state `sensor_eval()` cannot
        show you: it keeps returning a full, plausible dict of schema defaults."""
        return self._updates_since_tick


# ------------------------------------------------------------------- loading

def load(name_or_path) -> AdapterSpec:
    """Load a descriptor by adapter name ('real_g1'), file name, or path."""
    adapters = skill_monitor.adapters_dir()
    path = Path(name_or_path)
    if not path.suffix:
        path = adapters / f"{name_or_path}.json"
    elif not path.is_absolute() and not path.exists():
        path = adapters / path.name
    if not path.exists():
        raise FileNotFoundError(
            f"no adapter descriptor {path.name!r} (have: {available()})")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return from_dict(raw, base_dir=path.parent)


def _read_fragment(fragment, base_dir: Path, label: str, adapter: str) -> dict:
    """One schema fragment's {key: {doc, default}} map: a "*_schema.json" file name (or
    path) resolved against `base_dir`, or an inline dict used as-is."""
    if isinstance(fragment, dict):
        return fragment
    if not isinstance(fragment, str):
        raise ValueError(
            f"adapter {adapter!r}: schema fragment {label} must be a file name or an "
            f"inline {{key: {{doc, default}}}} dict, got {type(fragment).__name__}")
    path = base_dir / fragment
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(
            f"adapter {adapter!r}: schema fragment {label} names {fragment!r}, which "
            f"does not exist in {base_dir}") from exc
    keys = loaded.get("keys")
    if not isinstance(keys, dict):
        raise ValueError(
            f"adapter {adapter!r}: schema fragment {fragment!r} has no 'keys' object")
    return keys


def compose_schema(schema, base_dir: Path, adapter: str = "adapter") -> tuple:
    """Merge a descriptor's `schema` declaration into one key map, plus the warnings the
    merge raised.

    `schema` is a single fragment or a LIST of them. Fragments are applied left to
    right and a later one wins, so ["pose_schema.json", "nav_schema.json"] is the pose
    vocabulary plus navigation's, and a trailing inline dict retunes individual keys for
    one robot without forking the shared file.

    A collision only counts as a collision when the two entries DIFFER: re-declaring a
    key identically says nothing and is silent. When they differ, the later entry still
    wins -- see the module docstring for why that is not an error -- and the override is
    named in the returned warnings so it reaches `manifest()` and the wire.
    """
    fragments = schema if isinstance(schema, list) else [schema]
    if not fragments:
        raise ValueError(f"adapter {adapter!r} declares no schema")

    merged: dict = {}
    origin: dict = {}
    complaints: list = []
    for i, fragment in enumerate(fragments):
        label = fragment if isinstance(fragment, str) else f"schema[{i}] (inline)"
        for key, entry in _read_fragment(fragment, base_dir, f"[{i}]", adapter).items():
            previous = merged.get(key, _MISSING)
            if previous is not _MISSING and previous != entry:
                changed = sorted(
                    f"{field}: {previous.get(field)!r} -> {entry.get(field)!r}"
                    for field in set(previous) | set(entry)
                    if isinstance(previous, dict) and isinstance(entry, dict)
                    and previous.get(field) != entry.get(field)
                ) or [f"{previous!r} -> {entry!r}"]
                complaints.append(
                    f"schema key {key!r} is redefined by {label} and the later "
                    f"definition wins ({'; '.join(changed)}); it came from "
                    f"{origin[key]}. If that is intentional this line is the record of "
                    f"it; if it is not, two fragments disagree about what {key!r} means "
                    f"and every rule written over it is reading one of the two")
            merged[key] = entry
            origin[key] = label

    if not merged:
        raise ValueError(f"adapter {adapter!r} declares no schema")
    return merged, complaints


def from_dict(raw: dict, base_dir: Path | None = None) -> AdapterSpec:
    base_dir = skill_monitor.adapters_dir() if base_dir is None else base_dir
    schema = raw.get("schema")
    if schema is None:
        raise ValueError(f"adapter {raw.get('name')!r} declares no schema")
    merged, complaints = compose_schema(schema, base_dir, raw.get("name", "adapter"))
    return AdapterSpec(raw, merged, complaints)


def available() -> list:
    return sorted(
        p.stem for p in skill_monitor.adapters_dir().glob("*.json")
        if not p.stem.endswith("_schema"))
