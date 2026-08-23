"""A monitor that exists only in this process, on the gateway's own bus interface.

This is a **fiction**, and it says so on the wire: ``services.ros.detail`` names it, so
an operator looking at the page can never mistake mocked sensor values for a robot's.
It exists because this host has no ``rclpy`` and cannot see the robot's DDS graph, so
it is the only way to develop or review the operator surface at all.

What it is not allowed to be is an *approximation*. Every frame it publishes goes
through ``core.api``'s builders and is validated by the same validators the real
producers are held to -- see ``tests/test_web_ui.py``. If the contract moves and this
does not, the tests fail here rather than in a browser.

The spec and the adapter are the real ones off disk (``specs/g1`` and
``adapters/real_g1.json``): the panes that render a spec, its APs and its topic list are
then rendering the actual artefacts, not a stand-in shaped like them.
"""

from __future__ import annotations

import json
import math
import threading
import time

import skill_monitor
from skill_monitor.backend.gateway import BusUnavailable, MonitorBus
from skill_monitor.core import adapter_spec, api, spec_contract

NS = "/g1"

#: Sensor keys whose value is a number the mock varies over time. Everything else in the
#: schema is categorical and is driven by the little state machine in `_sensors`.
_NOISY = ("linear_vel", "angular_vel", "base_roll", "base_pitch")


# =============================================================================
# The automata pane 6 draws
#
# ponytail: all of this belongs to P4. The real graph comes out of Spot, via a
# nodes-and-edges accessor on `core.automata.LTLMonitor`, and reaches the wire as
# `api.build_skill_manifest(..., automata=...)`. Delete this block and call that builder
# the moment it lands. Until then the mock hand-compiles the two formula *shapes* the
# shipped spec actually uses -- a chained eventuality and a `G(...)` safety property --
# and returns nothing at all for any other shape, because a fabricated graph for a
# formula nobody translated is exactly the approximation this module is not allowed to
# be. The field names, types and nesting below are the contract's, not a resemblance of
# it, so the swap is a deletion rather than a migration.
# =============================================================================


def _literal(text: str) -> str | None:
    """`ap` or `!ap`, whitespace normalised away; None if it is not one literal."""
    body = text.strip()
    negated = body.startswith("!")
    if negated:
        body = body[1:].strip()
    if not body or not (body[0].isalpha() or body[0] == "_"):
        return None
    if not all(c.isalnum() or c == "_" for c in body):
        return None
    return ("!" if negated else "") + body


#: The unconditional guard, spelt the way the real producer spells it. Spot prints an
#: edge condition with `bdd_format_formula`, and `bddtrue` comes out as `1` -- so every
#: absorbing state's self-loop is labelled `1` on the wire. The mock says `1` too: a
#: friendlier `true` here would be a label the console never has to render for a real
#: monitor, and the console is what this module exists to hold up.
_ANY = "1"


def _negate(literal: str) -> str:
    return literal[1:] if literal.startswith("!") else "!" + literal


def _unwrap(text: str, operator: str) -> str | None:
    """The body of `F(...)`/`G(...)` when that is the *whole* of `text`, else None.

    The balance walk is the point: `G(a) && G(b)` starts with `G(` and ends with `)`
    too, and slicing it would hand back `a) && G(b` as a guard.
    """
    text = text.strip()
    if not text.startswith(operator + "("):
        return None
    depth = 0
    for i, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[len(operator) + 1:i].strip() if i == len(text) - 1 else None
    return None


