"""The monitor's pure half: what a client reads about a running monitor, and how one
tick becomes one verdict.

Two latched topics carry everything a client needs, and neither requires importing this
package:

    api.MANIFEST    the skill: spec as authored, plus phase names and where it came from
    api.ADAPTER     the robot: sensor schema and which topic feeds which key

and the per-tick api.VERDICT carries the live part (phase, formula statuses, failure
modes, risk, and the intervention rung). A GUI that reads these three is agnostic to
skill AND to embodiment: it renders what it is told exists.

ROS-free on purpose. `monitor_node` needs `rclpy` and cannot be imported on a laptop, so
everything that can be decided without a graph is decided here and the node is a thin
wrapper over it: the tick ledger, the observation normaliser, and the verdict builder are
all plain functions over plain dicts, and `tests/test_manifest.py` exercises them without
starting anything.

Three things this module refuses to do:

  * **Invent a payload shape.** Every dict that goes on the wire is built by a
    `core.api` builder, so the field names exist in one place.
  * **Re-decide the intervention.** `supervisor_logic.decide_intervention` is the pure
    grading library; the monitor calls it so the rung it records is bit-identical to the
    rung the supervisor used to compute for itself.
  * **Merge or interpolate a tick.** A gap in `seq` is reported as a gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import skill_monitor
from skill_monitor.core import api
from skill_monitor.core.monitor_action import grade_action
from skill_monitor.core.supervisor_logic import decide_intervention

# Read off `grade_action`'s own signature rather than copied. The horizon is declared
# once, in the function that uses it; a fourth literal `3` in this file is exactly the
# drift P5 is unifying away. When P5 promotes it to a named constant, this line becomes
# an import of that name.
WARN_STEPS: int = grade_action.__kwdefaults__["warn_steps"]
MIN_CONFIDENCE: float = grade_action.__kwdefaults__["min_confidence"]

#: Default consecutive-step limit before a phase progress failure.
PHASE_VIOLATION_LIMIT = 3


# =============================================================================
# The manifest
# =============================================================================

#: Phase names in order, with a positional fallback for an unnamed phase.
#: Delegated rather than reimplemented: P0 wrote its own copy in `api` to avoid
#: depending on a file another branch was editing, and two copies of "what is a phase
#: called" is one too many.
phase_names = api.phase_names


def skill_manifest(raw_spec: dict, source: str = "inline") -> dict:
    """The api.MANIFEST payload for a spec.

    The spec is passed through as authored rather than reassembled from parsed pieces --
    a client should see exactly the document the engine was given, including any field
    this engine version does not itself understand.
    """
    return api.build_skill_manifest(spec=raw_spec or {}, source=source)


def ap_rows(manifest: dict, state: dict) -> list:
    """One row per atomic proposition: (name, value, description).

    `value` is True/False from the monitor's last observation, or None when the AP
    is not currently required (phases only evaluate the APs they need, so an absent
    AP means "not asked", never "false").
    """
    values = (state or {}).get("ap_values") or {}
    aps = (manifest or {}).get("atomic_propositions") or {}
    return [(name, values.get(name), desc) for name, desc in sorted(aps.items())]


def sensor_rows(adapter: dict, state: dict) -> list:
    """One row per sensor field: (key, value, doc). Driven by the adapter's schema,
    so a robot with entirely different fields renders with no code change."""
    values = (state or {}).get("sensors") or {}
    schema = (adapter or {}).get("schema") or {}
    keys = sorted(set(schema) | set(values))
    return [(k, values.get(k), (schema.get(k) or {}).get("doc", "")) for k in keys]


# =============================================================================
# Where the spec comes from
# =============================================================================

def resolve_spec_path(value) -> Path:
    """The file a `--formulas-file` argument names.

    The compose files pass a **bare name** (`formulas_g1.json`), not a path, so the
    lookup goes through `skill_monitor.spec_path()` and resolves against the mounted
    /config volume first and the packaged specs second. Treating the flag as a plain
    path -- which it was -- makes a containerised monitor fail to find a spec that is
    sitting in its own image.

    An argument that already names an existing file still wins, so a developer can
    point at a scratch spec anywhere on disk.
    """
    given = Path(value)
    if given.exists():
        return given
    return skill_monitor.spec_path(str(value))


# =============================================================================
# One step per tick
# =============================================================================

@dataclass(frozen=True)
class Admission:
    """What the ledger decided about an arriving tick index.

    `step` is the only thing the node acts on; the rest exists so the decision is
    loggable. A rejected tick that silently vanishes is the bug this type prevents.
    """

    step: bool
    seq: int
    missed: int
    reason: str  # first | advanced | redelivered | stale | implicit


class TickLedger:
    """Which `seq` has been stepped, and which pulses were never seen.

    The received tick index is authoritative. The evaluator publishes from a worker
    thread behind a queue, so message *arrival* order says nothing about which tick a
    payload describes: driving the automaton off arrival means that under model backlog
    tick N's automaton is stepped against tick N-k's observation, with nothing in the
    record to say so, and every `max_steps` bound stretches silently.

    So: one step per distinct, advancing `seq`. A repeat is refused outright -- a
    redelivered tick must not advance a debounce or a phase counter twice. A gap is
    counted and published in `missed_ticks`, never interpolated and never merged into a
    single catch-up step: a monitor that fabricates the observations it did not receive
    is worse than one that admits the hole.
    """

    def __init__(self) -> None:
        self.last_seq: int | None = None
        #: Gaps since the last verdict was published; the node clears this per tick.
        self.missed: int = 0
        #: Every gap since the ledger was reset -- the run-level number.
        self.total_missed: int = 0
        #: Ticks refused because they had already been stepped.
        self.redelivered: int = 0

    def reset(self) -> None:
        """A new episode. The seq stream is global and does not restart with it, so
        `last_seq` is deliberately kept: a reset must not make a stale redelivery
        look like a fresh tick."""
        self.missed = 0

    def admit(self, seq) -> Admission:
        """Decide whether `seq` may step the automaton, and count what was skipped.

        A payload with no usable `seq` -- every legacy `/ltl/evaluations` message, which
        predates the envelope -- is given the next implicit index, so the legacy stack
        keeps its arrival-driven behaviour exactly and still gets a verdict.
        """
        if not isinstance(seq, int) or isinstance(seq, bool):
            implicit = 0 if self.last_seq is None else self.last_seq + 1
            self.last_seq = implicit
            self.missed = 0
            return Admission(True, implicit, 0, "implicit")

        if self.last_seq is None:
            self.last_seq = seq
            self.missed = 0
            return Admission(True, seq, 0, "first")

        if seq == self.last_seq:
            self.redelivered += 1
            return Admission(False, seq, 0, "redelivered")

        if seq < self.last_seq:
            # Out of order, i.e. a tick the automaton has already moved past. It cannot
            # be applied without rewinding state the automaton has no undo for.
            self.redelivered += 1
            return Admission(False, seq, 0, "stale")

        missed = seq - self.last_seq - 1
        self.last_seq = seq
        self.missed = missed
        self.total_missed += missed
        return Admission(True, seq, missed, "advanced")


# =============================================================================
# The observation, from either wire
# =============================================================================

@dataclass(frozen=True)
class Observation:
    """One tick's worth of evidence, normalised out of whichever wire it arrived on."""

    ap_values: dict = field(default_factory=dict)
    sensors: dict = field(default_factory=dict)
    confidence: float = 1.0
    stale_sources: tuple = ()
    unknown_aps: tuple = ()
    seq: int | None = None
    t: float | None = None
    step: int | None = None
    #: `done` | `reset` | None -- the legacy in-band control keys.
    control: str | None = None
    legacy: bool = False

    @property
    def has_data(self) -> bool:
        """False when nothing could be evaluated this tick.

        This is what makes the top-level verdict `INCONCLUSIVE_NO_DATA`, which is a
        different axis from a formula's own `INCONCLUSIVE`: the latter is the normal
        state of a healthy run.
        """
        return bool(self.ap_values)


