"""The wire contract: topic names, the JSON envelope, one builder and one validator
per payload.

Specified in ``docs/api.md``, which is the source of truth for every field name below.
This module is the executable copy of that document, and it lands before every other
package so that nine concurrent branches cannot each invent their own topic names and
their own JSON keys -- reconciling that afterwards is a rewrite, not a merge.

Pure Python on purpose. No ``rclpy``, no I/O, no clock, no network: the spec generator,
the contract oracle, the gateway's tests and any client that never installs ROS all
import this, so it must be importable on a laptop.

Three rules the rest of the repo depends on:

  * **Topic names live here and nowhere else.** No other file may contain a
    ``/monitor/...`` string literal. The ``/ltl/*`` -> ``/monitor/*`` rename then
    happens because a package imported ``api.OBSERVATION``, not as a nine-branch sweep
    that one branch forgets. ``tests/test_api.py`` greps for stray literals.

  * **Validators return a list of human-readable problems and never raise**, for any
    input at all -- ``None``, a list, a bare string. Same shape and same reason as
    ``spec_contract.validate()``: a gateway or a frontend handed a malformed frame must
    be able to *report* it, not die on it.

  * **Builders take keyword arguments and fill the envelope themselves.** A caller
    cannot forget ``seq`` because it is a required parameter, and cannot mistype
    ``schema_version`` because it is not a parameter at all.

Plain dicts, deliberately -- no dataclasses and no shared base class. These payloads
cross Python -> ROS -> WebSocket -> JSON on disk; dicts validated at the edge travel
across that boundary, class instances do not.
"""

from __future__ import annotations

from typing import Any, Callable

# Bumped on any breaking change to a payload below. Consumers compare, they do not
# negotiate: an unrecognised version is a problem to report, not a format to guess at.
SCHEMA_VERSION = 1

# --------------------------------------------------------------------------- topics

TICK = "/monitor/tick"
OBSERVATION = "/monitor/observation"
VERDICT = "/monitor/verdict"
ADAPTER = "/monitor/adapter"
MANIFEST = "/monitor/manifest"
COMMAND = "/monitor/command"
LOAD_SPEC = "/monitor/load_spec"
SPEC_STATUS = "/monitor/spec_status"
RAW_ECHO_REQUEST = "/monitor/raw_echo_request"
RAW_ECHO = "/monitor/raw_echo"
MONITOR_STATUS = "/monitor/status"

TOPICS = frozenset({
    TICK, OBSERVATION, VERDICT, ADAPTER, MANIFEST,
    COMMAND, LOAD_SPEC, SPEC_STATUS, RAW_ECHO_REQUEST, RAW_ECHO,
    MONITOR_STATUS,
})

# Published TRANSIENT_LOCAL, depth 1, reliable. A client that connects mid-mission gets
# the last value immediately instead of waiting for a change that may never come --
# which for a manifest or an adapter descriptor is "never", since they are published
# once at startup.
#
# MONITOR_STATUS is latched for the sharper version of the same reason: a paused monitor
# emits nothing else, so a console that connected during the pause and waited for a
# change would wait for the operator who caused it. Not latched, the one state an
# operator must never miss is the one state that is invisible.
LATCHED_TOPICS = frozenset({ADAPTER, MANIFEST, SPEC_STATUS, MONITOR_STATUS})

# ---------------------------------------------------------------- closed vocabularies

CLOCK_MODES = ("wall", "replay", "manual")

# Which clock drove a recorded run. A replayed file must never be ambiguous about it.
CLOCK_SOURCES = ("external", "internal")

# `arrival` today; `stamp` once the robot stamps its own messages.
TICK_MEMBERSHIPS = ("arrival", "stamp")

# INCONCLUSIVE_NO_DATA is a *different axis* from a formula's INCONCLUSIVE: the former
# means nothing arrived, the latter that the prefix neither proves nor refutes.
VERDICTS = ("SATISFIED", "VIOLATED", "UNDECIDED", "INCONCLUSIVE_NO_DATA")

# core.automata.MonitorStatus, as a string on the wire.
FORMULA_STATUSES = ("INCONCLUSIVE", "ACCEPTED", "VIOLATED")

FAULT_CATEGORIES = ("SAFETY", "INVARIANT", "TIMEOUT", "PROGRESS")

# The guard conditions a spec may declare on an execution phase, in the order the phase
# machine consults them: a phase is entered when `enter_condition` holds, refuses entry
# when `precondition` does not, fails outright when `invariant` breaks, counts a
# violation when `progress_condition` does not hold, and leaves when `exit_condition`
# does. Closed, because `verdict.phase_guards.guards[].name` is a row label a console
# renders -- an unrecognised one would be drawn as a guard nobody can name.
PHASE_GUARD_NAMES = (
    "enter_condition", "precondition", "invariant",
    "progress_condition", "exit_condition",
)

# core.monitor_action.Action, ordered. The monitor decides the rung; the supervisor
# only enforces it.
INTERVENTION_ACTIONS = ("CONTINUE", "WARN", "SLOW", "REPLAN", "HALT", "ABORT")

COMMANDS = ("arm", "reset", "pause", "resume")

# Whether the monitor is watching, and if not, why not. Closed, because `running` is the
# only member that means the robot is being monitored and a console must be able to
# decide that by comparison rather than by guessing at a string it has not seen before.
#
#   running  the automaton is being stepped -- the only safe state
#   paused   an operator stopped it; the robot keeps moving, unwatched
#   halted   a fault ended the run; recoverable only by `reset`
#   idle     no episode is armed, or a terminal state was reached
#
# The last three all mean "not watching", which is why they are one field and not three
# booleans: a console that renders them separately can render two of them at once, and
# an operator reading "paused" beside "idle" learns nothing about the robot.
RUN_STATES = ("running", "paused", "halted", "idle")