def _split_conjuncts(text: str) -> list[str]:
    """`text` split on `&&` at bracket depth zero."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        char = text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and text.startswith("&&", i):
            parts.append(text[start:i])
            i += 2
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return [p.strip() for p in parts]


def _eventuality_chain(formula: str) -> list[str] | None:
    """`F(a && F(b && F(c)))` -> `['a', 'b', 'c']`; None for any other shape."""
    body = _unwrap(formula, "F")
    if body is None:
        return None
    parts = _split_conjuncts(body)
    if len(parts) == 1:
        head = _literal(parts[0])
        return None if head is None else [head]
    if len(parts) != 2:
        return None
    head = _literal(parts[0])
    rest = _eventuality_chain(parts[1])
    return None if head is None or rest is None else [head] + rest


def _chain_automaton(name: str, formula: str, chain: list[str]) -> dict:
    """One state per eventuality still outstanding, plus the state where none are."""
    states = [{"id": i, "accepting": False, "sink": False} for i in range(len(chain))]
    # Accepting *and* absorbing: every eventuality has been discharged, so the verdict
    # is ACCEPTED and no further input can take it back.
    states.append({"id": len(chain), "accepting": True, "sink": True})
    edges = []
    for i, literal in enumerate(chain):
        edges.append({"from": i, "to": i + 1, "label": literal})
        edges.append({"from": i, "to": i, "label": _negate(literal)})
    edges.append({"from": len(chain), "to": len(chain), "label": _ANY})
    return {"name": name, "formula": formula, "initial": 0,
            "states": states, "edges": edges}


def _safety_automaton(name: str, formula: str, literal: str) -> dict:
    """`G(p)`: hold in the accepting state while `p` holds, absorb the moment it does
    not. Two states, and the second one is where a violated safety property stays."""
    return {"name": name, "formula": formula, "initial": 0,
            "states": [{"id": 0, "accepting": True, "sink": False},
                       {"id": 1, "accepting": False, "sink": True}],
            "edges": [{"from": 0, "to": 1, "label": _negate(literal)},
                      {"from": 0, "to": 0, "label": literal},
                      {"from": 1, "to": 1, "label": _ANY}]}


def compile_automaton(name: str, formula) -> dict | None:
    """The monitor graph for `formula`, or None when the mock cannot build a real one."""
    text = str(formula or "")
    guard = _unwrap(text, "G")
    if guard is not None:
        literal = _literal(guard)
        return None if literal is None else _safety_automaton(name, text, literal)
    chain = _eventuality_chain(text)
    return None if chain is None else _chain_automaton(name, text, chain)


def automata_for(spec: dict) -> list[dict]:
    """A graph per monitor, in the order the verdict lists them: `ltl_formulas` first,
    then `named_failure_modes`. A formula the mock cannot compile contributes no graph,
    and its verdict row therefore has none to match -- which is the degrade path the
    console has to survive anyway, because the phase machine's own faults never have
    one either.
    """
    declared = list(spec.get("ltl_formulas") or []) + \
        list(spec.get("named_failure_modes") or [])
    graphs = []
    for entry in declared:
        if not isinstance(entry, dict):
            continue
        graph = compile_automaton(entry.get("name", ""), entry.get("formula", ""))
        if graph is not None:
            graphs.append(graph)
    return graphs


def label_holds(label: str, ap_values: dict) -> bool | None:
    """Whether an edge's guard holds this tick -- or None when the tick cannot say.

    None is not False. An AP whose sensor went stale is absent from `ap_values`, and
    reading that as "the guard did not fire" would advance the mock's automaton on
    evidence it does not have.
    """
    if label == _ANY:
        return True
    negated = label.startswith("!")
    name = label[1:] if negated else label
    if name not in ap_values:
        return None
    value = bool(ap_values[name])
    return (not value) if negated else value


def successor(graph: dict, state, ap_values: dict):
    """The state after one tick, or None when a guard this tick cannot answer stands in
    the way -- which is what `formulas[].state: null` on the wire means."""
    for edge in graph["edges"]:
        if edge["from"] != state:
            continue
        holds = label_holds(edge["label"], ap_values)
        if holds is None:
            return None
        if holds:
            return edge["to"]
    return None


def status_of(graph: dict | None, state) -> str:
    """The formula status a state implies. Unknown state, unknown status -- and an
    accepting state that is also absorbing is ACCEPTED, not VIOLATED."""
    if graph is None or state is None:
        return "INCONCLUSIVE"
    for declared in graph["states"]:
        if declared["id"] == state:
            if declared["accepting"]:
                return "ACCEPTED"
            if declared["sink"]:
                return "VIOLATED"
    return "INCONCLUSIVE"


def _initial_states(automata) -> dict:
    return {graph["name"]: graph["initial"] for graph in automata}


def _wire_admits_state() -> bool:
    """Whether this build's verdict contract has room for `formulas[].state`.

    `_FORMULA_FIELDS` is closed and its entries are checked by `_check_each`, so the
    field is P0's to open before any producer may send it -- and a mock that emitted it
    early would be publishing a frame the shipped validators reject, which is the one
    thing this module exists not to do. Asking the validator itself, once, means the
    mock starts carrying the field the moment it is admitted and needs no edit to do it.

    ponytail: delete this and pass `state=` straight to `api.build_formula` /
    `api.build_failure_mode` once those builders take it.
    """
    probe = api.build_verdict(
        seq=1, t=0.0, step=0, skill_name="probe", phase=None, phase_index=None,
        verdict="UNDECIDED",
        formulas=[api.build_formula(name="probe", status="INCONCLUSIVE") | {"state": 0}],
        failure_modes=[api.build_failure_mode(
            name="probe", fault_category="SAFETY", status="INCONCLUSIVE",
            confidence=1.0) | {"state": None}],
        risk=api.build_risk(steps_to_timeout=None, seconds_to_timeout=None,
                            violations_to_fault=None, warn=False,
                            trigger_confidence=1.0),
        intervention=api.build_intervention(action="CONTINUE", confidence=1.0),
    )
    return api.validate_verdict(probe) == []


#: Asked once, at import: the answer cannot change while the process runs.
WIRE_ADMITS_STATE = _wire_admits_state()


def _with_state(row: dict, state) -> dict:
    """A verdict row carrying its automaton state, where the contract has room."""
    return row | {"state": state} if WIRE_ADMITS_STATE else row


class MockBus(MonitorBus):
    """One namespace, one monitor, ticking at the adapter's own ``tick_hz``."""

    def __init__(self, spec_name: str = "g1", adapter_name: str = "real_g1",
                 rate_scale: float = 1.0):
        self.spec = json.loads(skill_monitor.spec_path(spec_name).read_text())
        # The descriptor's own manifest, wrapped in the wire envelope it predates.
        described = adapter_spec.load(adapter_name).manifest()
        self.adapter = api.build_adapter(
            adapter=adapter_name,
            doc=described["doc"],
            tick_hz=described["tick_hz"],
            schema=described["schema"],
            sources=described["sources"],
            warnings=described.get("warnings", ()),
        )
        self.tick_hz = float(self.adapter["tick_hz"])
        # Wall-clock seconds between pulses. Scaled separately from `tick_hz` because
        # the wire value must stay the robot's -- a page that renders "1 Hz" while
        # frames arrive at 4 Hz is showing a lie the operator cannot see through.
        self.period = 1.0 / (self.tick_hz * rate_scale)
        self.t0 = time.time()

        #: One graph per monitor the spec declares, and where each of them stands. The
        #: graphs are latched with the manifest; the state is republished every verdict.
        self._automata = automata_for(self.spec)
        self._auto_state = _initial_states(self._automata)

        self._latched = {
            api.ADAPTER: json.dumps(self.adapter),
            api.MANIFEST: json.dumps(self._manifest("mock")),
            # The builder, not a dict shaped like one. `spec_status` has a closed field
            # set, so a hand-rolled frame with a `source` on it is a frame the
            # validators reject and no real monitor would ever send.
            api.SPEC_STATUS: json.dumps(api.build_spec_status(
                ok=True, skill_name=self.spec.get("skill_name", ""))),
        }
        self._subs: list[tuple[str, tuple, callable]] = []
        self._lock = threading.Lock()
        self._last_seen: float | None = None
        self._seq = 0
        self._step = 0
        self._paused = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mock-monitor",
                                        daemon=True)
        self._thread.start()

    # -- MonitorBus --------------------------------------------------------

    def namespaces(self):
        return [NS]

    def latched(self, ns, topic):
        return self._latched.get(topic) if ns == NS else None

    def last_seen(self, ns):
        return self._last_seen if ns == NS else None

    def status(self):
        return {
            "available": True,
            "detail": ("MOCK -- there is no ROS here. Every sensor value on this page "
                       "is fabricated by skill_monitor.frontend.mock_monitor."),
            "mock": True,
        }

    def subscribe(self, ns, topics, callback):
        entry = (ns, tuple(topics), callback)
        with self._lock:
            self._subs.append(entry)

        def unsubscribe():
            with self._lock:
                if entry in self._subs:
                    self._subs.remove(entry)
        return unsubscribe

    def publish(self, ns, topic, payload_text):
        if ns != NS:
            raise BusUnavailable(f"the mock serves {NS} only, not {ns!r}")
        if topic == api.COMMAND:
            self._command(json.loads(payload_text).get("command"))
        elif topic == api.LOAD_SPEC:
            self._load_spec(json.loads(payload_text).get("spec") or {})
        # Anything else is accepted and dropped: the mock is not the place to decide
        # which ingress topics a real monitor answers.

    def shutdown(self):
        self._stop.set()

    # -- the fiction -------------------------------------------------------

    def _manifest(self, source):
        """The spec as authored, plus the graphs pane 6 draws.

        ponytail: the `|` is here because `api.build_skill_manifest` has no `automata`
        keyword yet -- P4's producer half adds one, and this merge goes with it. The
        field is legal on the wire today because the manifest is the one validator
        opened with `closed=False`, which is also why it is the payload the graphs
        belong on: they are derived from the spec, latched with it, and change only
        when it does.
        """
        return api.build_skill_manifest(spec=self.spec, source=source) | {
            "automata": self._automata,
        }

    def _command(self, command):
        if command == "reset":
            self._step = 0
            self._auto_state = _initial_states(self._automata)
        elif command in ("pause", "resume"):
            self._paused = command == "pause"

    def _load_spec(self, spec):
        """Hot reload, and the episode ends because of it.

        A spec swap mid-episode leaves the automaton stepping propositions from a
        document nobody is looking at any more, so the step counter restarts and the
        manifest is relatched with the spec that is now loaded.
        """
        problems = spec_contract.validate(spec, self.adapter["schema"].keys())
        # `spec_status` says whether the spec was taken and why not; *which* spec is now
        # loaded is the manifest's `source`, which is a field the manifest really has.
        status = api.build_spec_status(
            ok=not problems, problems=problems,
            skill_name=spec.get("skill_name", ""))
        if not problems:
            self.spec = spec
            self._step = 0
            # A new spec is new automata, and the states of the old ones mean nothing
            # against it -- the same reason `step` restarts.
            self._automata = automata_for(spec)
            self._auto_state = _initial_states(self._automata)
            self._latched[api.MANIFEST] = json.dumps(self._manifest("load_spec"))
        self._latched[api.SPEC_STATUS] = json.dumps(status)
        self._emit(api.SPEC_STATUS, self._latched[api.SPEC_STATUS])

    def _run(self):
        while not self._stop.wait(self.period):
            if self._paused:
                continue
            self._seq += 1
            self._step += 1
            self._pulse()
            if self._step >= self._episode_steps():
                # The episode ends and the next one starts. `seq` does not restart with
                # it -- it is the clock's axis, not the run's, and a console that saw
                # both go back to 1 could not tell a new episode from a new clock.
                # Every automaton does restart: a run's states belong to that run.
                self._step = 0
                self._auto_state = _initial_states(self._automata)

    def _pulse(self):
        seq, step = self._seq, self._step
        t = self.t0 + seq / self.tick_hz
        self._emit(api.TICK, json.dumps(api.build_tick(
            seq=seq, t=t, tick_hz=self.tick_hz, t0=self.t0, mode="wall")))

        sensors = self._sensors(step)
        stale = self._stale_sources(step)
        ap_values, unknown = self._aps(sensors, stale)
        confidence = 0.5 if stale else 1.0
        self._emit(api.OBSERVATION, json.dumps(api.build_observation(
            seq=seq, t=t, step=step, sensors=sensors, ap_values=ap_values,
            unknown_aps=unknown, confidence=confidence,
            data_health=self._health(step, stale))))

        self._emit(api.VERDICT, json.dumps(self._verdict(seq, t, step, ap_values,
                                                         unknown, stale, confidence)))
        self._last_seen = time.time()

    def _emit(self, topic, text):
        with self._lock:
            subs = [s for s in self._subs if s[0] == NS and topic in s[1]]
        for _ns, _topics, callback in subs:
            callback(topic, text)

    def _episode_steps(self) -> int:
        """The whole run's bound: every phase's own, summed. A spec with no bounds runs
        for a nominal 150 ticks rather than forever, so the mock's step counter is
        always something the max-steps pane can be read against."""
        total = sum(_max_steps(self.spec, i) or 0
                    for i in range(len(self.spec.get("execution_phases") or [])))
        return total or 150

    def _stale_sources(self, step):
        # The depth camera drops out for six ticks in every sixty. This is the case the
        # panes exist for: staleness, an UNKNOWN AP, and a de-rated confidence, all at
        # once and all visible.
        return ["points"] if 20 <= step % 60 < 26 else []

    def _phase_at(self, step):
        """(index, steps spent in it), walking the spec's own per-phase bounds."""
        phases = self.spec.get("execution_phases") or []
        if not phases:
            return None, step
        left = step
        for i in range(len(phases)):
            bound = _max_steps(self.spec, i) or 50
            if left < bound or i == len(phases) - 1:
                return i, left
            left -= bound
        return len(phases) - 1, left

    def _sensors(self, step):
        phase = min((self._phase_at(step)[0] or 0), 2)
        min_range = max(0.18, 3.0 - 0.02 * (step % 150))
        return {
            "min_range": round(min_range, 3),
            "base_roll": round(0.02 * math.sin(step / 6.0), 4),
            "base_pitch": round(0.03 * math.cos(step / 9.0), 4),
            "base_height": round(0.78 + 0.01 * math.sin(step / 4.0), 4),
            "upright_flag": 1.0,
            "linear_vel": round(max(0.0, 0.45 + 0.08 * math.sin(step / 5.0)), 3),
            "angular_vel": round(0.15 * math.sin(step / 11.0), 3),
            "nav_mode": "AUTOMATIC",
            "nav_state": ("planning", "following", "following")[phase],
            "num_waypoints": 4,
            "current_target_idx": min(3, step // 20),
            "mission_finished": step % 150 > 140,
            "nav_stuck": False,
            "image_similarity_to_goal": round(min(0.95, 0.2 + 0.006 * (step % 150)), 3),
        }

    def _aps(self, sensors, stale):
        """Evaluate the spec's own rules against the fabricated sensors.

        The same ``eval`` shape the evaluator uses, over the same rule text, so an AP
        that this page shows as true is true *for the reason the rule gives*. A key fed
        only by a stale source makes its APs UNKNOWN rather than false -- which is the
        whole reason ``unknown_aps`` is a sibling list and not a third truth value.
        """
        blind = {k for k in self.adapter["schema"]
                 if any(k in s.get("keys", []) for s in self.adapter["sources"]
                        if s["id"] in stale)}
        values, unknown = {}, []
        for name, description in self.spec["atomic_propositions"].items():
            keys = spec_contract.sensor_keys_in_rule(description)
            if keys & blind:
                unknown.append(name)
                continue
            rule = spec_contract.rule_of(description)
            if rule is None:
                unknown.append(name)          # an LLM-evaluated AP; the mock has no model
                continue
            try:
                values[name] = bool(eval(rule, {}, sensors))
            except Exception:                       # noqa: BLE001
                unknown.append(name)
        return values, unknown

    def _health(self, step, stale):
        health = {}
        for source in self.adapter["sources"]:
            is_stale = source["id"] in stale
            expected = float(source["expected_hz"])
            health[source["id"]] = {
                "rate_hz": 0.0 if is_stale else round(expected * (0.95 + 0.1 *
                                                      math.sin(step / 7.0)), 3),
                "expected_hz": expected,
                "age_s": round(6.0 if is_stale else 1.0 / max(expected, 1e-6), 3),
                "samples_this_tick": 0 if is_stale else max(1, int(expected)),
                "refreshed": not is_stale,
                "dropped": 0,
            }
        return health

    def _verdict(self, seq, t, step, ap_values, unknown, stale, confidence):
        phases = api.phase_names(self.spec.get("execution_phases"))
        phase_index, in_phase = self._phase_at(step)
        phase = phases[phase_index] if phases and phase_index is not None else None
        bound = _max_steps(self.spec, phase_index)

        # One tick of every automaton, over the AP values this tick already fabricated,
        # so a lit node on the console is lit for the reason the edge label gives. A
        # guard the tick cannot answer -- an AP blinded by a stale source -- leaves the
        # state where it was and reports null rather than a state nobody stepped into.
        states = {}
        graphs = {graph["name"]: graph for graph in self._automata}
        for name, graph in graphs.items():
            nxt = successor(graph, self._auto_state.get(name, graph["initial"]),
                            ap_values)
            if nxt is not None:
                self._auto_state[name] = nxt
            states[name] = nxt

        # A safety automaton enters its sink on the tick its guard fails and stays
        # there, so a mode reads VIOLATED for the rest of the episode instead of
        # flickering with the AP. `tripped` survives for a declared mode the mock could
        # compile no graph for: whichever the spec declares first, and only that one,
        # because tripping every SAFETY mode at once would have the page claim the robot
        # fell over at the same instant it saw an obstacle.
        declared = self.spec.get("named_failure_modes", [])
        tripped = declared[0]["name"] if declared else None
        ap_violation = ap_values.get("collision_risk", False)
        modes = [
            _with_state(api.build_failure_mode(
                name=m["name"], fault_category=m.get("fault_category", "SAFETY"),
                status=status_of(graphs.get(m["name"]), states.get(m["name"]))
                       if m["name"] in graphs
                       else ("VIOLATED" if ap_violation and m["name"] == tripped
                             else "INCONCLUSIVE"),
                confidence=confidence), states.get(m["name"]))
            for m in declared
        ]
        violated = any(m["status"] == "VIOLATED" for m in modes)
        action = ("HALT" if violated and confidence > 0.75 else
                  "WARN" if violated or stale else "CONTINUE")
        return api.build_verdict(
            seq=seq, t=t, step=step,
            skill_name=self.spec.get("skill_name", ""),
            phase=phase, phase_index=phase_index,
            verdict="VIOLATED" if violated else "UNDECIDED",
            formulas=[
                _with_state(api.build_formula(
                    name=f["name"],
                    status=status_of(graphs.get(f["name"]), states.get(f["name"]))),
                    states.get(f["name"]))
                for f in self.spec.get("ltl_formulas", [])
            ],
            failure_modes=modes,
            risk=api.build_risk(
                steps_to_timeout=None if bound is None else max(0, bound - in_phase),
                seconds_to_timeout=(None if bound is None
                                    else round(max(0, bound - in_phase) / self.tick_hz, 3)),
                violations_to_fault=None,
                warn=bool(stale or violated),
                severity="SAFETY" if violated else None,
                trigger_confidence=confidence,
                stale_sources=list(stale),
            ),
            intervention=api.build_intervention(
                action=action,
                category="SAFETY" if violated else None,
                imminence="now" if violated else None,
                confidence=confidence),
            missed_ticks=0,
        )


def _max_steps(spec, phase_index):
    phases = spec.get("execution_phases") or []
    if phase_index is None or not (0 <= phase_index < len(phases)):
        return None
    bounds = phases[phase_index].get("timing_bounds") or {}
    value = bounds.get("max_steps")
    return value if isinstance(value, int) else None