def normalize_observation(payload) -> Observation | None:
    """An `Observation` from either an api.OBSERVATION or a legacy `/ltl/evaluations`
    payload, or None if it is not an object at all.

    The two shapes are told apart by `ap_values`, which the envelope always carries and
    the legacy flat dict never did. The legacy branch dies with the legacy subscription,
    when P3 lands.
    """
    if not isinstance(payload, dict):
        return None

    if "ap_values" in payload:
        health = payload.get("data_health")
        stale = ()
        if isinstance(health, dict):
            stale = tuple(sorted(
                sid for sid, entry in health.items()
                if isinstance(entry, dict) and not entry.get("refreshed", True)
            ))
        aps = payload.get("ap_values")
        sensors = payload.get("sensors")
        return Observation(
            ap_values=dict(aps) if isinstance(aps, dict) else {},
            sensors=dict(sensors) if isinstance(sensors, dict) else {},
            confidence=_unit(payload.get("confidence", 1.0)),
            stale_sources=stale,
            unknown_aps=tuple(payload.get("unknown_aps") or ()),
            seq=payload.get("seq"),
            t=payload.get("t"),
            step=payload.get("step"),
            control=None,
            legacy=False,
        )

    # Legacy: a flat AP dict with reserved `__dunder__` metadata alongside it. The
    # reserved keys are metadata *about* the observation, not part of it, and are
    # stripped here so they can never reach a phase guard's eval namespace.
    control = None
    if payload.get("__done__"):
        control = "done"
    elif payload.get("__reset__"):
        control = "reset"
    return Observation(
        ap_values={k: bool(v) for k, v in payload.items() if not k.startswith("__")},
        sensors=dict(payload.get("__sensors__") or {}),
        confidence=_unit(payload.get("__confidence__", 1.0)),
        stale_sources=tuple(payload.get("__stale__") or ()),
        unknown_aps=(),
        seq=None,
        t=None,
        step=None,
        control=control,
        legacy=True,
    )


