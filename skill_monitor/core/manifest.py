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

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import skill_monitor
from skill_monitor.core import api, spec_contract
from skill_monitor.core.monitor_action import Action, grade_action
from skill_monitor.core.supervisor_logic import SAFETY_CATEGORIES, decide_intervention

# The predictive horizon and the de-escalation floor of the intervention ladder.
#
# These used to be read off `grade_action.__kwdefaults__` so the number was declared
# once. That is an import-time landmine: `__kwdefaults__` is None for a function with
# no keyword-only defaults, so moving `warn_steps` in front of the `*` in that
# signature raises TypeError while *importing this module* -- taking the node, the
# panel, the ablation runner and test collection down with it, for an edit that changed
# nothing about the ladder.
#
# The one-definition property belongs in `core/monitor_action.py`, as module constants
# that `grade_action` defaults to. P5 owns that file, so until it lands the numbers are
# spelled here and `test_the_ladder_horizon_is_not_two_numbers` fails the moment the
# two disagree -- a red test rather than an unimportable package.
WARN_STEPS: int = 3
MIN_CONFIDENCE: float = 0.5

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
    reason: str  # first | advanced | redelivered | stale | implicit | epoch


def tick_epoch(tick) -> float | None:
    """The clock's restart discriminator off a `/monitor/tick` payload, or None.

    `t0` is the clock's own start time (`GET /api/clock` reports it beside `seq`), so a
    clock that restarts republishes from `seq` 0 with a *different* `t0`. That is the
    only non-heuristic way to tell "the clock restarted" from "a stale message arrived
    late", and the size of the backwards jump is emphatically not one.

    Tolerant of its absence: P1 may land after this, and a clock that never sends `t0`
    simply has one epoch forever -- which is the behaviour this monitor already had.

    A non-finite `t0` is *no* epoch, not a strange one. `nan != nan`, so a NaN adopted
    as the epoch compares unequal to itself on every subsequent pulse: the monitor
    declares a clock restart every tick, the ledger drops `last_seq` every tick, and
    one-step-per-tick silently becomes one-step-per-message -- redeliveries and
    backwards jumps included, with `redelivered` reading 0 so nothing says so. It is
    reachable rather than theoretical: `json.dumps(float("nan"))` emits bare `NaN` and
    `json.loads` accepts it, so a clock with an uninitialised `t0` round-trips intact.
    """
    if not isinstance(tick, dict):
        return None
    t0 = tick.get("t0")
    if isinstance(t0, bool) or not isinstance(t0, (int, float)):
        return None
    if not math.isfinite(t0):
        return None
    return float(t0)


#: The one problem in `api.validate_tick`'s output that a *newer* clock legitimately
#: causes. See `tick_problems_that_matter`.
_UNKNOWN_FIELD = "unknown field"