# =============================================================================
# Validation primitives
#
# Every public validator is total: it accepts Any and returns list[str]. Nothing
# below may raise, which is why each helper checks the type before it indexes.
# =============================================================================

_Check = tuple[Callable[[Any], bool], str]


def _kind(value: Any) -> str:
    """The word to use in a problem message for something of the wrong type."""
    if value is None:
        return "null"
    return {
        bool: "a bool", int: "an int", float: "a float", str: "a string",
        list: "an array", dict: "an object",
    }.get(type(value), f"a {type(value).__name__}")


def _is_int(v: Any) -> bool:
    # bool is a subclass of int in Python, and `True` where a seq belongs is a bug we
    # want reported rather than serialised.
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


INT: _Check = (_is_int, "an int")
NUMBER: _Check = (_is_number, "a number")
STRING: _Check = (lambda v: isinstance(v, str), "a string")
BOOL: _Check = (lambda v: isinstance(v, bool), "a bool")
OBJECT: _Check = (lambda v: isinstance(v, dict), "an object")
ARRAY: _Check = (lambda v: isinstance(v, list), "an array")

INT_OR_NULL: _Check = (lambda v: v is None or _is_int(v), "an int or null")
#: The null is a third value, not a missing bool. "We did not check this" and "this
#: does not hold" are different facts about a guard, and one of them is a fault.
BOOL_OR_NULL: _Check = (lambda v: v is None or isinstance(v, bool), "a bool or null")
OBJECT_OR_NULL: _Check = (lambda v: v is None or isinstance(v, dict), "an object or null")
NUMBER_OR_NULL: _Check = (lambda v: v is None or _is_number(v), "a number or null")
STRING_OR_NULL: _Check = (lambda v: v is None or isinstance(v, str), "a string or null")
STRING_ARRAY: _Check = (
    lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    "an array of strings",
)
OBJECT_ARRAY: _Check = (
    lambda v: isinstance(v, list) and all(isinstance(x, dict) for x in v),
    "an array of objects",
)
UNIT_INTERVAL: _Check = (
    lambda v: _is_number(v) and 0.0 <= v <= 1.0,
    "a number in [0.0, 1.0]",
)
#: A count of things that happened. The bound is the point: an unbounded INT let a
#: producer's own bookkeeping slip ship -141 pulses as a valid `missed_ticks`.
COUNT: _Check = (lambda v: _is_int(v) and v >= 0, "an int >= 0")
ANY: _Check = (lambda v: True, "anything")


def _one_of(values, *, nullable: bool = False) -> _Check:
    allowed = tuple(values)
    label = " or ".join(repr(v) for v in allowed)
    if nullable:
        return (lambda v: v is None or v in allowed, f"{label} or null")
    return (lambda v: v in allowed, label)


def _string_keyed(inner: _Check) -> _Check:
    """An object whose keys are strings and whose values all pass `inner`."""
    pred, what = inner
    return (
        lambda v: isinstance(v, dict)
        and all(isinstance(k, str) for k in v)
        and all(pred(x) for x in v.values()),
        f"an object mapping strings to {what}",
    )


def _not_an_object(payload: Any, label: str) -> list[str] | None:
    """The problem list for a payload that is not a JSON object at all, else None.

    Every public validator starts here, which is what makes `validate_x(None)` and
    `validate_x("nonsense")` return a problem instead of an AttributeError.
    """
    if isinstance(payload, dict):
        return None
    return [f"{label}: payload must be an object, got {_kind(payload)}"]


def _check_fields(
    payload: dict,
    label: str,
    fields: dict[str, _Check],
    problems: list[str],
    *,
    optional: tuple[str, ...] = (),
    closed: bool = True,
) -> None:
    """Required fields present and well typed; unknown fields named.

    `optional` names fields that are tolerated when absent and still type-checked when
    present. That is what lets a payload gain a field without the addition being a
    breaking change every older producer fails -- an added REQUIRED field is a wire
    break and needs a SCHEMA_VERSION bump.

    `closed` off means the payload legitimately carries fields this engine version
    does not understand -- the skill manifest, which is passed through as authored.
    """
    for name, (pred, expected) in fields.items():
        if name not in payload:
            if name not in optional:
                problems.append(f"{label}: missing required field '{name}'")
            continue
        value = payload[name]
        if not pred(value):
            problems.append(
                f"{label}: field '{name}' must be {expected}, got {_kind(value)}"
                + ("" if isinstance(value, (dict, list)) else f" ({value!r})")
            )
    if closed:
        for name in payload:
            if name not in fields and name not in optional:
                problems.append(f"{label}: unknown field '{name}'")


def _check_each(
    payload: dict,
    key: str,
    label: str,
    fields: dict[str, _Check],
    problems: list[str],
    *,
    optional: tuple[str, ...] = (),
) -> None:
    """Apply `_check_fields` to every element of a list-of-objects field."""
    items = payload.get(key)
    if not isinstance(items, list):
        return  # already reported by the parent's own type check
    for i, item in enumerate(items):
        if isinstance(item, dict):
            _check_fields(item, f"{label}.{key}[{i}]", fields, problems, optional=optional)


def _check_nested(
    payload: dict,
    key: str,
    label: str,
    fields: dict[str, _Check],
    problems: list[str],
    *,
    optional: tuple[str, ...] = (),
) -> None:
    """Apply `_check_fields` to a nested object field."""
    nested = payload.get(key)
    if isinstance(nested, dict):
        _check_fields(nested, f"{label}.{key}", fields, problems, optional=optional)


def _check_version(payload: dict, label: str, problems: list[str]) -> None:
    """A payload from a newer engine is reported, not silently misread."""
    version = payload.get("schema_version")
    if _is_int(version) and version != SCHEMA_VERSION:
        problems.append(
            f"{label}: schema_version is {version}, this build speaks {SCHEMA_VERSION}"
        )