def _unit(value) -> float:
    """A confidence clamped into [0.0, 1.0]; 1.0 for anything unreadable.

    Clamped rather than passed through: `api.UNIT_INTERVAL` rejects 1.2, and a verdict
    that fails its own validator because a producer sent a stray number is a worse
    outcome than a verdict that reports full confidence.
    """
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


# =============================================================================
# The verdict
# =============================================================================

#: Categories that mean the same thing as one of api.FAULT_CATEGORIES under another
#: name. A precondition that did not hold on entry is the world not being as the spec
#: required -- the same unrecoverable shape as a broken invariant.
_CATEGORY_ALIASES = {"PRECONDITION": "INVARIANT"}

#: Spellings that mean "no fault category", not "a category I do not recognise".
_NO_CATEGORY = {"", "NONE", "NULL", "-"}

#: What an unrecognised category becomes on the wire. `fault_category` is a closed
#: vocabulary, so something must be chosen; the conservative reading is that a fault
#: nobody could classify is not thereby a mild one.
UNCLASSIFIED_CATEGORY = "INVARIANT"


def wire_fault_category(category) -> str | None:
    """A spec's authored fault category as one of `api.FAULT_CATEGORIES`, or None.

    None means the spec said there is no category here (a `precondition_fault_category`
    of `"NONE"` in the shipped G1 spec), which `api.build_intervention` accepts and
    `grade_action` reads as CONTINUE.
    """
    if category is None:
        return None
    text = str(category).strip().upper()
    if text in _NO_CATEGORY:
        return None
    text = _CATEGORY_ALIASES.get(text, text)
    return text if text in api.FAULT_CATEGORIES else UNCLASSIFIED_CATEGORY


