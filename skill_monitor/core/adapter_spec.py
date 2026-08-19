"""An adapter as DATA: which topics a robot publishes, and how their fields become
sensor_eval keys. Pure -- no ROS -- so the whole mapping is unit-testable and the
generator (which runs on a host with no ROS) can read a robot's schema without
importing the module that subscribes to it.

A descriptor (skill_monitor/adapters/*.json) has:

    schema    "nav_schema.json" or an inline {key: {doc, default}} dict
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
from collections import ChainMap
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
        if self.q is not None and not 0.0 <= self.q <= 1.0:
            raise ValueError(f"{source_id}: 'q' must be between 0.0 and 1.0, got {self.q!r}")

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
        self.fn_name = fn_name
        self.fn = EXTRACTORS[fn_name](**args) if fn_name else None

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

    def __init__(self, raw: dict, schema: dict):
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
        out = []
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
        self._window_sources: set = set()
        #: Closed ticks. -1 until the first tick, so `ticks` is the index of the tick
        #: `sensor_eval()` is currently describing.
        self.ticks = -1
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
            # Scratch in front of the held values: later steps of THIS message see
            # what earlier steps of this same message produced, so upright_flag is
            # computed from this message's roll/pitch/height and not last tick's.
            scratch: dict = {}
            chained = ChainMap(scratch, self.values)
            for step in src.message_steps:
                scratch.update(step.apply(payload, chained))
            for key, value in scratch.items():
                self._window.setdefault(key, []).append(value)
            # Unconditional: ARRIVAL and extraction YIELD are different questions. A
            # Nav2 status whose status_list is empty, or a JSON status whose fields
            # are all absent, decodes to nothing -- but the topic is alive and the
            # source is not silent. Gating this on `scratch` would report the source
            # as having delivered nothing, which under three-valued APs promotes
            # every AP over it to UNKNOWN and freezes the automaton.
            self._window_sources.add(source_id)
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

        The one thing a rollback cannot undo is state INSIDE an extractor: if the
        third tick-step raises, the first two have already advanced their own streaks.
        That is inherent to a stateful extractor and is why `reset()` exists.
        """
        with self._lock:
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
                # self-consistent. Drop the window anyway: a poisoned sample must cost
                # exactly one window, not raise out of every tick from here on.
                self._window.clear()
                self._window_sources.clear()
                raise

            self.values = candidate
            self._refreshed = frozenset(folded)
            self._refreshed_sources = frozenset(self._window_sources)
            self.ticks += 1
            self._window.clear()
            self._window_sources.clear()
            return dict(self.values)

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

    def pending_samples(self) -> int:
        """Samples sitting in the OPEN window. Zero right after any tick -- an idle
        period must not accumulate."""
        with self._lock:
            return sum(len(v) for v in self._window.values())


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
    raw = json.loads(path.read_text())
    return from_dict(raw, base_dir=path.parent)


def from_dict(raw: dict, base_dir: Path | None = None) -> AdapterSpec:
    base_dir = skill_monitor.adapters_dir() if base_dir is None else base_dir
    schema = raw.get("schema")
    if isinstance(schema, str):
        schema = json.loads((base_dir / schema).read_text())["keys"]
    if not isinstance(schema, dict) or not schema:
        raise ValueError(f"adapter {raw.get('name')!r} declares no schema")
    return AdapterSpec(raw, schema)


def available() -> list:
    return sorted(
        p.stem for p in skill_monitor.adapters_dir().glob("*.json")
        if not p.stem.endswith("_schema"))