# =============================================================================
# The envelope
#
# Three tiers, and which tier a payload sits in is dictated by docs/api.md's own
# examples:
#
#   tick-scoped  schema_version, seq, t, step   -- observation, verdict, raw_echo
#   clocked      schema_version, seq, t         -- tick (the clock has no episode, so
#                                                  no step; `arm`/`reset` go to the
#                                                  monitor, not to the clock)
#   plain        schema_version                 -- adapter, manifest, command,
#                                                  load_spec, spec_status,
#                                                  raw_echo_request
#
# `step` is required-but-nullable in the tick-scoped tier: null means no episode is
# armed, which is a fact worth transmitting rather than a field worth omitting.
#
# A plain payload MAY carry `seq` and `t` when the publisher has them handy -- the
# builders accept them as optional keywords and the validators tolerate them -- but a
# consumer must not require them. A latched manifest's `seq` is the seq at which it was
# last published, which for a mid-mission subscriber is arbitrarily old and therefore
# not something to reason about.
# =============================================================================

_TICK_SCOPED: dict[str, _Check] = {
    "schema_version": INT,
    "seq": INT,
    "t": NUMBER,
    "step": INT_OR_NULL,
}

_CLOCKED: dict[str, _Check] = {
    "schema_version": INT,
    "seq": INT,
    "t": NUMBER,
}

_PLAIN: dict[str, _Check] = {
    "schema_version": INT,
}

# Tolerated, never required, on a plain payload.
_PLAIN_OPTIONAL = ("seq", "t")


def _tick_scoped_envelope(seq: Any, t: Any, step: Any) -> dict:
    return {"schema_version": SCHEMA_VERSION, "seq": seq, "t": t, "step": step}


def _clocked_envelope(seq: Any, t: Any) -> dict:
    return {"schema_version": SCHEMA_VERSION, "seq": seq, "t": t}


def _plain_envelope(seq: Any = None, t: Any = None) -> dict:
    envelope: dict = {"schema_version": SCHEMA_VERSION}
    if seq is not None:
        envelope["seq"] = seq
    if t is not None:
        envelope["t"] = t
    return envelope


# =============================================================================
# /monitor/tick -- clock -> everyone
# =============================================================================

_TICK_FIELDS: dict[str, _Check] = {
    **_CLOCKED,
    "tick_hz": NUMBER,
    "mode": _one_of(CLOCK_MODES),
    "t0": NUMBER,
}


def build_tick(*, seq: int, t: float, tick_hz: float, t0: float,
               mode: str = "wall") -> dict:
    """The only thing that advances the system.

    `tick_hz` is the *effective* rate after any CLI override, not the descriptor
    default: a consumer converting a tick-denominated timeout to seconds must read the
    rate that is actually running.

    `t0` is unix time at which the *clock* started, and it is what lets a consumer
    distinguish a **restart** from an **out-of-order delivery**. `seq` restarts at 1
    when the clock does, so a consumer that only refuses to step backwards -- the
    correct response to a redelivered frame -- would otherwise silently discard the
    whole beginning of the new run, however far the previous one had got. Same `t0` and
    a lower `seq` is a redelivery to drop; a different `t0` is a new clock, and the
    consumer must reset its own tick bookkeeping to follow it.

    **Required, and deliberately with no default**, unlike `mode`. A default would let
    a producer that has never heard of `t0` emit a frame claiming `t0 == 0.0` that
    validates perfectly -- and two such producers would be indistinguishable, which is
    the exact failure this field exists to prevent. Forgetting it is a `TypeError` at
    the call site instead of a wrong answer on the wire.
    """
    return _clocked_envelope(seq, t) | {"tick_hz": tick_hz, "mode": mode, "t0": t0}


def validate_tick(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "tick")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(payload, "tick", _TICK_FIELDS, problems)
    _check_version(payload, "tick", problems)
    return problems


# =============================================================================
# /monitor/observation -- evaluator -> monitor, frontend
# =============================================================================

_DATA_HEALTH_FIELDS: dict[str, _Check] = {
    "rate_hz": NUMBER,
    "expected_hz": NUMBER,
    "age_s": NUMBER,
    "samples_this_tick": INT,
    "refreshed": BOOL,
    "dropped": INT,
}

_OBSERVATION_FIELDS: dict[str, _Check] = {
    **_TICK_SCOPED,
    "clock": _one_of(CLOCK_SOURCES),
    "tick_membership": _one_of(TICK_MEMBERSHIPS),
    "sensors": _string_keyed(ANY),
    "ap_values": _string_keyed(BOOL),
    "unknown_aps": STRING_ARRAY,
    "confidence": UNIT_INTERVAL,
    "data_health": _string_keyed(OBJECT),
}


def build_observation(
    *,
    seq: int,
    t: float,
    step: int | None,
    sensors: dict,
    ap_values: dict,
    confidence: float,
    data_health: dict,
    unknown_aps=(),
    clock: str = "external",
    tick_membership: str = "arrival",
) -> dict:
    """One message per tick, always -- including ticks where nothing arrived.

    `ap_values` is booleans only: an AP that could not be evaluated names itself in
    `unknown_aps` and is absent from `ap_values`, so UNKNOWN never has to be encoded as
    a third truth value inside a dict the automaton reads.
    """
    return _tick_scoped_envelope(seq, t, step) | {
        "clock": clock,
        "tick_membership": tick_membership,
        "sensors": dict(sensors),
        "ap_values": dict(ap_values),
        "unknown_aps": list(unknown_aps),
        "confidence": confidence,
        "data_health": dict(data_health),
    }


