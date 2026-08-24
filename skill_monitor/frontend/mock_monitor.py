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
import random
import re
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


def _probe_verdict(*, formulas=None, failure_modes=None, **extra) -> dict:
    """A minimal, otherwise-valid verdict, for asking the validator a question.

    Everything about it is the builders' own, so the only thing a rejection can be
    about is what the caller put on it.
    """
    return api.build_verdict(
        seq=1, t=0.0, step=0, skill_name="probe", phase=None, phase_index=None,
        verdict="UNDECIDED",
        formulas=[api.build_formula(name="probe", status="INCONCLUSIVE")]
        if formulas is None else formulas,
        failure_modes=[] if failure_modes is None else failure_modes,
        risk=api.build_risk(steps_to_timeout=None, seconds_to_timeout=None,
                            violations_to_fault=None, warn=False,
                            trigger_confidence=1.0),
        intervention=api.build_intervention(action="CONTINUE", confidence=1.0),
    ) | extra


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
    probe = _probe_verdict(
        formulas=[api.build_formula(name="probe", status="INCONCLUSIVE") | {"state": 0}],
        failure_modes=[api.build_failure_mode(
            name="probe", fault_category="SAFETY", status="INCONCLUSIVE",
            confidence=1.0) | {"state": None}],
    )
    return api.validate_verdict(probe) == []


def _wire_admits_phase_guards() -> bool:
    """Whether this build's verdict contract has room for `phase_guards`.

    The same question as `_wire_admits_state`, asked the same way and for the same
    reason: `_VERDICT_FIELDS` is closed, so P0 opens the field before any producer may
    send it, and a mock that emitted it early would publish frames the shipped
    validators reject. Asking the validator itself means `--mock` starts demonstrating
    pane 7's guard truth the moment P0 lands, with no edit here.

    ponytail: delete this and pass `phase_guards=` straight to `api.build_verdict`
    once that builder takes it.
    """
    probe = _probe_verdict(phase_guards={
        "phase": "probe",
        "guards": [{"name": "invariant", "expr": "upright", "value": None}]})
    return api.validate_verdict(probe) == []


#: The last segment of the monitor-state topic, which is also the gateway's route verb
#: for it: ``LATCHED_ROUTES`` is derived from the topic name, so
#: ``GET /api/monitors/{ns}/status`` appears with no edit to the gateway the moment the
#: constant lands. Spelt as the segment and not as the whole topic because
#: ``tests/test_api.py`` allows a topic literal in ``core/api.py`` and nowhere else.
STATUS_VERB = "status"

#: The states the contract admits, in the order the console's banner ranks them.
#: ``api.RUN_STATES`` where the build has it, and the same four words where it does not,
#: so this module imports on either -- the tuple is not a second opinion about the
#: vocabulary and ``tests/test_web_ui.py`` asserts the two agree.
MONITOR_STATES = tuple(getattr(api, "RUN_STATES", None)
                       or ("running", "paused", "halted", "idle"))

#: The two the mock is ever actually in: it has no fault to halt on and no gap between
#: episodes to be idle in, and it publishes no state it cannot be in.
_STATES_EMITTED = ("running", "paused")


def status_topic():
    """The monitor-state topic as ``core.api`` spells it, or None in a build that has no
    such topic yet.

    Found by its last segment rather than by an attribute name: the *name* of the
    constant is P0's to choose and its value is the contract's, and this module must not
    break on a spelling of ``api.STATUS`` it guessed wrong.
    """
    named = [t for t in sorted(api.TOPICS) if t.rsplit("/", 1)[-1] == STATUS_VERB]
    return named[0] if len(named) == 1 else None


#: Asked once, at import: neither answer can change while the process runs.
STATUS_TOPIC = status_topic()


