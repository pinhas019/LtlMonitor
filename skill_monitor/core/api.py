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

TOPICS = frozenset({
    TICK, OBSERVATION, VERDICT, ADAPTER, MANIFEST,
    COMMAND, LOAD_SPEC, SPEC_STATUS, RAW_ECHO_REQUEST, RAW_ECHO,
})

# Published TRANSIENT_LOCAL, depth 1, reliable. A client that connects mid-mission gets
# the last value immediately instead of waiting for a change that may never come --
# which for a manifest or an adapter descriptor is "never", since they are published
# once at startup.
LATCHED_TOPICS = frozenset({ADAPTER, MANIFEST, SPEC_STATUS})

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

# core.monitor_action.Action, ordered. The monitor decides the rung; the supervisor
# only enforces it.
INTERVENTION_ACTIONS = ("CONTINUE", "WARN", "SLOW", "REPLAN", "HALT", "ABORT")

COMMANDS = ("arm", "reset", "pause", "resume")

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

    `closed` off means the payload legitimately carries fields this engine version
    does not understand -- the skill manifest, which is passed through as authored.
    """
    for name, (pred, expected) in fields.items():
        if name not in payload:
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


def build_tick(*, seq: int, t: float, tick_hz: float, mode: str = "wall",
               t0: float = 0.0) -> dict:
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
}

_FAILURE_MODE_FIELDS: dict[str, _Check] = {
    "name": STRING,
    "fault_category": _one_of(FAULT_CATEGORIES),
    "status": _one_of(FORMULA_STATUSES),
    # Required, not optional. Without it a VIOLATED derived from a dead sensor grades
    # at 1.0 and the intervention ladder goes straight to ABORT.
    "confidence": UNIT_INTERVAL,
}

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
    # Pulses the monitor did not see. Logged, never interpolated.
    "missed_ticks": INT,
}


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
) -> dict:
    """Exactly once per tick.

    `intervention.action` is one rung of CONTINUE < WARN < SLOW < REPLAN < HALT < ABORT.
    The monitor decides it here; the supervisor only enforces what it is handed, so the
    decision is in the recorded stream rather than in the actuating process.
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
    }


def build_formula(*, name: str, status: str) -> dict:
    """One entry of `verdict.formulas`."""
    return {"name": name, "status": status}


def build_failure_mode(
    *, name: str, fault_category: str, status: str, confidence: float
) -> dict:
    """One entry of `verdict.failure_modes`. `confidence` has no default on purpose."""
    return {
        "name": name,
        "fault_category": fault_category,
        "status": status,
        "confidence": confidence,
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
    _check_fields(payload, "verdict", _VERDICT_FIELDS, problems)
    _check_version(payload, "verdict", problems)
    _check_each(payload, "formulas", "verdict", _FORMULA_FIELDS, problems)
    _check_each(payload, "failure_modes", "verdict", _FAILURE_MODE_FIELDS, problems)
    _check_nested(payload, "risk", "verdict", _RISK_FIELDS, problems)
    _check_nested(payload, "intervention", "verdict", _INTERVENTION_FIELDS, problems)
    return problems


# =============================================================================
# /monitor/adapter (latched) -- evaluator -> everyone
# =============================================================================

_STEP_FIELDS: dict[str, _Check] = {
    "keys": STRING_ARRAY,
    "aggregate": STRING,
    "on": STRING,
}

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
}


def build_adapter(
    *,
    adapter: str,
    doc: str,
    tick_hz: float,
    schema: dict,
    sources,
    warnings=(),
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
    }


def validate_adapter(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "adapter")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(payload, "adapter", _ADAPTER_FIELDS, problems, optional=_PLAIN_OPTIONAL)
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
                            problems,
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

_MANIFEST_FIELDS: dict[str, _Check] = {
    **_PLAIN,
    "skill_name": STRING,
    "phases": STRING_ARRAY,
    "source": STRING,
}


def phase_names(execution_phases) -> list:
    """Phase names in order, with a positional fallback for an unnamed phase."""
    if not isinstance(execution_phases, list):
        return []
    return [
        p.get("phase", f"phase{i}") if isinstance(p, dict) else f"phase{i}"
        for i, p in enumerate(execution_phases)
    ]


def build_skill_manifest(
    *, spec: dict, source: str = "inline", seq: int | None = None, t: float | None = None
) -> dict:
    """The skill spec exactly as authored, plus `phases` and where it came from.

    Passed through rather than reassembled from parsed pieces: a client must see the
    document the engine was actually given, including fields this engine version does
    not itself understand. That is also why `validate_skill_manifest` is the one
    open validator here -- an unknown field is the point, not a problem.
    """
    # Spec first: the envelope must win, so a spec that happens to carry its own
    # `schema_version` cannot overwrite the wire version and misroute every consumer.
    return dict(spec or {}) | _plain_envelope(seq, t) | {
        "skill_name": (spec or {}).get("skill_name", ""),
        "phases": phase_names((spec or {}).get("execution_phases")),
        "source": source,
    }


def validate_skill_manifest(payload: Any) -> list[str]:
    if (bad := _not_an_object(payload, "manifest")) is not None:
        return bad
    problems: list[str] = []
    _check_fields(payload, "manifest", _MANIFEST_FIELDS, problems, closed=False)
    _check_version(payload, "manifest", problems)
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