def validate_observation(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "observation")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(payload, "observation", _OBSERVATION_FIELDS, problems)
    _check_version(payload, "observation", problems)

    health = payload.get("data_health")
    if isinstance(health, dict):
        for source_id, entry in health.items():
            if isinstance(entry, dict):
                _check_fields(
                    entry,
                    f"observation.data_health[{source_id!r}]",
                    _DATA_HEALTH_FIELDS,
                    problems,
                )

    # An AP cannot be both evaluated and unevaluated in the same tick; if it is, a
    # consumer's answer depends on which field it read first.
    ap_values, unknown = payload.get("ap_values"), payload.get("unknown_aps")
    if isinstance(ap_values, dict) and isinstance(unknown, list):
        for ap in sorted(set(ap_values) & {u for u in unknown if isinstance(u, str)}):
            problems.append(
                f"observation: '{ap}' appears in both ap_values and unknown_aps"
            )
    return problems


# =============================================================================
# /monitor/verdict -- monitor -> supervisor, frontend
# =============================================================================

_FORMULA_FIELDS: dict[str, _Check] = {
    "name": STRING,
    "status": _one_of(FORMULA_STATUSES),
    # Which state of this formula's Büchi automaton the monitor is in right now, read
    # against the graph of the same `name` on the latched `manifest.automata`.
    # Nullable, and the null is load-bearing: a producer that cannot report a state --
    # a faked monitor, or a build whose graph is unavailable -- says so, and the
    # consumer highlights nothing rather than guessing state 0.
    "state": INT_OR_NULL,
}

_FAILURE_MODE_FIELDS: dict[str, _Check] = {
    "name": STRING,
    "fault_category": _one_of(FAULT_CATEGORIES),
    "status": _one_of(FORMULA_STATUSES),
    # Required, not optional. Without it a VIOLATED derived from a dead sensor grades
    # at 1.0 and the intervention ladder goes straight to ABORT.
    "confidence": UNIT_INTERVAL,
    # Same field, same meaning as on a formula row: a named failure mode is an LTL
    # monitor too and has its own graph on `manifest.automata`, under its own name.
    "state": INT_OR_NULL,
}

#: `state` arrived on both row types after SCHEMA_VERSION 1 shipped. Required would be a
#: wire break needing a version bump -- every producer that predates it becomes invalid
#: for carrying nothing new. Optional means an older producer still validates while one
#: that sends `state` is type-checked. Both row field sets stay CLOSED, so `state` still
#: has to be *declared* here or a verdict carrying it is rejected as an unknown field.
_ROW_OPTIONAL = ("state",)

_RISK_FIELDS: dict[str, _Check] = {
    "steps_to_timeout": INT_OR_NULL,
    # Ships *beside* steps_to_timeout, never replacing it, until spec bounds move to
    # seconds (P11).
    "seconds_to_timeout": NUMBER_OR_NULL,
    "violations_to_fault": INT_OR_NULL,
    "warn": BOOL,
    "severity": STRING_OR_NULL,
    "trigger_confidence": UNIT_INTERVAL,
    "stale_sources": STRING_ARRAY,
}

_INTERVENTION_FIELDS: dict[str, _Check] = {
    "action": _one_of(INTERVENTION_ACTIONS),
    "category": _one_of(FAULT_CATEGORIES, nullable=True),
    "imminence": STRING_OR_NULL,
    "confidence": UNIT_INTERVAL,
}

#: One row of `verdict.phase_guards.guards`: a guard the active phase declares, the
#: expression **as the spec authored it**, and the truth the phase machine computed for
#: it on this tick.
#:
#: `expr` is carried rather than derived because the consumer must not evaluate it. A
#: second implementation of the expression evaluator is exactly where this project's
#: `min_range < 0.25` decimal-point bug lived three times; the console shows the
#: operator their own words next to the monitor's own answer, and computes nothing.
_PHASE_GUARD_FIELDS: dict[str, _Check] = {
    "name": _one_of(PHASE_GUARD_NAMES),
    "expr": STRING,
    # Nullable on purpose, and the null is not a shrug: it means the phase machine did
    # not consult this guard on this tick -- it short-circuited before reaching it, an
    # AP the expression reads was in `unknown_aps`, or the expression raised. A
    # consumer that renders null as false reports a guard as broken that was never
    # asked, which is the one reading this field exists to prevent.
    "value": BOOL_OR_NULL,
}

#: `verdict.phase_guards` itself. Null for the whole block when no phase is active --
#: the same absence `phase_index` reports, spelled the same way.
_PHASE_GUARDS_FIELDS: dict[str, _Check] = {
    "phase": STRING,
    "guards": OBJECT_ARRAY,
}

_VERDICT_FIELDS: dict[str, _Check] = {
    **_TICK_SCOPED,
    "skill_name": STRING,
    "phase": STRING_OR_NULL,
    "phase_index": INT_OR_NULL,
    "verdict": _one_of(VERDICTS),
    "formulas": OBJECT_ARRAY,
    "failure_modes": OBJECT_ARRAY,
    "terminal": STRING_OR_NULL,
    "risk": OBJECT,
    "intervention": OBJECT,
    # Pulses the monitor did not see. Logged, never interpolated -- and counted, so a
    # negative is a producer talking about a tick axis it is no longer on.
    "missed_ticks": COUNT,
    # The evaluated truth of the active phase's guard conditions, or null when no phase
    # is active. See `_PHASE_GUARD_FIELDS`.
    "phase_guards": OBJECT_OR_NULL,
}

#: `phase_guards` landed after SCHEMA_VERSION 1 shipped, so it follows the rule `state`
#: and `threshold` already follow: optional, because making it required would invalidate
#: every producer that predates it with no version bump to make the mismatch
#: detectable. `_VERDICT_FIELDS` is CLOSED, so it still has to be *declared* above or a
#: verdict carrying it is thrown out entirely rather than merely ignored.
_VERDICT_OPTIONAL = ("phase_guards",)