def build_status(*, seq: int, t: float, state: str, reason: str | None,
                 since_seq: int | None) -> dict:
    """The monitor-state frame: ``api.build_monitor_status`` where the build has it.

    The fallback is the identical shape, hand-built, so this module is importable on a
    build that predates the builder -- and nothing it returns reaches the wire unless
    ``WIRE_ADMITS_STATUS``, which is the shipped validator's own answer about this exact
    payload. A hand-built frame that the validator has never seen is not published.

    ponytail: delete the fallback once ``api.build_monitor_status`` is on dev.
    """
    builder = getattr(api, "build_monitor_status", None)
    if builder is not None:
        return builder(seq=seq, t=t, state=state, reason=reason, since_seq=since_seq)
    return {"schema_version": api.SCHEMA_VERSION, "seq": seq, "t": t,
            "state": state, "reason": reason, "since_seq": since_seq}


def _probe_status(state: str = "running", reason: str | None = "operator command",
                  since_seq: int | None = 0) -> dict:
    """A monitor-state frame, for asking the validator a question -- and the one shape
    the mock actually publishes, so the probe and the payload cannot drift apart."""
    return build_status(seq=1, t=1.0, state=state, reason=reason, since_seq=since_seq)


def _wire_admits_status() -> bool:
    """Whether this build's contract has a monitor-state topic the mock may publish on.

    The same question as ``_wire_admits_phase_guards``, asked the same way and for the
    same reason: the answer is the shipped validator's, so ``--mock`` starts reporting a
    state -- and the console's banner starts showing one -- the moment P0's topic lands,
    with no edit here. Every frame the mock would send is probed, the nullable fields
    included: a topic that exists and rejects a null ``reason`` is not the contract this
    module was written against, and publishing into it would be the approximation this
    module is not allowed to be.

    ponytail: delete this and call ``api.build_monitor_status(...)`` directly once that
    builder exists.
    """
    if STATUS_TOPIC is None:
        return False
    probes = [_probe_status(state=s) for s in _STATES_EMITTED]
    # The startup frame: nothing has ticked, so there is no tick to have begun at.
    probes.append(_probe_status(reason="monitor started", since_seq=None))
    probes.append(_probe_status(reason=None, since_seq=None))
    return all(api.validate_for_topic(STATUS_TOPIC, p) == [] for p in probes)


#: Asked once, at import: the answer cannot change while the process runs.
WIRE_ADMITS_STATE = _wire_admits_state()
WIRE_ADMITS_PHASE_GUARDS = _wire_admits_phase_guards()
WIRE_ADMITS_STATUS = _wire_admits_status()


def _with_state(row: dict, state) -> dict:
    """A verdict row carrying its automaton state, where the contract has room."""
    return row | {"state": state} if WIRE_ADMITS_STATE else row


# =============================================================================
# The phase machine pane 7 draws
#
# ponytail: this belongs to P4 as well. The real answer comes from whatever steps the
# phase machine and already knows which guard it acted on this tick; the mock evaluates
# the spec's own guard text over the AP values it fabricated on the same frame, so a
# guard the console shows as true is true of the propositions shown beside it.
# =============================================================================

#: The guards a phase may declare, in the order the pane lists them: what had to be
#: true to be here at all, what admitted the phase, what has to stay true, what has to
#: keep being true, and what ends it. A phase that declares none of one is reported
#: with none -- the wire carries what the spec authored and not a full set padded with
#: nulls, because "this phase has no invariant" and "its invariant was not evaluated"
#: are different facts.
GUARD_KEYS = ("precondition", "enter_condition", "invariant",
              "progress_condition", "exit_condition")

_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def guard_aps(expr, ap_names) -> list[str]:
    """Which declared propositions `expr` reads.

    A word-boundary name match against the names the spec declares -- the same question
    the console asks of the same string, and deliberately the same answer. It is not a
    parse and claims not to be: it says this guard is a function of these propositions,
    which is all either side needs in order to show them beside it. String literals go
    first, so a `nav_state` value spelled like a proposition is not counted as one.
    """
    body = _QUOTED.sub(" ", str(expr or ""))
    return [n for n in ap_names if re.search(rf"\b{re.escape(n)}\b", body)]