def tick_problems_that_matter(problems) -> list[str]:
    """`api.validate_tick`'s problems, minus the ones a newer clock legitimately causes.

    `api` closes the tick payload, so the `t0` P1 is adding reads as
    `tick: unknown field 't0'` -- and a monitor that drops a pulse for that reason goes
    deaf to a clock one release ahead of it, which is exactly the failure `t0` exists
    to prevent. An unknown field is the one problem that is safe to carry: every field
    this build reads was checked by name, and the extra one is simply not read.
    """
    return [p for p in (problems or ()) if _UNKNOWN_FIELD not in p]


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

    **Within one epoch.** "Backwards means already stepped" holds only while the clock
    that numbered the ticks kept running. A clock container that restarts republishes
    from `seq` 0, and a ledger that knew only about `seq` refused every one of them as
    stale -- zero verdicts for the rest of the process's life, and `reset()` kept
    `last_seq` so an operator could not recover it either. `epoch` is the clock's own
    `t0`: a changed one is a new tick stream, the ledger starts over and the monitor
    keeps stepping. An absent one (a clock that predates `t0`) means one epoch forever,
    which is exactly the behaviour above.

    The residual, stated rather than engineered away: the epoch is carried on
    `/monitor/tick` and the `seq` on `/monitor/observation`, so an observation from the
    old epoch that arrives after the new clock's first pulse is adopted as the new
    epoch's first tick. It costs the ticks between that index and the restart, once, on
    a restart -- against going deaf permanently, which is what it replaces.
    """

    def __init__(self) -> None:
        self.last_seq: int | None = None
        #: The clock's `t0` for the stream `last_seq` belongs to. See `tick_epoch`.
        self.epoch: float | None = None
        #: Gaps since the last verdict was published; the node clears this per tick.
        self.missed: int = 0
        #: Every gap since the ledger was reset -- the run-level number.
        self.total_missed: int = 0
        #: Ticks refused because they had already been stepped.
        self.redelivered: int = 0
        #: Ticks admitted with a fabricated index, i.e. off the legacy wire.
        self.implicit: int = 0
        #: Clock restarts adopted.
        self.epochs: int = 0
        # The fabricated index counts separately from `last_seq` on purpose -- see
        # `admit`.
        self._implicit_seq: int | None = None

    def reset(self) -> None:
        """A new episode.

        The seq stream is global and does not restart with the episode, so `last_seq`
        and `epoch` are deliberately kept: a reset must not make a stale redelivery look
        like a fresh tick. Everything counted *per run* -- gaps, refusals, fabricated
        indices -- is cleared, because that is what "since the ledger was reset" means
        in the attribute docs above and a run-level number that survives its run is
        being read by somebody as this run's.
        """
        self.missed = 0
        self.total_missed = 0
        self.redelivered = 0
        self.implicit = 0
        self._implicit_seq = None

    def admit(self, seq, *, epoch: float | None = None) -> Admission:
        """Decide whether `seq` may step the automaton, and count what was skipped.

        `epoch` is the clock's `t0`. A change in it is a clock restart: the ledger
        starts over rather than refusing the restarted stream as stale. None means the
        caller does not know, which leaves the ledger in whatever epoch it was in.

        A payload with no usable `seq` -- every legacy `/ltl/evaluations` message, which
        predates the envelope -- is given the next implicit index, so the legacy stack
        keeps its arrival-driven behaviour exactly and still gets a verdict. That index
        is counted *separately* from `last_seq`: sharing the counter meant one legacy
        copy of tick N fabricated `last_seq + 1`, and the real envelope for tick N+1
        then arrived looking redelivered. Two live wires, and only the fabricated one
        advancing.
        """
        new_epoch = False
        if epoch is not None:
            if self.epoch is not None and epoch != self.epoch:
                new_epoch = True
                self.epochs += 1
                self.last_seq = None
                self._implicit_seq = None
                self.missed = 0
            self.epoch = epoch

        if not isinstance(seq, int) or isinstance(seq, bool):
            self._implicit_seq = (
                0 if self._implicit_seq is None else self._implicit_seq + 1
            )
            self.implicit += 1
            self.missed = 0
            return Admission(True, self._implicit_seq, 0, "implicit")

        if self.last_seq is None:
            self.last_seq = seq
            self.missed = 0
            return Admission(True, seq, 0, "epoch" if new_epoch else "first")

        if seq == self.last_seq:
            self.redelivered += 1
            return Admission(False, seq, 0, "redelivered")

        if seq < self.last_seq:
            # Out of order *within this epoch*, i.e. a tick the automaton has already
            # moved past. It cannot be applied without rewinding state the automaton
            # has no undo for. A restarted clock is not this case: it arrives with a
            # new epoch and is handled above.
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

#: What a category this build does not recognise becomes on the wire.
#:
#: `fault_category` is closed on `verdict.failure_modes` -- there is no null and no
#: passthrough -- so *something* has to be chosen, and the choice must not be able to
#: stop the robot. It used to be INVARIANT, which meant a spec typo ("SAFTEY") graded
#: ABORT where pre-PR it graded WARN, and `build_failure_mode_infos` defaults a missing
#: field to "UNKNOWN" so it fired on any spec that omits it at all. `core/automata.py`
#: documents "NAVIGATION" as an example category, so a name this vocabulary lacks is an
#: expected input, not a corrupt one.
#:
#: PROGRESS is the mildest rung the vocabulary offers: `grade_action` takes an
#: already-breached PROGRESS to REPLAN, which is below HALT, so an unclassifiable fault
#: is reported and re-planned rather than actuated on. The loudness moved to
#: `fault_category_problems`, which rejects the spec at load, where the author can
#: still see the name they mistyped.
UNCLASSIFIED_CATEGORY = "PROGRESS"


def recognised_fault_category(category) -> bool:
    """Whether `wire_fault_category` maps this spelling by knowing it, rather than by
    giving up on it. `"PROGRESS"` and an unrecognised name produce the same wire value,
    so the two cannot be told apart after the fact -- which is why this exists."""
    if category is None:
        return True
    text = str(category).strip().upper()
    if text in _NO_CATEGORY:
        return True
    return _CATEGORY_ALIASES.get(text, text) in api.FAULT_CATEGORIES


def wire_fault_category(category) -> str | None:
    """A spec's authored fault category as one of `api.FAULT_CATEGORIES`, or None.

    None means the spec said there is no category here (a `precondition_fault_category`
    of `"NONE"` in the shipped G1 spec), which `api.build_intervention` accepts and
    `grade_action` reads as CONTINUE. Note that the null survives only where the wire
    admits one: `verdict.intervention.category` is nullable and
    `verdict.failure_modes[].fault_category` is not, so on a failure-mode entry "NONE"
    ships as `UNCLASSIFIED_CATEGORY` -- non-halting, but not null.
    """
    if category is None:
        return None
    text = str(category).strip().upper()
    if text in _NO_CATEGORY:
        return None
    text = _CATEGORY_ALIASES.get(text, text)
    return text if text in api.FAULT_CATEGORIES else UNCLASSIFIED_CATEGORY


#: Where a spec may author a fault category, and what the field is called there.
_CATEGORY_FIELDS = (
    ("named_failure_modes", "fault_category"),
    ("execution_phases", "invariant_fault_category"),
    ("execution_phases", "precondition_fault_category"),
)


def fault_category_problems(spec) -> list[str]:
    """Human-readable problems with a spec's authored fault categories.

    Same shape and same purpose as `spec_contract.validate()`'s list, and fed into the
    same `/monitor/spec_status`: a category this build cannot classify is graded to a
    non-halting rung at runtime, so if it is *not* also reported at load the spec runs
    with a fault the monitor will never act on and nobody was told. Naming it here puts
    the message where the author can still fix it.

    (It lives in this module rather than in `spec_contract` only because P4 owns this
    file and not that one -- it belongs beside `validate_structure`.)
    """
    problems: list[str] = []
    for section, field_name in _CATEGORY_FIELDS:
        entries = (spec or {}).get(section)
        if not isinstance(entries, list):
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            label = entry.get("name") or entry.get("phase") or f"{section}[{i}]"
            if field_name not in entry:
                if section == "named_failure_modes":
                    problems.append(
                        f"named failure mode '{label}' declares no {field_name}; "
                        f"it grades as {UNCLASSIFIED_CATEGORY} and will not halt. "
                        f"Expected one of {sorted(api.FAULT_CATEGORIES)}"
                    )
                continue
            value = entry.get(field_name)
            if not recognised_fault_category(value):
                problems.append(
                    f"'{label}' declares {field_name} {value!r}, which this build does "
                    f"not recognise; it grades as {UNCLASSIFIED_CATEGORY} and will not "
                    f"halt. Expected one of {sorted(api.FAULT_CATEGORIES)}"
                )
    return problems


def token_halts(action) -> bool:
    """Whether an `intervention.action` name is at or above HALT, i.e. "stop actuating"."""
    try:
        return Action[str(action)] >= Action.HALT
    except KeyError:
        return False


def fault_stops_the_run(entry) -> bool:
    """Whether a graded `verdict.failure_modes` entry stops the monitor's run.

    The node used to halt on any triggered failure mode regardless of what it published
    -- so on a dead-sensor `collision_imminent` it published WARN, the supervisor kept
    actuating, and the monitor shut down anyway: two different decisions about the same
    tick, from the same process. This is the one decision both read.

    Graded by `grade_action` on the entry's own category and confidence, at the
    already-breached imminence of 0 that `decide_intervention` uses, so the rung here is
    the rung in the token.

    Two rungs stop the run:

      * at or above HALT -- the token itself says stop;
      * below HALT for a fault that would not have reached HALT *at any confidence*.
        A phase TIMEOUT grades REPLAN on perfectly fresh data, and "this episode is
        over" is a different statement from "stop the robot": the phase machine's
        termination contract predates this PR and is not its to change.

    What is left is the case being fixed: a fault that *would* have halted on fresh data
    and was held back only by its confidence. There the monitor is saying it is not sure
    the fault happened, and it now behaves that way.
    """
    category = (entry or {}).get("fault_category")
    graded = grade_action(
        category, imminence=0, confidence=_unit((entry or {}).get("confidence", 1.0)),
        min_confidence=MIN_CONFIDENCE, warn_steps=WARN_STEPS,
    )
    if graded >= Action.HALT:
        return True
    certain = grade_action(
        category, imminence=0, confidence=1.0,
        min_confidence=MIN_CONFIDENCE, warn_steps=WARN_STEPS,
    )
    return certain < Action.HALT


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


# =============================================================================
# Which sources a failure mode is believable on
#
# Derived, never authored: `spec_contract.sensor_keys_in_rule()` gives an AP's sensor
# keys and the adapter manifest gives key -> source. See docs/clocking.md, "AP -> source
# dependency", for the three gaps a naive lookup gets wrong.
# =============================================================================

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: Single uppercase letters that are LTL temporal operators, not propositions.
_LTL_OPERATORS = frozenset("GFXURWM")


def aps_in_expression(text) -> frozenset[str]:
    """The atomic propositions an LTL formula or a phase condition names."""
    if not isinstance(text, str):
        return frozenset()
    return frozenset(
        t for t in _IDENTIFIER.findall(text)
        if t not in spec_contract.NON_SENSOR_TOKENS and t not in _LTL_OPERATORS
    )


def _source_keys(source: dict) -> set[str]:
    """Every sensor key a source feeds, declared or derived.

    Both are read because the derived ones are the ones that matter: `upright_flag` is
    computed by a step from `base_roll`/`base_pitch`/`base_height`, and a lookup that
    saw only a source's top-level `keys` would map the AP over it to no source at all
    -- i.e. to permanently fresh. A step's `inputs` need no separate walk: they are keys
    of the same source, so the closure is already closed.
    """
    keys: set[str] = set()
    declared = source.get("keys")
    if isinstance(declared, list):
        keys |= {k for k in declared if isinstance(k, str)}
    steps = source.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            if isinstance(step.get("key"), str):
                keys.add(step["key"])
            for key in step.get("keys") or ():
                if isinstance(key, str):
                    keys.add(key)
    return keys


def adapter_key_sources(adapter) -> dict[str, frozenset[str]]:
    """Sensor key -> the adapter source ids that produce it."""
    out: dict[str, set[str]] = {}
    for source in (adapter or {}).get("sources") or ():
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            continue
        for key in _source_keys(source):
            out.setdefault(key, set()).add(source["id"])
    return {key: frozenset(ids) for key, ids in out.items()}


def adapter_required_sources(adapter) -> frozenset[str]:
    """Source ids whose freshness an AP's believability depends on.

    `required` is the knob, deliberately not `tracked`: `tracked` counts toward the
    observation's global confidence scalar, `required` says whether a missing source
    makes an AP unknowable, and the two already diverge on
    `/vision/goal_similarity` (untracked, but its key feeds `visually_at_goal`).
    Missing means required -- a source nobody declared optional is one whose silence
    should be visible.
    """
    return frozenset(
        source["id"]
        for source in (adapter or {}).get("sources") or ()
        if isinstance(source, dict)
        and isinstance(source.get("id"), str)
        and bool(source.get("required", True))
    )


def ap_source_map(atomic_propositions, adapter) -> dict[str, frozenset[str]] | None:
    """AP name -> the required adapter sources whose data that AP is computed from.

    None when the adapter has announced nothing to map against, which is the signal to
    the caller that per-AP freshness is not knowable here and the observation's global
    scalar is all there is.

    An AP with no `"True when"` rule is LLM-evaluated: the evaluator hands it the whole
    `sensor_eval` dict, so it depends on *every* source. Mapping it to "no sources"
    would make it permanently fresh, exactly backwards.

    Residual: a rule that references only keys no source claims maps to the empty set,
    i.e. to full confidence. That is a descriptor gap -- `api.validate_adapter` already
    reports a source feeding a key the schema never declares -- and reporting it as low
    confidence would de-escalate a real halt for a bookkeeping error.
    """
    key_sources = adapter_key_sources(adapter)
    if not key_sources:
        return None
    required = adapter_required_sources(adapter)
    out: dict[str, frozenset[str]] = {}
    for ap, description in (atomic_propositions or {}).items():
        keys = spec_contract.sensor_keys_in_rule(
            description if isinstance(description, str) else ""
        )
        if not keys:
            out[str(ap)] = required
            continue
        sources: set[str] = set()
        for key in keys:
            sources |= key_sources.get(key, frozenset())
        out[str(ap)] = frozenset(sources) & required
    return out


def expression_source_map(expressions, ap_map) -> dict[str, frozenset[str]] | None:
    """Name -> the sources the named expression's APs are computed from.

    `expressions` is {name: LTL formula or phase condition}. A name whose expression
    mentions no AP this spec declares is left out entirely rather than mapped to the
    empty set: "reads nothing" and "I could not tell what it reads" grade very
    differently, and only the first one deserves full confidence.
    """
    if ap_map is None:
        return None
    out: dict[str, frozenset[str]] = {}
    for name, expression in (expressions or {}).items():
        aps = aps_in_expression(expression) & set(ap_map)
        if not aps:
            continue
        sources: set[str] = set()
        for ap in aps:
            sources |= ap_map[ap]
        out[str(name)] = frozenset(sources)
    return out


def source_confidence(sources, stale_sources=()) -> float:
    """The fraction of `sources` that are fresh; 1.0 for an empty set."""
    sources = frozenset(sources or ())
    if not sources:
        return 1.0
    return len(sources - frozenset(stale_sources or ())) / len(sources)


def failure_mode_entries(
    modes,
    confidence: float,
    *,
    mode_sources: dict | None = None,
    stale_sources=(),
) -> list[dict]:
    """`verdict.failure_modes`, every entry carrying a `confidence`.

    This closes a live bug rather than adding a field. The supervisor's VIOLATED branch
    reads `violated.get("confidence", 1.0)`, and the entries were built without the key
    -- so a `fell_over` derived from a sensor that stopped publishing graded at full
    confidence and went straight to ABORT, with the de-escalation path that exists for
    exactly this case never taken.

    **The confidence is per mode**, and this is the safety-relevant half. Stamping one
    global scalar -- the fraction of *all* required sources fresh -- onto every entry
    de-escalates faults that are perfectly well evidenced: a quiet battery topic drags
    the number under `min_confidence` while the depth camera is fresh, and a real
    `collision_imminent` grades WARN instead of HALT. So each mode is graded on the
    freshness of the sources feeding *its* APs, via `mode_sources` (see
    `ap_source_map`) against `stale_sources`.

    `mode_sources` None -- no adapter has announced itself, so nothing says which source
    feeds which AP -- falls back to the observation's global `confidence` for every
    mode, which is the old behaviour and the best available with no map. A mode absent
    from a map that does exist falls back the same way, because "its expression named no
    AP I know" is ignorance, not freshness.
    """
    out = []
    for mode in modes or []:
        name = str(mode.get("name", ""))
        sources = None if mode_sources is None else mode_sources.get(name)
        graded = (
            confidence if sources is None
            else source_confidence(sources, stale_sources)
        )
        out.append(api.build_failure_mode(
            name=name,
            fault_category=(
                wire_fault_category(mode.get("fault_category")) or UNCLASSIFIED_CATEGORY
            ),
            status=_status_name(mode.get("status")),
            confidence=_unit(graded),
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


def breached_mode(failure_modes) -> dict | None:
    """The entry `decide_intervention` grades, or None when it falls through to the
    predictive risk block.

    The precedence is `supervisor_logic`'s, reproduced rather than guessed at: a
    VIOLATED safety mode first, then any VIOLATED mode, and no breach at all means the
    risk branch fired.

    The honest fix is for `decide_intervention` to *return* which branch it took --
    P5 owns `core/supervisor_logic.py`, so that is a note in this PR's report and not a
    diff here. What this replaces is worse than duplication: matching
    `decision.reason` against failure-mode names, where `reason` is a mode's name on one
    branch and a severity string on the other, so a mode literally named "TIMEOUT"
    hijacked the evidence of a risk-branch decision and reported the wrong `imminence`
    and `confidence` beside the right rung.
    """
    modes = list(failure_modes or ())
    violated = [fm for fm in modes if fm.get("status") == "VIOLATED"]
    for fm in violated:
        if fm.get("fault_category") in SAFETY_CATEGORIES:
            return fm
    return violated[0] if violated else None


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
    # Which branch fired, decided by the same rule `decide_intervention` uses rather
    # than by matching its `reason` string against failure-mode names. See
    # `breached_mode`.
    breached = breached_mode(failure_modes)
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
    mode_sources: dict | None = None,
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
    modes = failure_mode_entries(
        failure_modes, confidence,
        mode_sources=mode_sources, stale_sources=stale_sources,
    )
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