def build_verdict(
    *,
    seq: int,
    t: float,
    step: int | None,
    skill_name: str,
    phase: str | None,
    phase_index: int | None,
    verdict: str,
    formulas,
    failure_modes,
    risk: dict,
    intervention: dict,
    terminal: str | None = None,
    missed_ticks: int = 0,
    phase_guards: dict | None = None,
) -> dict:
    """Exactly once per tick.

    `intervention.action` is one rung of CONTINUE < WARN < SLOW < REPLAN < HALT < ABORT.
    The monitor decides it here; the supervisor only enforces what it is handed, so the
    decision is in the recorded stream rather than in the actuating process.

    `phase_guards` defaults to None because "no phase is active" is the ordinary state
    of an idle or finished run, and because a producer with no phase machine at all
    still has to be able to build a valid verdict.
    """
    return _tick_scoped_envelope(seq, t, step) | {
        "skill_name": skill_name,
        "phase": phase,
        "phase_index": phase_index,
        "verdict": verdict,
        "formulas": list(formulas),
        "failure_modes": list(failure_modes),
        "terminal": terminal,
        "risk": dict(risk),
        "intervention": dict(intervention),
        "missed_ticks": missed_ticks,
        "phase_guards": None if phase_guards is None else dict(phase_guards),
    }


def build_phase_guard(*, name: str, expr: str, value: bool | None = None) -> dict:
    """One row of `verdict.phase_guards.guards`.

    `value` defaults to None -- "the phase machine did not consult this guard on this
    tick" -- because that is the safe default for a caller that has no answer. A caller
    that computed one passes it; nothing here computes it, and nothing here may.
    """
    return {"name": name, "expr": expr, "value": value}


def build_phase_guards(*, phase: str, guards) -> dict:
    """`verdict.phase_guards`: which phase, and the truth of each guard it declares."""
    return {"phase": phase, "guards": list(guards)}


def build_formula(*, name: str, status: str, state: int | None = None) -> dict:
    """One entry of `verdict.formulas`.

    `state` defaults to None -- unlike `confidence` below -- because "I do not know
    which automaton state this is" is a legitimate and common answer (no graph, or a
    monitor this build cannot introspect), whereas "I do not know how much to believe
    this fault" never is.
    """
    return {"name": name, "status": status, "state": state}


def build_failure_mode(
    *,
    name: str,
    fault_category: str,
    status: str,
    confidence: float,
    state: int | None = None,
) -> dict:
    """One entry of `verdict.failure_modes`. `confidence` has no default on purpose."""
    return {
        "name": name,
        "fault_category": fault_category,
        "status": status,
        "confidence": confidence,
        "state": state,
    }


def build_risk(
    *,
    steps_to_timeout: int | None,
    seconds_to_timeout: float | None,
    violations_to_fault: int | None,
    warn: bool,
    trigger_confidence: float,
    severity: str | None = None,
    stale_sources=(),
) -> dict:
    """`verdict.risk` -- how close the run is to a bound, and how much to believe it."""
    return {
        "steps_to_timeout": steps_to_timeout,
        "seconds_to_timeout": seconds_to_timeout,
        "violations_to_fault": violations_to_fault,
        "warn": warn,
        "severity": severity,
        "trigger_confidence": trigger_confidence,
        "stale_sources": list(stale_sources),
    }


def build_intervention(
    *,
    action: str,
    confidence: float,
    category: str | None = None,
    imminence: str | None = None,
) -> dict:
    """`verdict.intervention` -- the rung, and the evidence that chose it."""
    return {
        "action": action,
        "category": category,
        "imminence": imminence,
        "confidence": confidence,
    }


def validate_verdict(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "verdict")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(payload, "verdict", _VERDICT_FIELDS, problems,
                  optional=_VERDICT_OPTIONAL)
    _check_version(payload, "verdict", problems)
    _check_each(payload, "formulas", "verdict", _FORMULA_FIELDS, problems,
                optional=_ROW_OPTIONAL)
    _check_each(payload, "failure_modes", "verdict", _FAILURE_MODE_FIELDS, problems,
                optional=_ROW_OPTIONAL)
    _check_nested(payload, "risk", "verdict", _RISK_FIELDS, problems)
    _check_nested(payload, "intervention", "verdict", _INTERVENTION_FIELDS, problems)
    # Two levels, because the rows are the point: a block whose only structure check was
    # "is an object" would let `{"value": "true"}` through, and a console reading that
    # string sees a truthy guard whatever the monitor decided.
    _check_nested(payload, "phase_guards", "verdict", _PHASE_GUARDS_FIELDS, problems)
    guards = payload.get("phase_guards")
    if isinstance(guards, dict):
        _check_each(guards, "guards", "verdict.phase_guards", _PHASE_GUARD_FIELDS,
                    problems)
    return problems


# =============================================================================
# /monitor/adapter (latched) -- evaluator -> everyone
# =============================================================================

_STEP_FIELDS: dict[str, _Check] = {
    "keys": STRING_ARRAY,
    "aggregate": STRING,
    "threshold": NUMBER_OR_NULL,   # streak length, in units of `on`; null if none
    "on": STRING,
}

#: `threshold` was added after SCHEMA_VERSION 1 shipped. Making it required would have
#: been a wire break needing a version bump -- and would have invalidated the adapter
#: example in docs/api.md, which is fed to validate_adapter verbatim. Optional means a
#: producer that predates it still validates, while one that sends it is type-checked.
_STEP_OPTIONAL = ("threshold",)

_SOURCE_FIELDS: dict[str, _Check] = {
    "id": STRING,
    "topic": STRING,
    "type": STRING,
    "expected_hz": NUMBER,
    "max_age_s": NUMBER,
    "required": BOOL,
    "tracked": BOOL,
    "keys": STRING_ARRAY,
    "steps": OBJECT_ARRAY,
}

_ADAPTER_FIELDS: dict[str, _Check] = {
    **_PLAIN,
    "adapter": STRING,
    "doc": STRING,
    "tick_hz": NUMBER,
    "warnings": STRING_ARRAY,
    "schema": _string_keyed(OBJECT),
    "sources": OBJECT_ARRAY,
    # Topics a recording needs and the evaluator must never read: terrain, the
    # planner's paths, tf. It travels beside `sources` so that `ros2 bag record` gets
    # its line off the adapter the run declared -- see `adapter_spec.AdapterSpec.scene`
    # for why being a forbidden INPUT and being worth recording are different things.
    "scene": STRING_ARRAY,
}