def _status_name(status) -> str:
    """`MonitorStatus.VIOLATED` or the string `"VIOLATED"`, either way."""
    name = getattr(status, "name", None) or str(status)
    return name if name in api.FORMULA_STATUSES else "INCONCLUSIVE"


def formula_entries(statuses) -> list[dict]:
    """`verdict.formulas` from (name, status) pairs."""
    return [
        api.build_formula(name=str(name), status=_status_name(status))
        for name, status in statuses
    ]


def failure_mode_entries(modes, confidence: float) -> list[dict]:
    """`verdict.failure_modes`, every entry carrying a `confidence`.

    This closes a live bug rather than adding a field. The supervisor's VIOLATED branch
    reads `violated.get("confidence", 1.0)`, and the entries were built without the key
    -- so a `fell_over` derived from a sensor that stopped publishing graded at full
    confidence and went straight to ABORT, with the de-escalation path that exists for
    exactly this case never taken.

    The confidence is the observation's: it is the freshness of the data the automaton
    stepped on, and a failure mode is only ever as believable as the tick that produced
    it.
    """
    out = []
    for mode in modes or []:
        out.append(api.build_failure_mode(
            name=str(mode.get("name", "")),
            fault_category=(
                wire_fault_category(mode.get("fault_category")) or UNCLASSIFIED_CATEGORY
            ),
            status=_status_name(mode.get("status")),
            confidence=_unit(confidence),
        ))
    return out


def risk_block(
    *,
    steps_to_timeout: int | None,
    violations_to_fault: int | None,
    confidence: float,
    stale_sources=(),
    tick_hz: float = 1.0,
    violations_seen: int = 0,
    warn_steps: int = WARN_STEPS,
) -> dict:
    """`verdict.risk` -- how close the run is to a bound, and how much to believe it.

    `seconds_to_timeout` ships **beside** `steps_to_timeout` and never replaces it. Spec
    bounds are tick-denominated until P11, and a consumer asserting on the existing
    field has to keep working; the seconds are a convenience derived from the effective
    `tick_hz` off the pulse, not a second source of truth.
    """
    warn_timeout = steps_to_timeout is not None and steps_to_timeout <= warn_steps
    warn_progress = (
        violations_seen > 0
        and violations_to_fault is not None
        and violations_to_fault <= warn_steps
    )
    seconds = None
    if steps_to_timeout is not None and isinstance(tick_hz, (int, float)) and tick_hz > 0:
        seconds = steps_to_timeout / float(tick_hz)
    return api.build_risk(
        steps_to_timeout=steps_to_timeout,
        seconds_to_timeout=seconds,
        violations_to_fault=violations_to_fault,
        warn=bool(warn_timeout or warn_progress),
        severity="TIMEOUT" if warn_timeout else ("PROGRESS" if warn_progress else None),
        trigger_confidence=_unit(confidence),
        stale_sources=list(stale_sources),
    )


def _imminence_label(steps: int | None) -> str | None:
    """`imminence` is a string on the wire, so the count is rendered rather than sent."""
    if steps is None:
        return None
    if steps <= 0:
        return "now"
    return f"{steps} step" + ("" if steps == 1 else "s")