def guard_value(expr, ap_values, ap_names):
    """True, False, or None -- and None is not False.

    A guard reading a proposition this tick could not evaluate has not failed; it was
    not answered. Reporting False there is how a stale depth camera comes to read as a
    broken invariant, which is the one thing the pane exists to make impossible.
    """
    if any(name not in ap_values for name in guard_aps(expr, ap_names)):
        return None
    try:
        return bool(eval(str(expr), {"__builtins__": {}}, dict(ap_values)))
    except Exception:                                   # noqa: BLE001
        return None


def phase_guards(spec: dict, phase_index, ap_values: dict) -> dict | None:
    """`verdict.phase_guards` -- the active phase's own guards and their live truth.

    None when no phase is active, which is a value the wire carries rather than an
    empty object: a run between phases has no guards, and an empty `guards` list would
    say the phase declared none.
    """
    phases = spec.get("execution_phases") or []
    if phase_index is None or not (0 <= phase_index < len(phases)):
        return None
    phase = phases[phase_index] if isinstance(phases[phase_index], dict) else {}
    names = list(spec.get("atomic_propositions") or {})
    guards = [
        {"name": key, "expr": phase[key],
         "value": guard_value(phase[key], ap_values, names)}
        for key in GUARD_KEYS
        if isinstance(phase.get(key), str) and phase[key].strip()
    ]
    # The same fallback `api.phase_names` uses, so the name here and the name in
    # `verdict.phase` are one string and the console can match them.
    return {"phase": phase.get("phase", f"phase{phase_index}"), "guards": guards}


def _with_phase_guards(verdict: dict, guards) -> dict:
    """A verdict carrying its phase's guards, where the contract has room."""
    return verdict | {"phase_guards": guards} if WIRE_ADMITS_PHASE_GUARDS else verdict


# =============================================================================
# Pane 3's raw echo
#
# The summaries are **the producer's own**. `backend/adapters/raw_echo.py` is where the
# `kind` convention lives -- `image`, `fields`, `image_unavailable` -- and it is
# stdlib-only, so this module can call it on a laptop with no ROS. That is the point:
# the console is reviewed against the code the robot runs, PNG encoder, downscale, byte
# cap, rate stride and all, rather than against a second implementation written to
# resemble it. What the mock fabricates is the *message*, which is what it fabricates
# everywhere else.
#
# `summary` is deliberately opaque on the wire -- `api.build_raw_echo`'s own docstring
# says its shape is the adapter's business -- so the convention is not a contract. What
# *is* the contract is the envelope, and every frame here goes through the shipped
# builder and the shipped validator like every other frame this module publishes.
# =============================================================================

try:                                    # pragma: no cover -- exercised both ways in CI
    from skill_monitor.backend.adapters import raw_echo as echo_producer
except ImportError:                     # a build that predates the producer half
    echo_producer = None

#: What a RealSense colour stream on the G1 actually publishes: 320x240 `bgr8`. The
#: mock fabricates a message of exactly that shape so the producer's downscale, its
#: channel swap and its byte cap are all on the path a reviewer looks at.
ECHO_SOURCE_W, ECHO_SOURCE_H = 320, 240

#: A frame's worth of low-order noise, computed once. The bars alone compress to under a
#: kilobyte, and a pane that renders a 700-byte "camera frame" teaches a reviewer that
#: the echo is free -- which is the one thing this feature exists to contradict. Real
#: photographic content at 160x120 measures ~48 KB of PNG; six bits of per-pixel noise
#: over the bars puts the mock in that neighbourhood instead of three orders below it.
_NOISE_BITS = bytes(i & 0x3F for i in range(256))
_NOISE = random.Random(20260824).randbytes(
    ECHO_SOURCE_W * ECHO_SOURCE_H * 3 * 2).translate(_NOISE_BITS)