#: `scene` arrived after SCHEMA_VERSION 1 shipped, so it is optional for the same reason
#: `state` is on a verdict row: required would be a wire break needing a version bump,
#: and every producer that predates it would become invalid for carrying nothing new.
#: The field set stays CLOSED, so `scene` still has to be declared above or an adapter
#: carrying it is rejected as an unknown field.
_ADAPTER_OPTIONAL = _PLAIN_OPTIONAL + ("scene",)


def build_adapter(
    *,
    adapter: str,
    doc: str,
    tick_hz: float,
    schema: dict,
    sources,
    warnings=(),
    scene=(),
    seq: int | None = None,
    t: float | None = None,
) -> dict:
    """What this robot can observe.

    Resolved values only. A `debounce_s` declared in a descriptor appears here as the
    integer tick threshold it resolved to, so the number exists in exactly one place and
    can be read straight off the wire.

    This is how the monitor validates a pushed spec without ever opening an adapter
    descriptor file, and how the frontend renders a sensor table for a robot it has
    never heard of.
    """
    return _plain_envelope(seq, t) | {
        "adapter": adapter,
        "doc": doc,
        "tick_hz": tick_hz,
        "warnings": list(warnings),
        "schema": dict(schema),
        "sources": list(sources),
        "scene": list(scene),
    }


def validate_adapter(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "adapter")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(payload, "adapter", _ADAPTER_FIELDS, problems,
                  optional=_ADAPTER_OPTIONAL)
    _check_version(payload, "adapter", problems)
    _check_each(payload, "sources", "adapter", _SOURCE_FIELDS, problems)

    sources = payload.get("sources")
    if isinstance(sources, list):
        for i, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            steps = source.get("steps")
            if isinstance(steps, list):
                for j, step in enumerate(steps):
                    if isinstance(step, dict):
                        _check_fields(
                            step, f"adapter.sources[{i}].steps[{j}]", _STEP_FIELDS,
                            problems, optional=_STEP_OPTIONAL,
                        )
            # A source that feeds a key the schema never declares is a descriptor bug
            # that would otherwise surface as a silently absent sensor field.
            schema = payload.get("schema")
            if isinstance(schema, dict) and isinstance(source.get("keys"), list):
                for key in source["keys"]:
                    if isinstance(key, str) and key not in schema:
                        problems.append(
                            f"adapter.sources[{i}]: key '{key}' is not declared in schema"
                        )
    return problems


# =============================================================================
# /monitor/manifest (latched) -- monitor -> everyone
# =============================================================================

#: One node of a Büchi automaton. `accepting` and `sink` are the two facts a client
#: needs to colour it; everything else about a state is derivable from the edges.
_AUTOMATON_STATE_FIELDS: dict[str, _Check] = {
    "id": INT,
    "accepting": BOOL,
    "sink": BOOL,
}

#: One transition. `label` is the edge's guard already rendered to a string by the
#: producer -- a BDD is not a wire type, and a consumer must never have to parse one.
_AUTOMATON_EDGE_FIELDS: dict[str, _Check] = {
    "from": INT,
    "to": INT,
    "label": STRING,
}

#: One entry of `manifest.automata` -- the graph the monitor of this `name` is stepping.
#: `name` is the join key: it matches `verdict.formulas[].name` or
#: `verdict.failure_modes[].name`, and `state` on that row indexes `states[].id` here.
_AUTOMATON_FIELDS: dict[str, _Check] = {
    "name": STRING,
    "formula": STRING,
    "initial": INT,
    "states": OBJECT_ARRAY,
    "edges": OBJECT_ARRAY,
}

_MANIFEST_FIELDS: dict[str, _Check] = {
    **_PLAIN,
    "skill_name": STRING,
    "phases": STRING_ARRAY,
    "source": STRING,
    # The Büchi automaton of every monitor this spec built. Structural, so it lives
    # here on the latched manifest -- one message per spec load -- and each tick then
    # carries only the `state` integer that indexes into it.
    "automata": OBJECT_ARRAY,
}

#: `automata` is optional, not required: a producer that cannot introspect its monitors
#: omits the field entirely rather than sending an empty list, because "no graph
#: available" and "this spec has no monitors" are different facts and a consumer that
#: draws an empty pane for the first one is reporting something untrue. Declared in
#: `_MANIFEST_FIELDS` all the same, so it is type-checked whenever it IS present --
#: the manifest validator is open (`closed=False`), so an undeclared field would
#: otherwise go through entirely unexamined.
_MANIFEST_OPTIONAL = ("automata",)


def phase_names(execution_phases) -> list:
    """Phase names in order, with a positional fallback for an unnamed phase."""
    if not isinstance(execution_phases, list):
        return []
    return [
        p.get("phase", f"phase{i}") if isinstance(p, dict) else f"phase{i}"
        for i, p in enumerate(execution_phases)
    ]