def intervention_block(
    *,
    failure_modes,
    risk: dict,
    min_confidence: float = MIN_CONFIDENCE,
    warn_steps: int = WARN_STEPS,
) -> dict:
    """`verdict.intervention` -- the rung, and the evidence that chose it.

    The decision moves here from the enforcing node. Deciding it in the actuator put
    policy in the last process that should hold any, and left the choice out of the
    recorded stream: the verdict said what was wrong, and only the robot's behaviour
    said what was done about it.

    `decide_intervention` is called rather than reimplemented so the rung recorded here
    is provably the rung the supervisor used to compute for itself -- P5's node stops
    calling it, but it stays the one definition of the ladder's precedence.
    """
    decision = decide_intervention(
        {"named_failure_modes": list(failure_modes), "risk": dict(risk)},
        min_confidence=min_confidence,
        warn_steps=warn_steps,
    )
    # Which branch fired, re-read from the decision rather than re-derived: a breached
    # failure mode is named, a predictive risk names its own severity.
    breached = next(
        (fm for fm in failure_modes if fm.get("name") == decision.reason), None
    )
    if breached is not None:
        confidence = _unit(breached.get("confidence", 1.0))
        imminence = _imminence_label(0)  # already violated
    else:
        confidence = _unit(risk.get("trigger_confidence", 1.0))
        steps = risk.get("steps_to_timeout")
        if steps is None:
            steps = risk.get("violations_to_fault")
        imminence = _imminence_label(steps) if risk.get("severity") else None
    return api.build_intervention(
        action=decision.action.name,
        category=wire_fault_category(decision.category),
        imminence=imminence,
        confidence=confidence,
    )


def verdict_word(*, formulas, failure_modes, has_data: bool) -> str:
    """The top-level `verdict`.

    `INCONCLUSIVE_NO_DATA` is a *different axis* from a formula's `INCONCLUSIVE`, which
    is why `MonitorStatus` is not extended to hold it: "the prefix neither proves nor
    refutes" is the normal state of a healthy run, whereas "nothing arrived" is a
    statement about the sensors. Both travel, in different fields.

    A permanent violation outranks a silent tick: it is already proven and no later
    absence of data unproves it.
    """
    everything = list(formulas) + list(failure_modes)
    if any(e.get("status") == "VIOLATED" for e in everything):
        return "VIOLATED"
    if not has_data:
        return "INCONCLUSIVE_NO_DATA"
    if formulas and all(e.get("status") == "ACCEPTED" for e in formulas):
        return "SATISFIED"
    return "UNDECIDED"


def build_verdict_payload(
    *,
    seq: int,
    t: float,
    step: int | None,
    skill_name: str,
    phase: str | None,
    phase_index: int | None,
    formula_statuses=(),
    failure_modes=(),
    confidence: float = 1.0,
    stale_sources=(),
    steps_to_timeout: int | None = None,
    violations_to_fault: int | None = None,
    violations_seen: int = 0,
    tick_hz: float = 1.0,
    terminal: str | None = None,
    missed_ticks: int = 0,
    has_data: bool = True,
    min_confidence: float = MIN_CONFIDENCE,
    warn_steps: int = WARN_STEPS,
) -> dict:
    """The whole api.VERDICT payload for one tick, from plain values.

    Everything the node knows goes in and a validated payload comes out, so the node
    itself holds no field names: `tests/test_manifest.py` can build a verdict for any
    situation without `rclpy`, and `api.validate_verdict` judges the same bytes the
    supervisor and the frontend will read.
    """
    formulas = formula_entries(formula_statuses)
    modes = failure_mode_entries(failure_modes, confidence)
    risk = risk_block(
        steps_to_timeout=steps_to_timeout,
        violations_to_fault=violations_to_fault,
        confidence=confidence,
        stale_sources=stale_sources,
        tick_hz=tick_hz,
        violations_seen=violations_seen,
        warn_steps=warn_steps,
    )
    return api.build_verdict(
        seq=seq,
        t=t,
        step=step,
        skill_name=skill_name,
        phase=phase,
        phase_index=phase_index,
        verdict=verdict_word(
            formulas=formulas, failure_modes=modes, has_data=has_data
        ),
        formulas=formulas,
        failure_modes=modes,
        terminal=terminal,
        risk=risk,
        intervention=intervention_block(
            failure_modes=modes,
            risk=risk,
            min_confidence=min_confidence,
            warn_steps=warn_steps,
        ),
        missed_ticks=missed_ticks,
    )