class MockImage:
    """The five attributes `raw_echo.looks_like_image` duck-types on.

    Not a `sensor_msgs/msg/Image` -- there is no ROS here to define one -- and it does
    not need to be: the producer matches on the attributes rather than on a type name,
    precisely so a bag or a stand-in renders the same way a live camera does.
    """

    __slots__ = ("width", "height", "encoding", "step", "data")

    def __init__(self, width, height, encoding, data, step=None):
        self.width = width
        self.height = height
        self.encoding = encoding
        self.data = data
        self.step = width * 3 if step is None else step


def _xor(a: bytes, b: bytes) -> bytes:
    """Byte-wise XOR of two equal-length buffers, done as one big-integer operation --
    a per-byte loop over a quarter of a megabyte, every tick, in a mock, is not worth
    the milliseconds."""
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")


def synthetic_bgr8(step: int, width: int = ECHO_SOURCE_W,
                   height: int = ECHO_SOURCE_H) -> bytes:
    """Raw `bgr8` pixels that could not be mistaken for a camera.

    Diagonal bars in three saturated colours sliding one bar a tick, a white marker box
    travelling across the frame, and per-pixel noise over all of it. No robot produces
    this, which is the point: an operator who sees it is looking at the mock, and a
    reviewer who sees it move knows the echo is live and not a still left in the page.

    The rows are slices of one long pattern line, because a diagonal is the same line
    shifted by `y` -- which is what makes a 320x240 frame per tick cheap enough to be
    fabricated by a console rather than a robot.
    """
    bars = (b"\x78\x28\xe4", b"\xd2\xc8\x28", b"\x2e\x22\x1e")     # blue, green, red
    span = 12
    line = bytearray()
    for i in range(width + height + span):
        line += bars[((i // span) + step) % len(bars)]
    box_x, box_y, box = (step * 3) % max(1, width - 24), (height - 40) // 2, 40
    offset = (step * width * 3) % (len(_NOISE) - width * height * 3)
    rows = []
    for y in range(height):
        row = bytearray(line[y * 3:(y + width) * 3])
        if box_y <= y < box_y + box:
            row[box_x * 3:(box_x + box) * 3] = b"\xff" * (box * 3)
        rows.append(bytes(row))
    return _xor(b"".join(rows), _NOISE[offset:offset + width * height * 3])


def synthetic_frame(step: int) -> MockImage:
    """The colour frame the mock's camera source "publishes" this tick."""
    return MockImage(ECHO_SOURCE_W, ECHO_SOURCE_H, "bgr8", synthetic_bgr8(step))


#: The ticks in every sixty on which the camera source publishes a frame the echo cannot
#: render. Fabricated for the same reason `_stale_sources` fabricates a dropout: the
#: console has a rendering for it -- `image_unavailable`, with the producer's own reason
#: sentence -- and a path that only appears when somebody points a console at a depth
#: topic on a real robot is a path nobody reviews. `16UC1` is what a depth stream
#: actually publishes, and the reason string is the producer's, not the mock's.
_UNRENDERABLE = range(44, 50)


def _depth_frame(step: int) -> MockImage:
    """A 16-bit depth frame: a real message, and one no echo can turn into a picture."""
    return MockImage(ECHO_SOURCE_W, ECHO_SOURCE_H, "16UC1",
                     bytes(ECHO_SOURCE_W * ECHO_SOURCE_H * 2),
                     step=ECHO_SOURCE_W * 2)


def echo_message(source: dict, step: int, sensors: dict):
    """The message the mock's `source` "published" this tick, and the values folded from
    it -- the two things `RawEcho.offer` takes.

    The camera-derived source gets a picture; everything else gets the keys it feeds,
    read off the same fabricated frame the observation was folded from, so a number in
    the echo and the same number in the row table above it are one number and not two
    fictions.
    """
    values = {key: sensors[key] for key in sorted(source.get("keys") or ())
              if key in sensors}
    ros_type = str(source.get("type", ""))
    if ros_type.endswith(("/Image", "/CompressedImage", "/PointCloud2")):
        msg = _depth_frame(step) if step % 60 in _UNRENDERABLE \
            else synthetic_frame(step)
        return msg, values
    return values, values


def mock_kind(source: dict, summary: dict) -> dict:
    """A `kind` the console has no renderer for, on one source, on purpose.

    `/path_manager/status` is a `std_msgs/String` carrying a JSON document, and a
    summary of it as that document is a shape the page has never seen. It renders as a
    pretty-printed dump, which is the extension point working: `kind` is open so that a
    depth or lidar summary written next month shows an operator every field it carries
    with no edit to the page. `--mock` exercises that path rather than leaving it to be
    discovered by whoever adds the next sensor type.

    Deliberately the mock's invention and not the producer's -- it is what a *future*
    adapter does, which is the thing the page has to survive.
    """
    if not str(source.get("type", "")).endswith("/String"):
        return summary
    document = summary.get("values") or {}
    return {key: value for key, value in summary.items()
            if key not in ("kind", "values")} | {
        "kind": "document",
        "media_type": "application/json",
        "bytes": len(json.dumps(document)),
        "document": document,
    }


def _probe_raw_echo() -> dict:
    """A raw-echo frame, for asking the validator a question -- built by the shipped
    builder, around the producer's own summary of the mock's own camera frame."""
    echo = echo_producer.RawEcho({"probe": "/probe"}, tick_hz=1.0)
    echo.select("probe")
    echo.offer("probe", synthetic_frame(0))
    _source_id, summary = echo.take()
    return api.build_raw_echo(seq=1, t=1.0, step=0, source_id="probe", summary=summary)


def _wire_admits_raw_echo() -> bool:
    """Whether this build has a raw-echo topic the mock may publish on, and a producer
    to build the summaries with.

    The same question as ``_wire_admits_status``, asked the same way and for the same
    reason: the topic and its validator are P0's, and a producer publishing on a topic
    the gateway's own ingress check would reject is the approximation this module is not
    allowed to be. Both halves are probed -- the frame going out and the request coming
    in, including the ``source_id: null`` that stops it -- because the mock honours one
    and publishes the other, and a build that admitted only one of them is not the
    contract this was written against.

    Note what this is *not* gated on: whether the gateway forwards the topic to a
    browser. That is ``STREAM_TOPICS``, it is P6's, and a mock is valid either way.
    """
    if echo_producer is None:
        return False
    if api.RAW_ECHO not in api.TOPICS or api.RAW_ECHO_REQUEST not in api.TOPICS:
        return False
    requests = [api.build_raw_echo_request(source_id=None),
                api.build_raw_echo_request(source_id="probe")]
    return (api.validate_for_topic(api.RAW_ECHO, _probe_raw_echo()) == []
            and all(api.validate_for_topic(api.RAW_ECHO_REQUEST, r) == []
                    for r in requests))


#: Asked once, at import: the answer cannot change while the process runs.
WIRE_ADMITS_RAW_ECHO = _wire_admits_raw_echo()


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
        #: The monitor's own state, as the status topic reports it. Tracked whether or
        #: not this build's contract admits that topic: it is what `_command` acts on and
        #: what `_run` obeys, and only the *publishing* of it is gated on the probe.
        self._paused = False
        self._state = "running"
        self._state_reason = "monitor started"
        # Null, not 0: nothing has been ticked yet, and 0 would name a tick this monitor
        # is claiming to have counted. The console renders it as a length it cannot
        # measure rather than as "running for 0 ticks".
        self._state_since = None
        #: The producer's own echo buffer, off until something selects a source: opt-in
        #: and one at a time is the contract's rule and it is enforced in there, not
        #: here. The mock's job is to hand it a message a tick; the selection, the rate
        #: stride, the accumulated sample count and the summary are all the real code's.
        self._echo = echo_producer.RawEcho(
            {source["id"]: source["topic"] for source in self.adapter["sources"]},
            tick_hz=self.tick_hz,
        ) if WIRE_ADMITS_RAW_ECHO else None
        if WIRE_ADMITS_STATUS:
            self._latched[STATUS_TOPIC] = json.dumps(self._status_payload())
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
        replay: list[tuple[str, str]] = []
        with self._lock:
            self._subs.append(entry)
            if ns == NS:
                # TRANSIENT_LOCAL, which the real bus gets from DDS: `RclpyBus` uses
                # `_latched_qos` for every topic in `api.LATCHED_TOPICS`, so a
                # subscriber arriving after the last publication is handed it anyway.
                #
                # It matters here and not only for fidelity. `/monitor/status` is both
                # latched and streamed, and a paused monitor publishes nothing else at
                # all -- so without the replay the mock's stream would be the one place
                # in the system where a console connecting during a pause is told
                # nothing until the operator who caused the pause ends it. That is the
                # exact failure the latched state exists to prevent.
                replay = [(t, self._latched[t]) for t in entry[1] if t in self._latched]
        # Outside the lock: a callback that publishes would otherwise deadlock on it.
        for topic, text in replay:
            callback(topic, text)

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
        elif topic == api.RAW_ECHO_REQUEST:
            self._raw_echo_request(json.loads(payload_text))
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

    def _status_payload(self) -> dict:
        """This monitor's state, on the clock reading it is being published at.

        ``seq`` is now; ``since_seq`` is when the state began, and the two are equal
        only on the frame that announces a transition. A console reading the latched
        copy an hour later measures the pause against its own live tick, which is the
        whole reason the second field exists.
        """
        return build_status(
            seq=self._seq,
            t=self.t0 + self._seq / self.tick_hz,
            state=self._state,
            reason=self._state_reason,
            since_seq=self._state_since,
        )

    def _set_state(self, state: str, reason: str | None) -> None:
        """Move to `state` and say so on the wire, latched and streamed.

        ``since_seq`` moves only when the *state* does. An operator resetting a monitor
        that was already running has not restarted the running, and a second ``pause``
        must not reset a banner counting how long the robot has been going unwatched.
        """
        if state == self._state and reason == self._state_reason:
            return
        if state != self._state:
            self._state_since = self._seq
        self._state, self._state_reason = state, reason
        self._paused = state != "running"
        if WIRE_ADMITS_STATUS:
            text = json.dumps(self._status_payload())
            self._latched[STATUS_TOPIC] = text
            self._emit(STATUS_TOPIC, text)

    def _command(self, command):
        """``arm`` | ``reset`` | ``pause`` | ``resume``, with the consequences the
        console's confirmations name.

        ``arm`` and ``reset`` restart the episode and discard its history -- the step
        counter, every automaton's state, and with the step counter the phase machine --
        and they un-pause, because a monitor armed into a paused state would be a control
        that appears to have worked and has not. ``pause`` stops the stepping and leaves
        the robot exactly where it was: running, and unwatched.
        """
        if command in ("arm", "reset"):
            self._step = 0
            self._auto_state = _initial_states(self._automata)
            self._set_state("running", f"operator command: {command}")
        elif command == "pause":
            self._set_state("paused", "operator command")
        elif command == "resume":
            self._set_state("running", "operator command")

    def _raw_echo_request(self, payload):
        """``{"source_id": "points"}`` to start, ``{"source_id": null}`` to stop.

        Handed straight to the producer's own `RawEcho.select`, which is where "one at a
        time" and "a source this adapter does not declare is refused rather than
        silently turning off an echo somebody is watching" already live. The mock does
        not get a second opinion about either.

        A request the shipped validator rejects changes nothing -- the gateway's ingress
        route validates before it publishes, so a payload that got here malformed did
        not come through the console, and a mock that acted on it would be a fixture
        more permissive than the system it stands in for.
        """
        if self._echo is None or api.validate_raw_echo_request(payload) != []:
            return
        self._echo.select(payload.get("source_id"))

    def _raw_echo(self, seq, t, step, health, sensors):
        """One tick of the echo, or None when there is nothing to say.

        The message is offered only for a tick the source actually delivered on:
        `data_health` is where the mock's dropouts live, and re-offering a frame through
        the depth camera's own six-tick outage would hide the one thing pane 3's age
        counter exists to show. Everything after that -- the rate stride, the sample
        count over the window, the summary -- is `RawEcho`'s.
        """
        if self._echo is None:
            return None
        source = next((s for s in self.adapter["sources"]
                       if s["id"] == self._echo.selected), None)
        if source is not None:
            samples = (health.get(source["id"]) or {}).get("samples_this_tick") or 0
            if samples:
                # Fabricated once and offered `samples` times: `offer` is a reference
                # and a counter by design, and drawing the frame once per message would
                # make the mock the expensive half of a feature whose whole subject is
                # what things cost.
                msg, values = echo_message(source, step, sensors)
                for _ in range(samples):
                    self._echo.offer(source["id"], msg, values)
        taken = self._echo.take()
        if taken is None:
            return None
        source_id, summary = taken
        return api.build_raw_echo(seq=seq, t=t, step=step, source_id=source_id,
                                  summary=mock_kind(source or {}, summary))

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
            self._seq += 1
            if self._paused:
                # The clock does not stop because the monitor was told to, so the pulse
                # goes out and `seq` keeps counting -- which is the axis the console
                # measures `since_seq` against, and the only reason it can say how long
                # the robot has been running unwatched.
                #
                # What stops is the monitor: no step, no automaton transition, no phase
                # change, no verdict. `_last_seen` is deliberately left alone as well:
                # the monitor really has gone quiet, and a freshness faked on its behalf
                # here would hide the very thing the console's banner exists to explain.
                self._emit(api.TICK, json.dumps(self._tick(self._seq)))
                continue
            self._step += 1
            self._pulse()
            if self._step >= self._episode_steps():
                # The episode ends and the next one starts. `seq` does not restart with
                # it -- it is the clock's axis, not the run's, and a console that saw
                # both go back to 1 could not tell a new episode from a new clock.
                # Every automaton does restart: a run's states belong to that run.
                self._step = 0
                self._auto_state = _initial_states(self._automata)

    def _tick(self, seq):
        """One clock pulse. Built here rather than inline because a paused monitor still
        gets clocked, and both paths must put the identical frame on the wire."""
        return api.build_tick(seq=seq, t=self.t0 + seq / self.tick_hz,
                              tick_hz=self.tick_hz, t0=self.t0, mode="wall")

    def _pulse(self):
        seq, step = self._seq, self._step
        t = self.t0 + seq / self.tick_hz
        self._emit(api.TICK, json.dumps(self._tick(seq)))

        sensors = self._sensors(step)
        stale = self._stale_sources(step)
        ap_values, unknown = self._aps(sensors, stale)
        confidence = 0.5 if stale else 1.0
        # Bound rather than built twice: the echo reports the same `samples_this_tick`
        # the row table above it shows, and two calls could not be relied on to agree.
        health = self._health(step, stale)
        self._emit(api.OBSERVATION, json.dumps(api.build_observation(
            seq=seq, t=t, step=step, sensors=sensors, ap_values=ap_values,
            unknown_aps=unknown, confidence=confidence,
            data_health=health)))

        self._emit(api.VERDICT, json.dumps(self._verdict(seq, t, step, ap_values,
                                                         unknown, stale, confidence)))

        # Last, and inside `_pulse`, which is the half of `_run` a pause does not
        # reach. A paused monitor is not watching, and an echo going out under one
        # would be the pane contradicting the banner above it.
        if self._echo is not None and self._echo.selected is not None:
            frame = self._raw_echo(seq, t, step, health, sensors)
            if frame is not None:
                self._emit(api.RAW_ECHO, json.dumps(frame))
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
        return _with_phase_guards(api.build_verdict(
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
        ), phase_guards(self.spec, phase_index, ap_values))


def _max_steps(spec, phase_index):
    phases = spec.get("execution_phases") or []
    if phase_index is None or not (0 <= phase_index < len(phases)):
        return None
    bounds = phases[phase_index].get("timing_bounds") or {}
    value = bounds.get("max_steps")
    return value if isinstance(value, int) else None