def validate_automata(payload: Any, label: str = "manifest") -> list[str]:
    """Problems with a `manifest.automata` block. Returns a list, never raises.

    Types are only half of it. A graph whose `initial` names a state that was never
    declared, or an edge that runs to one, is *well-typed nonsense*: it validates
    field by field and then draws as an empty or disconnected pane. The consumer has
    no way to tell that from a spec that genuinely has one state, so the mismatch has
    to be caught here, at the contract, and named -- not discovered as a blank panel.

    Three structural rules, and they are exactly the ones a renderer assumes:

      * every `states[].id` is unique -- a duplicate makes "the state numbered 3"
        ambiguous, and `verdict.formulas[].state` is nothing but that number;
      * `initial` is one of the declared ids -- otherwise there is no node to start at;
      * both endpoints of every edge are declared ids -- otherwise there is no node to
        draw the edge to.
    """
    if payload is None:
        return []
    if not isinstance(payload, list):
        return [f"{label}.automata: must be an array of objects, got {_kind(payload)}"]

    problems: list[str] = []
    for i, entry in enumerate(payload):
        where = f"{label}.automata[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be an object, got {_kind(entry)}")
            continue

        _check_fields(entry, where, _AUTOMATON_FIELDS, problems)
        _check_each(entry, "states", where, _AUTOMATON_STATE_FIELDS, problems)
        _check_each(entry, "edges", where, _AUTOMATON_EDGE_FIELDS, problems)

        # Ids first: everything below is a question about membership in this set. An
        # id that failed its own type check is skipped rather than reported twice.
        ids: set[int] = set()
        states = entry.get("states")
        if isinstance(states, list):
            for j, state in enumerate(states):
                if not isinstance(state, dict):
                    continue
                sid = state.get("id")
                if not _is_int(sid):
                    continue
                if sid in ids:
                    problems.append(f"{where}.states[{j}]: duplicate state id {sid}")
                ids.add(sid)

        initial = entry.get("initial")
        if _is_int(initial) and initial not in ids:
            problems.append(
                f"{where}: initial state {initial} is not a declared state"
            )

        edges = entry.get("edges")
        if isinstance(edges, list):
            for j, edge in enumerate(edges):
                if not isinstance(edge, dict):
                    continue
                for end in ("from", "to"):
                    node = edge.get(end)
                    if _is_int(node) and node not in ids:
                        problems.append(
                            f"{where}.edges[{j}]: '{end}' state {node} is not a "
                            f"declared state"
                        )
    return problems


def build_skill_manifest(
    *,
    spec: dict,
    source: str = "inline",
    automata=None,
    seq: int | None = None,
    t: float | None = None,
) -> dict:
    """The skill spec exactly as authored, plus `phases` and where it came from.

    Passed through rather than reassembled from parsed pieces: a client must see the
    document the engine was actually given, including fields this engine version does
    not itself understand. That is also why `validate_skill_manifest` is the one
    open validator here -- an unknown field is the point, not a problem.

    `automata` is the Büchi graph of every monitor the spec built (see
    `MultiMonitor.graphs`). None -- the default -- leaves the key OUT of the payload
    entirely rather than sending an empty list, because a producer that cannot
    introspect its monitors and a spec that declares no formulas are different facts,
    and a consumer must be able to tell them apart in order to degrade honestly.
    """
    # Spec first: the envelope must win, so a spec that happens to carry its own
    # `schema_version` cannot overwrite the wire version and misroute every consumer.
    payload = dict(spec or {}) | _plain_envelope(seq, t) | {
        "skill_name": (spec or {}).get("skill_name", ""),
        "phases": phase_names((spec or {}).get("execution_phases")),
        "source": source,
    }
    if automata is not None:
        payload["automata"] = list(automata)
    return payload


def validate_skill_manifest(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "manifest")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(
        payload, "manifest", _MANIFEST_FIELDS, problems,
        optional=_MANIFEST_OPTIONAL, closed=False,
    )
    _check_version(payload, "manifest", problems)
    # Only when it is a list: a non-list `automata` was just named by the type check
    # above, and saying it twice helps nobody.
    if isinstance(payload.get("automata"), list):
        problems += validate_automata(payload["automata"])
    return problems


# =============================================================================
# /monitor/command -- frontend -> monitor
# =============================================================================

_COMMAND_FIELDS: dict[str, _Check] = {
    **_PLAIN,
    "command": _one_of(COMMANDS),
}


def build_command(*, command: str, seq: int | None = None, t: float | None = None) -> dict:
    """`arm` | `reset` | `pause` | `resume`. `arm` and `reset` restart `step`."""
    return _plain_envelope(seq, t) | {"command": command}


def validate_command(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "command")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(payload, "command", _COMMAND_FIELDS, problems, optional=_PLAIN_OPTIONAL)
    _check_version(payload, "command", problems)
    return problems


# =============================================================================
# /monitor/status (latched) -- monitor -> everyone
# =============================================================================

_MONITOR_STATUS_FIELDS: dict[str, _Check] = {
    **_CLOCKED,
    "state": _one_of(RUN_STATES),
    "reason": STRING_OR_NULL,
    "since_seq": INT_OR_NULL,
}


def build_monitor_status(
    *,
    seq: int,
    t: float,
    state: str,
    reason: str | None = None,
    since_seq: int | None = None,
) -> dict:
    """Whether this monitor is watching, and if not, why not.

    The answer to a question every other topic on this wire answers only by omission. A
    monitor that is not stepping publishes no verdict, and a topic that is quiet when
    nothing is wrong cannot distinguish "calm" from "stopped a minute ago". That is
    already why the stall detector exists -- but a stall is an *inference* from silence,
    and it infers the same thing whether the monitor crashed or an operator pressed
    pause. This is the monitor stating it outright, which is the only version an
    operator can act on: a paused monitor means the robot is running unmonitored.

    Clocked rather than plain, unlike the other latched topics. `seq` and `t` are the
    clock reading when the frame was published, so a console can place a pause on the
    same axis as the verdicts either side of it.

    `since_seq` is when the state *began*, and it is not redundant with `seq`: a latched
    frame is arbitrarily old by the time a console receives it, so the length of a pause
    is `since_seq` against the *live* tick, not against this frame's own `seq`. That is
    what turns "paused" into "paused for four minutes" for a page that joined during
    minute three. On the frame announcing a transition the two are equal, which is the
    degenerate case and not the one the field exists for.

    `since_seq` is null before any clock has been seen: a monitor that has never been
    ticked cannot name a tick, and 0 would be a tick it is claiming to have counted.
    `reason` is null when there is nothing to say beyond the state itself.
    """
    return _clocked_envelope(seq, t) | {
        "state": state,
        "reason": reason,
        "since_seq": since_seq,
    }


def validate_monitor_status(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "monitor_status")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(payload, "monitor_status", _MONITOR_STATUS_FIELDS, problems)
    _check_version(payload, "monitor_status", problems)
    # A state that began after the frame announcing it is not a late clock reading, it
    # is arithmetic no console can render: "paused for -3 ticks".
    seq, since = payload.get("seq"), payload.get("since_seq")
    if _is_int(seq) and _is_int(since) and since > seq:
        problems.append(
            f"monitor_status: since_seq is {since}, after this frame's seq {seq}"
        )
    return problems


# =============================================================================
# /monitor/load_spec -> /monitor/spec_status (latched)
# =============================================================================

_LOAD_SPEC_FIELDS: dict[str, _Check] = {
    **_PLAIN,
    "spec": OBJECT,
    "source": STRING,
}

_SPEC_STATUS_FIELDS: dict[str, _Check] = {
    **_PLAIN,
    "ok": BOOL,
    "problems": STRING_ARRAY,
    "skill_name": STRING,
}


def build_load_spec(
    *, spec: dict, source: str = "pushed", seq: int | None = None, t: float | None = None
) -> dict:
    """A whole spec in.

    The spec is *wrapped* under `spec` rather than being the payload itself, because
    the envelope's `schema_version` describes the wire format and a spec document has
    its own versioning; merging the two would make an authored field collide with a
    transport field, and would also mean the manifest could no longer pass the spec
    through unaltered.
    """
    return _plain_envelope(seq, t) | {"spec": dict(spec), "source": source}


def validate_load_spec(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "load_spec")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(
        payload, "load_spec", _LOAD_SPEC_FIELDS, problems, optional=_PLAIN_OPTIONAL
    )
    _check_version(payload, "load_spec", problems)
    return problems


def build_spec_status(
    *,
    ok: bool,
    problems=(),
    skill_name: str = "",
    seq: int | None = None,
    t: float | None = None,
) -> dict:
    """The monitor's answer to a pushed spec.

    `problems` is the same human-readable list `spec_contract.validate()` returns, so
    the frontend renders one thing whether the spec was rejected structurally or
    against the schema last seen on `/monitor/adapter`. With no adapter on the graph
    only the structural half can be checked -- refusing every spec until an adapter
    appears would break offline replay.
    """
    return _plain_envelope(seq, t) | {
        "ok": ok,
        "problems": list(problems),
        "skill_name": skill_name,
    }


def validate_spec_status(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "spec_status")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(
        payload, "spec_status", _SPEC_STATUS_FIELDS, problems, optional=_PLAIN_OPTIONAL
    )
    _check_version(payload, "spec_status", problems)
    # ok=True with problems listed is contradictory, and a frontend showing a green
    # tick above a list of errors is worse than either alone.
    if payload.get("ok") is True and payload.get("problems"):
        problems.append("spec_status: ok is true but problems is not empty")
    return problems


# =============================================================================
# /monitor/raw_echo_request -> /monitor/raw_echo
# =============================================================================

_RAW_ECHO_REQUEST_FIELDS: dict[str, _Check] = {
    **_PLAIN,
    "source_id": STRING_OR_NULL,
}

_RAW_ECHO_FIELDS: dict[str, _Check] = {
    **_TICK_SCOPED,
    "source_id": STRING,
    "summary": OBJECT,
}


def build_raw_echo_request(
    *, source_id: str | None, seq: int | None = None, t: float | None = None
) -> dict:
    """Ask the evaluator to echo one source. `source_id=None` stops the echo.

    One at a time and opt-in, because a point cloud per frame is not free.
    """
    return _plain_envelope(seq, t) | {"source_id": source_id}


def validate_raw_echo_request(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "raw_echo_request")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(
        payload, "raw_echo_request", _RAW_ECHO_REQUEST_FIELDS, problems,
        optional=_PLAIN_OPTIONAL,
    )
    _check_version(payload, "raw_echo_request", problems)
    return problems


def build_raw_echo(
    *, seq: int, t: float, step: int | None, source_id: str, summary: dict
) -> dict:
    """A summary of one source's samples for one tick.

    Tick-scoped, so an echoed sample can be lined up against the observation folded
    from it. `summary` is deliberately opaque -- its shape is the adapter's business,
    and pinning it here would mean every new sensor type edits the wire contract.
    """
    return _tick_scoped_envelope(seq, t, step) | {
        "source_id": source_id,
        "summary": dict(summary),
    }


def validate_raw_echo(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "raw_echo")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(payload, "raw_echo", _RAW_ECHO_FIELDS, problems)
    _check_version(payload, "raw_echo", problems)
    return problems


# =============================================================================
# Dispatch by topic
# =============================================================================

# For the gateway (P6) and the frontend (P7), which route frames by topic name and
# should not carry their own topic -> validator table.
VALIDATORS: dict[str, Callable[[Any], list[str]]] = {
    TICK: validate_tick,
    OBSERVATION: validate_observation,
    VERDICT: validate_verdict,
    ADAPTER: validate_adapter,
    MANIFEST: validate_skill_manifest,
    COMMAND: validate_command,
    LOAD_SPEC: validate_load_spec,
    SPEC_STATUS: validate_spec_status,
    RAW_ECHO_REQUEST: validate_raw_echo_request,
    RAW_ECHO: validate_raw_echo,
    MONITOR_STATUS: validate_monitor_status,
}


def validate_for_topic(topic: str, payload: Any) -> list[str]:
    """Problems with `payload` as carried by `topic`; never raises.

    An unknown topic is itself a problem rather than a pass, so a typo'd topic name in
    a recorded bag is reported instead of silently validating against nothing.
    """
    validator = VALIDATORS.get(topic)
    if validator is None:
        return [f"unknown topic {topic!r}; expected one of {sorted(TOPICS)}"]
    return validator(payload)
