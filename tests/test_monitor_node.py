"""The monitor node's wiring, driven without a ROS graph.

`core/manifest.py` holds the decisions and `tests/test_manifest.py` pins them. This
file pins the ~600 lines that *feed* those decisions, because that is where three
safety-relevant defects lived: which wire is allowed to step the automaton, what the
ledger is handed when the clock restarts, and which rows reach the verdict builder at
all. None of those are visible from a pure function's arguments.

`tests/ros_stub.py` supplies the graph. The automaton is faked outright -- `MultiMonitor`
needs `spot`, and what these tests need from it is a count of how many times it was
stepped, which a real one would only obscure.
"""

from __future__ import annotations

import importlib
import json
import sys

import pytest

import ros_stub

pytestmark = pytest.mark.skipif(
    ros_stub.real_ros_present(),
    reason="a real rclpy is installed; these tests drive a stub and must not shadow it",
)

ros_stub.install()

import skill_monitor                                            # noqa: E402
from skill_monitor.backend import monitor_node                  # noqa: E402
from skill_monitor.core import api, automata, manifest          # noqa: E402
from skill_monitor.core.automata import (                       # noqa: E402
    FailureModeInfo,
    MonitorStatus,
)
from skill_monitor.core.monitor_action import Action            # noqa: E402


# =============================================================================
# A fake automaton
# =============================================================================

class FakeAut:
    def state_is_accepting(self, _state) -> bool:
        return False


class FakeEdge:
    """One outgoing transition, with the two attributes `LTLMonitor.graph()` reads."""

    def __init__(self, dst, cond) -> None:
        self.dst = dst
        self.cond = cond


class WalkableAut:
    """Enough of a spot `twa_graph` for `LTLMonitor.graph()` to walk end to end.

    Spot is not installed on this host, so a fake is the only way `graph()` can be
    driven at all -- and it is the same substitution this file already makes for the
    automaton as a whole (see the module docstring). It answers exactly the five calls
    `graph()` makes and nothing else, which is the check that `graph()` really is a
    thin walk and asks nothing new of the library.

    The default is a three-state chain: 0 --mission_started--> 1 --path_active--> 2,
    with 2 accepting and self-looping.
    """

    def __init__(self, edges=None, accepting=(2,), initial=0) -> None:
        self._edges = edges if edges is not None else {
            0: [(0, "!mission_started"), (1, "mission_started")],
            1: [(1, "!path_active"), (2, "path_active")],
            2: [(2, "1")],
        }
        self._accepting = set(accepting)
        self._initial = initial

    def num_states(self) -> int:
        return len(self._edges)

    def get_init_state_number(self) -> int:
        return self._initial

    def state_is_accepting(self, state) -> bool:
        return state in self._accepting

    def out(self, state):
        return [FakeEdge(dst, cond) for dst, cond in self._edges.get(state, ())]


def a_real_monitor(monkeypatch, name="full_navigation_sequence", *,
                   formula="F(mission_started && F(path_active))",
                   aut=None, sinks=()):
    """A genuine `LTLMonitor` wrapped around a fake automaton.

    Built with `object.__new__` because `__init__` calls `spot.translate`, which this
    host cannot do. `graph()` needs nothing else: `name`, `formula`, `aut`, `bdict` and
    `_sink_states` are the whole of its input, which is exactly why it could be written
    with no new Spot calls. `bdict` is opaque -- it is only ever handed straight back
    to `bdd_format_formula`, which here returns the label the fake edge carries.
    """
    monkeypatch.setattr(
        automata.spot, "bdd_format_formula",
        lambda bdict, cond: str(cond), raising=False,
    )
    m = object.__new__(automata.LTLMonitor)
    m.name, m.formula = name, formula
    m.aut, m.bdict = (aut or WalkableAut()), object()
    m._sink_states = set(sinks)
    m._initial_state = m.aut.get_init_state_number()
    m.current_state = m._initial_state
    return m


class FakeMonitor:
    """One LTL monitor. `violated_when` decides its status from the observation, which
    is how a test says "this is the tick the collision formula breaks" without spot."""

    def __init__(self, name, formula, failure_mode=None, violated_when=None,
                 current_state=0) -> None:
        self.name = name
        self.formula = formula
        self.failure_mode = failure_mode
        self.status = MonitorStatus.INCONCLUSIVE
        #: What the verdict reports as this monitor's automaton state. Settable, and
        #: allowed to be None: a monitor that cannot say which state it is in is the
        #: degrade path the contract's nullable `state` exists for.
        self.current_state = current_state
        self._violated_when = violated_when or (lambda obs: False)
        self._initial_state = 0
        self._sink_states: set[int] = set()
        self.aut = FakeAut()

    def step(self, observation) -> MonitorStatus:
        if self.status is not MonitorStatus.VIOLATED and self._violated_when(observation):
            self.status = MonitorStatus.VIOLATED
        return self.status

    def reset(self) -> None:
        self.status = MonitorStatus.INCONCLUSIVE

    def get_required_aps(self) -> set:
        return set()

    def format_automaton(self, **_kwargs) -> str:
        """The console dump `reload_specs` prints on a spec load. Nothing in this file
        reads stdout; it exists so a reload can be driven at all."""
        return f"  [fake automaton for {self.name}]"


class FakeMulti:
    def __init__(self, monitors, graphs=None) -> None:
        self.monitors = list(monitors)
        #: One entry per `step()`. The whole point of the fake.
        self.steps: list[dict] = []
        #: What `graphs()` hands back. None -- the default -- is the degrade path: a
        #: monitor this build cannot describe, which must still publish a valid
        #: manifest, simply without an `automata` key.
        self._graphs = graphs

    def graphs(self):
        return self._graphs

    def step(self, observation) -> dict:
        self.steps.append(dict(observation))
        for m in self.monitors:
            m.step(observation)
        return self.statuses()

    def statuses(self) -> dict:
        return {m.name: m.status for m in self.monitors}

    def __iter__(self):
        return iter(self.monitors)

    def reset(self) -> None:
        for m in self.monitors:
            m.reset()

    def all_accepted(self) -> bool:
        return all(m.status is MonitorStatus.ACCEPTED for m in self.monitors)

    def any_violated(self) -> bool:
        return any(m.status is MonitorStatus.VIOLATED for m in self.monitors)

    def get_required_aps(self) -> set:
        return set()

    def get_violated_failure_modes(self) -> list:
        return [
            (m, m.failure_mode)
            for m in self.monitors
            if m.failure_mode is not None and m.status is MonitorStatus.VIOLATED
        ]

    def get_failure_mode_monitors(self) -> list:
        return [m for m in self.monitors if m.failure_mode is not None]

    def get_property_monitors(self) -> list:
        return [m for m in self.monitors if m.failure_mode is None]


# =============================================================================
# A node
# =============================================================================

class Args:
    changes_only = True          # keeps the console quiet; nothing here reads stdout
    stop_on_violation = False
    passive = False
    formulas_file = None
    output_dir = None


def a_spec(**overrides) -> dict:
    """A small spec with one property formula, one SAFETY failure mode and one phase."""
    spec = {
        "skill_name": "TestSkill",
        "atomic_propositions": {
            "collision_risk": "True when min_range < 0.25. An obstacle is too close.",
            "upright": "True when upright_flag > 0.5. The base is standing.",
            "path_active": "True when nav_state in ['following']. There is a path.",
        },
        "ltl_formulas": [{"name": "nav", "formula": "F(path_active)"}],
        "named_failure_modes": [{
            "name": "collision_imminent",
            "formula": "G(!collision_risk)",
            "fault_category": "SAFETY",
            "description": "The robot must never get too close to an obstacle.",
        }],
        "execution_phases": [],
        "terminal_success": {"condition": "False"},
        "terminal_failure": {"condition": "False"},
    }
    spec.update(overrides)
    return spec


def an_adapter() -> dict:
    """Four required sources. `battery` feeds no AP in the spec above, which is the
    whole point: its silence must not grade a collision the depth camera saw."""
    return api.build_adapter(
        adapter="test_robot", doc="", tick_hz=1.0,
        schema={
            "min_range": {}, "upright_flag": {}, "nav_state": {}, "battery_v": {},
        },
        sources=[
            {"id": "points", "topic": "/points", "type": "T", "expected_hz": 15.0,
             "max_age_s": 0.5, "required": True, "tracked": True,
             "keys": ["min_range"], "steps": []},
            {"id": "odom", "topic": "/odom", "type": "T", "expected_hz": 50.0,
             "max_age_s": 0.5, "required": True, "tracked": True,
             "keys": [],
             # Derived: only the step names it, which is the case `_source_keys` exists
             # for -- `upright_flag` is computed from base_roll/pitch/height.
             "steps": [{"keys": ["upright_flag"], "aggregate": "last", "on": "message"}]},
            {"id": "status", "topic": "/status", "type": "T", "expected_hz": 5.0,
             "max_age_s": 1.0, "required": True, "tracked": True,
             "keys": ["nav_state"], "steps": []},
            {"id": "battery", "topic": "/battery", "type": "T", "expected_hz": 1.0,
             "max_age_s": 5.0, "required": True, "tracked": True,
             "keys": ["battery_v"], "steps": []},
        ],
    )


def a_node(spec_dict=None, *, monitors=None, adapter=None, graphs=None, multi=None):
    spec = monitor_node.spec_from_dict(spec_dict or a_spec())
    if monitors is None:
        monitors = [
            FakeMonitor("nav", "F(path_active)"),
            FakeMonitor(
                "collision_imminent", "G(!collision_risk)",
                failure_mode=FailureModeInfo(
                    name="collision_imminent", fault_category="SAFETY",
                    description="too close",
                ),
                violated_when=lambda obs: obs.get("collision_risk") is True,
            ),
        ]
    node = monitor_node.LtlMonitorNode(
        spec, multi if multi is not None else FakeMulti(monitors, graphs), Args()
    )
    if adapter is not None:
        node.adapter_callback(ros_stub.Message(json.dumps(adapter)))
    return node


#: Passed as `t0` to omit the field entirely -- a clock predating P1. `None` cannot mean
#: this: `None` is a legal JSON value and would be a *malformed* t0, not an absent one.
NO_T0 = object()


def tick(node, seq, *, t0=0.0, tick_hz=1.0):
    payload = api.build_tick(seq=seq, t=float(seq), tick_hz=tick_hz, t0=0.0, mode="wall")
    if t0 is NO_T0:
        payload.pop("t0")
    else:
        payload["t0"] = t0
    node.tick_callback(ros_stub.Message(json.dumps(payload)))


def observe(node, seq, *, aps=None, stale=(), confidence=1.0, wire=api.OBSERVATION):
    """Deliver one observation on `wire`. `stale` names sources that did not refresh."""
    sources = ("points", "odom", "status", "battery")
    payload = api.build_observation(
        seq=seq, t=float(seq), step=seq,
        sensors={},
        ap_values=aps if aps is not None else {"path_active": True},
        confidence=confidence,
        data_health={
            sid: {"rate_hz": 1.0, "expected_hz": 1.0, "age_s": 0.1,
                  "samples_this_tick": 1, "refreshed": sid not in stale, "dropped": 0}
            for sid in sources
        },
    )
    if wire == api.OBSERVATION:
        node.observation_callback(ros_stub.Message(json.dumps(payload)))
    else:
        node.legacy_eval_callback(ros_stub.Message(json.dumps(payload)))


def legacy_observe(node, aps=None):
    """The flat, seq-less `/ltl/evaluations` shape P3 still publishes."""
    node.legacy_eval_callback(ros_stub.Message(json.dumps(
        aps if aps is not None else {"path_active": True}
    )))


def verdicts(node) -> list[dict]:
    return [json.loads(m) for m in node.publishers[api.VERDICT].sent]


# =============================================================================
# 1. A restarted clock must not deafen the monitor
# =============================================================================

def test_a_restarted_clock_is_a_new_epoch_not_a_deaf_monitor():
    """The clock container restarts and republishes from 0. Every observation after it
    used to be refused as stale -- zero verdicts for the rest of the process's life,
    with `reset` deliberately keeping `last_seq` so an operator could not recover it."""
    node = a_node()
    for seq in (197, 198, 199):
        tick(node, seq, t0=1000.0)
        observe(node, seq)
    assert len(node.multi.steps) == 3

    # …the clock restarts: seq starts again at 0, and `t0` is the discriminator.
    for seq in (0, 1):
        tick(node, seq, t0=2000.0)
        observe(node, seq)

    assert len(node.multi.steps) == 5, "the monitor went deaf after the clock restarted"
    assert [v["seq"] for v in verdicts(node)] == [197, 198, 199, 0, 1]
    assert node.ledger.epochs == 1


def test_one_straggler_from_the_old_epoch_does_not_cost_the_rest_of_the_run():
    """The epoch rides `/monitor/tick` and the seq rides `/monitor/observation`, so an
    observation from the old epoch can arrive after the new clock's first pulse. Adopted
    as the new epoch's high-water mark it refused every genuine tick beneath it: 5001
    consecutive refusals for an epoch that reached 5000 -- roughly eight minutes of no
    stepping at 10 Hz -- and `missed_ticks` read 0 the whole way, because it only moves
    on a step that happened."""
    node = a_node()
    for seq in (4998, 4999, 5000):
        tick(node, seq, t0=1000.0)
        observe(node, seq)
    assert len(node.multi.steps) == 3

    tick(node, 0, t0=2000.0)          # the clock restarts…
    observe(node, 5000)               # …and the old epoch's tail arrives after it
    assert len(node.multi.steps) == 3, "a straggler stepped as the new epoch's first tick"
    assert node.ledger.ahead == 1
    assert node.ledger.last_seq is None

    for seq in range(1, 21):
        tick(node, seq, t0=2000.0)
        observe(node, seq)
    assert len(node.multi.steps) == 23, "the restarted stream was refused underneath it"
    assert [v["seq"] for v in verdicts(node)][-3:] == [18, 19, 20]


def test_a_refusal_burst_does_not_become_its_own_outage_in_the_log():
    """5001 unthrottled warn lines drown the one line that says what happened."""
    node = a_node()
    tick(node, 1)
    observe(node, 1)
    for _ in range(250):
        observe(node, 1)

    refusals = [w for w in node.get_logger().at("warn") if "not stepping again" in w]
    assert len(refusals) == 3            # the first, then one per 100
    assert "200 refused in a row" in refusals[-1]

    # …and the burst is closed on the console when stepping resumes.
    tick(node, 2)
    observe(node, 2)
    assert any("Stepping again after 250" in line for line in node.get_logger().at("info"))


def test_a_clock_that_never_sends_t0_is_refused_without_taking_the_run_with_it():
    """P1 has landed: `t0` is a required field, so a pulse without one is a producer
    that cannot be told apart from any other producer -- the exact ambiguity `t0`
    exists to prevent -- and it is refused. What must NOT happen is the refusal
    propagating: the observation stream carries its own `seq` and keeps stepping the
    automaton, so a clock too old to talk to costs the epoch, not the monitoring."""
    node = a_node()
    for seq in (10, 11):
        tick(node, seq, t0=NO_T0)
        observe(node, seq)
    observe(node, 9)
    assert len(node.multi.steps) == 2       # still monitoring
    assert node.ledger.epoch is None        # but it never adopted an epoch
    assert node.clock_seq != 11             # and the pulse itself never landed


def test_a_nan_t0_does_not_void_one_step_per_tick():
    """A clock with an uninitialised `t0` publishes bare `NaN` -- `json.dumps` emits it
    and `json.loads` accepts it. `nan != nan`, so `epoch != self.clock_epoch` was true on
    every pulse: a new epoch adopted each tick, `last_seq` back to None each tick, and
    every observation admitted. These seven arrivals of five indices -- three
    redeliveries and two backwards jumps -- were seven steps, with `redelivered` reading
    0 so nothing in the verdict stream indicated it."""
    node = a_node()
    for seq in (10, 10, 10, 11, 9, 11, 5):
        node.tick_callback(ros_stub.Message(
            '{"schema_version": 1, "seq": %d, "t": %d.0, "tick_hz": 1.0, '
            '"mode": "wall", "t0": NaN}' % (seq, seq)
        ))
        observe(node, seq)

    assert len(node.multi.steps) == 2, "a NaN t0 re-admitted every redelivery"
    assert node.clock_epoch is None
    assert node.ledger.epochs == 0
    assert node.ledger.redelivered == 5
    assert [v["seq"] for v in verdicts(node)] == [10, 11]


def test_a_tick_carrying_a_field_this_build_does_not_know_is_still_a_tick():
    """`api.validate_tick` closes the payload, so P1's `t0` reads as an unknown field.
    Dropping the pulse for that reason would make the monitor deaf to the very clock
    that tells it about restarts."""
    node = a_node()
    tick(node, 5, t0=1000.0, tick_hz=4.0)
    assert node.tick_hz == 4.0
    assert node.clock_epoch == 1000.0
    assert not [line for line in node.get_logger().at("warn") if "Malformed" in line]

    # A genuinely malformed tick is still refused.
    node.tick_callback(ros_stub.Message(json.dumps({"schema_version": 1, "seq": "x"})))
    assert any("Malformed" in line for line in node.get_logger().at("warn"))


# =============================================================================
# 2. One tick on two wires is one step
# =============================================================================

def test_a_tick_delivered_on_both_wires_steps_the_automaton_once():
    """docs/api.md guarantees both wires are live during the migration. Four clock ticks
    used to produce five automaton steps: the legacy copy had no `seq`, was given
    `last_seq + 1`, and from then on the real envelope looked redelivered -- so
    `verdict.seq` became a counter unrelated to the clock."""
    node = a_node()
    for seq in (1, 2, 3, 4):
        tick(node, seq)
        observe(node, seq)                       # the envelope
        legacy_observe(node)                     # …and the legacy copy of the same tick

    assert len(node.multi.steps) == 4, "the automaton double-stepped"
    assert [v["seq"] for v in verdicts(node)] == [1, 2, 3, 4]


def test_the_legacy_wire_still_drives_a_stack_where_p3_has_not_landed():
    """Dropping it outright would leave the un-migrated stack with no verdicts at all
    for a whole release."""
    node = a_node()
    for _ in range(3):
        legacy_observe(node)
    assert len(node.multi.steps) == 3
    assert [v["seq"] for v in verdicts(node)] == [0, 1, 2]


def test_a_legacy_control_signal_is_honoured_even_once_the_envelope_wins():
    """The LLM client's `__reset__` rides the legacy wire. Demoting that wire from
    *stepping* must not deafen the monitor to the only reset it can hear."""
    node = a_node()
    observe(node, 1)
    node.halted = True
    legacy_observe(node, {"__reset__": True})
    assert node.halted is False


# =============================================================================
# 3. Confidence is per failure mode
# =============================================================================

def test_a_quiet_battery_does_not_de_escalate_a_collision_the_camera_saw():
    """One global freshness number stamped on every mode graded a real
    `collision_imminent` at 0.34 -- WARN, not HALT -- because an unrelated topic had
    gone quiet. The supervisor then did not zero /cmd_vel, and
    `ablation_runner.safety_fault_from_verdict` did not even record a safety fault."""
    node = a_node(adapter=an_adapter())
    tick(node, 1)
    observe(node, 1, aps={"collision_risk": True, "upright": True},
            stale=["battery"], confidence=0.34)

    v = verdicts(node)[-1]
    collision = next(fm for fm in v["failure_modes"] if fm["name"] == "collision_imminent")
    assert collision["confidence"] == 1.0        # its own source is perfectly fresh
    assert v["intervention"]["action"] == "ABORT"
    assert Action[v["intervention"]["action"]] >= Action.HALT


def test_a_collision_seen_by_a_dead_camera_is_still_de_escalated():
    """Safety is not softened away, only de-escalated while its *own* evidence is weak."""
    node = a_node(adapter=an_adapter())
    tick(node, 1)
    observe(node, 1, aps={"collision_risk": True, "upright": True},
            stale=["points"], confidence=0.34)

    v = verdicts(node)[-1]
    collision = next(fm for fm in v["failure_modes"] if fm["name"] == "collision_imminent")
    assert collision["confidence"] == 0.0
    assert v["intervention"]["action"] == "WARN"


def test_a_breach_the_camera_cannot_support_does_not_grade_one_the_imu_proves():
    """Two SAFETY modes breach on the same tick and the evidence for them is not the
    same: the depth camera is dead, so `collision_imminent` grades 0.0, while the fresh
    odometry proves `fell_over` at 1.0. The rung came from whichever mode the spec
    authored first, so in `formulas_g1.json`'s order a robot on the floor was published
    as WARN and this node did not halt -- a de-escalation meant to hold back one fault's
    own weak evidence, spent on suppressing a different fault's perfect evidence."""
    def a_pair(blind_first: bool) -> list:
        crash = FakeMonitor(
            "collision_imminent", "G(!collision_risk)",
            failure_mode=FailureModeInfo(name="collision_imminent",
                                         fault_category="SAFETY",
                                         description="too close"),
            violated_when=lambda obs: obs.get("collision_risk") is True,
        )
        fell = FakeMonitor(
            "fell_over", "G(upright)",
            failure_mode=FailureModeInfo(name="fell_over", fault_category="SAFETY",
                                         description="on the floor"),
            violated_when=lambda obs: obs.get("upright") is False,
        )
        return [crash, fell] if blind_first else [fell, crash]

    for blind_first in (True, False):
        node = a_node(monitors=a_pair(blind_first), adapter=an_adapter())
        tick(node, 1)
        observe(node, 1, aps={"collision_risk": True, "upright": False},
                stale=["points"], confidence=0.5)

        v = verdicts(node)[-1]
        graded = {fm["name"]: fm["confidence"] for fm in v["failure_modes"]}
        assert graded == {"collision_imminent": 0.0, "fell_over": 1.0}
        assert v["intervention"]["action"] == "ABORT", "list position decided the rung"
        assert v["intervention"]["confidence"] == 1.0
        # The evidence names the entry the rung was graded from, in either order.
        assert manifest.breached_mode(v["failure_modes"])["name"] == "fell_over"
        assert node.halted is True


def test_with_no_adapter_announced_the_global_scalar_is_all_there_is():
    """Nothing says which source feeds which AP, so the observation's own number is the
    honest answer -- and it is documented as the fallback, not as the design."""
    node = a_node()
    tick(node, 1)
    observe(node, 1, aps={"collision_risk": True}, confidence=0.34)
    v = verdicts(node)[-1]
    assert v["failure_modes"][0]["confidence"] == 0.34
    assert v["intervention"]["action"] == "WARN"


def test_the_node_halts_exactly_when_the_token_it_published_says_halt():
    """The node used to call `_halt()` regardless, so on the same tick its behaviour and
    the token it published were two different decisions."""
    sure = a_node(adapter=an_adapter())
    tick(sure, 1)
    observe(sure, 1, aps={"collision_risk": True}, stale=["battery"], confidence=0.34)
    assert sure.halted is True
    assert manifest.token_halts(verdicts(sure)[-1]["intervention"]["action"])

    unsure = a_node(adapter=an_adapter())
    tick(unsure, 1)
    observe(unsure, 1, aps={"collision_risk": True}, stale=["points"], confidence=0.34)
    assert unsure.halted is False
    assert not manifest.token_halts(verdicts(unsure)[-1]["intervention"]["action"])

    # …and the same fault halts as soon as its own data is fresh again.
    tick(unsure, 2)
    observe(unsure, 2, aps={"collision_risk": True}, confidence=1.0)
    assert unsure.halted is True


# =============================================================================
# 4. A phase fault reaches the token
# =============================================================================

def _g1_spec() -> dict:
    return json.loads(skill_monitor.spec_path("g1").read_text())


def test_a_phase_invariant_breach_reaches_the_intervention_token():
    """All three phases in the shipped G1 spec declare `invariant_fault_category:
    "SAFETY"`. The breach halted this process and published CONTINUE, so P5 -- which is
    contracted to obey the token and nothing else -- would not have stopped the robot."""
    node = a_node(_g1_spec(), monitors=[FakeMonitor("nav", "F(path_active)")])
    tick(node, 1)
    observe(node, 1, aps={"mission_started": True, "upright": True,
                          "collision_risk": False})
    tick(node, 2)
    observe(node, 2, aps={"mission_started": True, "upright": False,
                          "collision_risk": False})

    v = verdicts(node)[-1]
    breach = next(
        fm for fm in v["failure_modes"] if fm["name"].startswith("phase:")
    )
    assert breach["fault_category"] == "SAFETY"
    assert breach["status"] == "VIOLATED"
    assert v["intervention"]["action"] == "ABORT"
    assert node.halted is True


def test_a_phase_timeout_reaches_the_token_too():
    """TIMEOUT and precondition faults have no named-mode cover in any spec."""
    spec = a_spec(execution_phases=[{
        "phase": "Approach",
        "enter_condition": "path_active",
        "invariant": "upright",
        "invariant_fault_category": "SAFETY",
        "progress_condition": "True",
        "exit_condition": "False",
        "timing_bounds": {"max_steps": 2},
    }])
    node = a_node(spec, monitors=[FakeMonitor("nav", "F(path_active)")])
    for seq in (1, 2, 3, 4):
        tick(node, seq)
        observe(node, seq, aps={"path_active": True, "upright": True})

    v = verdicts(node)[-1]
    timeout = next(fm for fm in v["failure_modes"] if fm["name"].endswith(":timeout"))
    assert timeout["fault_category"] == "TIMEOUT"
    assert v["intervention"]["action"] == "REPLAN"
    # A timeout is counted in ticks, not sensed, so no source's silence weakens it.
    assert timeout["confidence"] == 1.0
    # …and "the episode is over" still ends the run, as it did before the token existed.
    assert node.halted is True


def test_a_phase_fault_reaches_the_un_migrated_supervisor_too():
    """The legacy `/ltl/state_description` is the only thing P5's current node reads,
    and a phase fault it does not halt on is one it would otherwise never hear about.

    (A phase fault that *does* halt reaches it as the `state: halt` frame `_halt`
    already sends, which is the legacy stack's stop signal.)"""
    spec = a_spec(execution_phases=[{
        "phase": "Approach",
        "enter_condition": "path_active",
        "invariant": "upright",
        "invariant_fault_category": "SAFETY",
        "progress_condition": "True",
        "exit_condition": "False",
    }])
    node = a_node(spec, monitors=[FakeMonitor("nav", "F(path_active)")],
                  adapter=an_adapter())
    tick(node, 1)
    observe(node, 1, aps={"path_active": True, "upright": True})
    tick(node, 2)
    # `upright` is computed from odom, and odom stopped publishing: the invariant reads
    # as breached, but on evidence that cannot support stopping the robot.
    observe(node, 2, aps={"path_active": True, "upright": False}, stale=["odom"])

    v = verdicts(node)[-1]
    breach = next(fm for fm in v["failure_modes"] if fm["name"].startswith("phase:"))
    assert breach["confidence"] == 0.0
    assert v["intervention"]["action"] == "WARN"
    assert node.halted is False

    states = [json.loads(m) for m in node.publishers[monitor_node._LEGACY_STATE_DESC].sent]
    latest = [s for s in states if "named_failure_modes" in s][-1]
    assert any(fm["name"].startswith("phase:") for fm in latest["named_failure_modes"])


# =============================================================================
# 5. An unrecognised fault category must not halt the robot
# =============================================================================

def test_a_mistyped_fault_category_does_not_abort_the_mission():
    """`core/automata.py` documents "NAVIGATION" as an example category, so a name this
    build does not enumerate is an expected input. It used to grade ABORT."""
    spec = a_spec(named_failure_modes=[{
        "name": "wandered", "formula": "G(!collision_risk)",
        "fault_category": "SAFTEY", "description": "typo",
    }])
    node = a_node(spec, monitors=[
        FakeMonitor("nav", "F(path_active)"),
        FakeMonitor(
            "wandered", "G(!collision_risk)",
            failure_mode=FailureModeInfo(name="wandered", fault_category="SAFTEY",
                                         description="typo"),
            violated_when=lambda obs: obs.get("collision_risk") is True,
        ),
    ])
    tick(node, 1)
    observe(node, 1, aps={"collision_risk": True})

    v = verdicts(node)[-1]
    assert v["failure_modes"][0]["fault_category"] == manifest.UNCLASSIFIED_CATEGORY
    assert Action[v["intervention"]["action"]] < Action.HALT
    assert api.validate_verdict(v) == []


def test_a_pushed_spec_with_a_fault_category_this_build_cannot_grade_is_rejected():
    """The rung is deliberately mild, so the loudness has to live at load time -- where
    the author can still see the name they mistyped."""
    node = a_node()
    bad = a_spec(named_failure_modes=[{
        "name": "wandered", "formula": "G(!collision_risk)",
        "fault_category": "SAFTEY",
    }])
    node.load_spec_callback(ros_stub.Message(json.dumps(bad)))

    status = json.loads(node.publishers[api.SPEC_STATUS].sent[-1])
    assert status["ok"] is False
    assert any("SAFTEY" in p for p in status["problems"])
    assert node.spec.skill_name == "TestSkill"      # …and it was not adopted

    # The same spec spelled correctly is accepted.
    good = a_spec(named_failure_modes=[{
        "name": "wandered", "formula": "G(!collision_risk)",
        "fault_category": "SAFETY",
    }])
    node.load_spec_callback(ros_stub.Message(json.dumps(good)))
    assert json.loads(node.publishers[api.SPEC_STATUS].sent[-1])["ok"] is True


# =============================================================================
# `verdict()`'s input mapping
# =============================================================================

def test_the_verdict_maps_every_piece_of_node_state_onto_the_payload():
    """Defects 3 and 5 both lived in this mapping rather than in the builder it calls."""
    node = a_node(adapter=an_adapter())
    tick(node, 41, tick_hz=2.0)
    observe(node, 41, aps={"path_active": True}, stale=["battery"], confidence=0.5)

    v = verdicts(node)[-1]
    assert api.validate_verdict(v) == []
    assert v["seq"] == 41 and v["t"] == 41.0
    assert isinstance(v["step"], int)
    assert v["skill_name"] == "TestSkill"
    assert v["risk"]["stale_sources"] == ["battery"]
    assert v["risk"]["trigger_confidence"] == 0.5
    assert v["missed_ticks"] == 0
    assert [fm["name"] for fm in v["failure_modes"]] == ["collision_imminent"]
    # `state` rides every formula row: the automaton graph is latched on the manifest,
    # so all a tick has to carry is which node of it this monitor is in.
    assert v["formulas"] == [{"name": "nav", "status": "INCONCLUSIVE", "state": 0}]


def test_a_gap_in_the_tick_stream_is_reported_not_interpolated():
    node = a_node()
    tick(node, 1)
    observe(node, 1)
    tick(node, 5)
    observe(node, 5)
    assert len(node.multi.steps) == 2
    assert verdicts(node)[-1]["missed_ticks"] == 3


def test_a_redelivered_tick_publishes_no_second_verdict():
    node = a_node()
    tick(node, 1)
    observe(node, 1)
    observe(node, 1)
    assert len(node.multi.steps) == 1
    assert len(verdicts(node)) == 1


# =============================================================================
# …and what the ablation records off the same verdict
# =============================================================================

def test_the_ablation_records_the_fault_the_token_was_graded_from():
    """`safety_fault_from_verdict` gates on `action >= HALT`, so a collision graded WARN
    by an unrelated stale topic did not even count as a safety fault -- the ablation
    numbers moved. And the name it records is now the mode the token was graded from,
    which stopped being the first VIOLATED entry the moment phase faults joined the
    list."""
    from skill_monitor.backend import ablation_runner

    node = a_node(adapter=an_adapter())
    tick(node, 1)
    observe(node, 1, aps={"collision_risk": True}, stale=["battery"], confidence=0.34)
    assert ablation_runner.safety_fault_from_verdict(verdicts(node)[-1]) \
        == "collision_imminent"

    quiet = a_node(adapter=an_adapter())
    tick(quiet, 1)
    observe(quiet, 1, aps={"collision_risk": False})
    assert ablation_runner.safety_fault_from_verdict(verdicts(quiet)[-1]) is None

    # Two breaches on one tick: the safety one is what the token graded, and what the
    # episode is recorded under.
    assert ablation_runner.safety_fault_from_verdict({
        "intervention": {"action": "ABORT", "category": "SAFETY"},
        "failure_modes": [
            {"name": "phase:Approach:progress", "fault_category": "PROGRESS",
             "status": "VIOLATED"},
            {"name": "fell_over", "fault_category": "SAFETY", "status": "VIOLATED"},
        ],
    }) == "fell_over"


# =============================================================================
# …and the stub itself: standing aside on a machine that has real ROS
# =============================================================================

_ROS_MODULES = (
    "rclpy", "rclpy.node", "rclpy.qos",
    "std_msgs", "std_msgs.msg", "geometry_msgs", "geometry_msgs.msg",
)


def test_real_ros_present_answers_the_same_after_the_stub_is_installed():
    """It is called from `install()`, which runs when the stub may already be in
    `sys.modules` from another test module. `importlib.util.find_spec` raises
    `ValueError: rclpy.__spec__ is None` for a `types.ModuleType`, so asking it about an
    installed stub turned the guard into a crash instead of an answer."""
    assert sys.modules["rclpy"]._is_skill_monitor_stub is True
    assert ros_stub.real_ros_present() is False


def test_the_stub_stands_aside_for_an_installed_but_unimported_rclpy(tmp_path,
                                                                    monkeypatch):
    """The docstring promised `install()` refuses to run when a real `rclpy` is
    importable; the only guard was `"rclpy" not in sys.modules`, and a real ROS that no
    one has imported yet is not in `sys.modules`. On a ROS machine that replaced rclpy,
    std_msgs and geometry_msgs for the whole pytest process -- and `pytestmark` does not
    save it, because skipif suppresses tests while `install()` runs at module scope."""
    real = tmp_path / "rclpy"
    real.mkdir()
    (real / "__init__.py").write_text("_is_the_real_thing = True\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    saved = {name: sys.modules[name] for name in _ROS_MODULES if name in sys.modules}
    for name in _ROS_MODULES:
        sys.modules.pop(name, None)
    importlib.invalidate_caches()
    try:
        assert ros_stub.real_ros_present() is True
        assert ros_stub.install() is None
        assert "rclpy" not in sys.modules, "the stub was installed over a real rclpy"
        assert "std_msgs" not in sys.modules
        assert "geometry_msgs" not in sys.modules
    finally:
        sys.modules.update(saved)

    # …and with no real rclpy on the path it still installs, idempotently.
    assert ros_stub.install() is sys.modules["rclpy"]


# =============================================================================
# 5. A monitor that stops stepping must say so
# =============================================================================

def test_a_monitor_that_stops_stepping_says_so_on_the_verdict_topic():
    """The failure this closes: the envelope publisher dies while the legacy one keeps
    going, and `_on_observation` returns above the ledger, above missed-tick accounting
    and above every log statement. Fifty legacy messages produced zero steps, zero
    verdicts and zero log lines — a safety monitor that had stopped monitoring and said
    nothing at all. The clock is a different publisher and is still ticking, so it is
    the one thing left that knows time is passing.
    """
    node = a_node()
    tick(node, 1)
    observe(node, 1)
    before = len(verdicts(node))

    last_pulse = 1 + monitor_node._STALL_TICKS + 1
    for seq in range(2, last_pulse + 1):
        tick(node, seq)

    stall = verdicts(node)[before:]
    assert stall, "the clock advanced with no step and the monitor published nothing"
    # A tick with no observation is exactly "not enough data", so the stall frame
    # lands in the vocabulary already specified for it rather than a new one.
    assert stall[-1]["verdict"] == "INCONCLUSIVE_NO_DATA"
    assert stall[-1]["seq"] == last_pulse, \
        "the frame carries the clock's index, not a stale observation's"
    assert stall[-1]["missed_ticks"] >= monitor_node._STALL_TICKS


def test_a_halted_monitor_is_allowed_to_be_quiet():
    """A halted monitor is supposed to be silent. Crying wolf there would teach an
    operator to ignore the one indication that matters."""
    node = a_node()
    tick(node, 1)
    node.halted = True
    before = len(verdicts(node))
    for seq in range(2, 15):
        tick(node, seq)
    assert verdicts(node)[before:] == []


def test_the_stall_detector_can_still_see_across_a_clock_restart():
    """`_silent_since` held a `seq` from the epoch that ended, and the new clock counts
    from its own beginning, so `clock_seq - _silent_since` was negative for as long as
    the previous run was longer than this one. The detector went quiet for exactly the
    stretch it exists to report: a monitor that has stopped stepping, saying nothing."""
    node = a_node()
    for seq in range(1, 201):                 # a long, healthy run on the first clock
        tick(node, seq, t0=1000.0)
        observe(node, seq)
    assert node._stalled is False
    mark = len(verdicts(node))

    for seq in range(1, 60):                  # the clock restarts; nothing steps again
        tick(node, seq, t0=2000.0)

    stall = verdicts(node)[mark:]
    assert stall, "59 pulses of silence on a new clock and the monitor published nothing"
    assert node._stalled is True
    assert stall[-1]["verdict"] == "INCONCLUSIVE_NO_DATA"
    assert stall[-1]["missed_ticks"] >= monitor_node._STALL_TICKS


def test_missed_ticks_is_a_count_and_never_goes_below_zero():
    """A negative `missed_ticks` reached the wire and `api.validate_verdict` accepted
    it: a consumer reconstructing the tick axis from `seq` and `missed_ticks` would have
    read the monitor as having seen more ticks than the clock ever sent."""
    node = a_node()
    for seq in range(1, 201):
        tick(node, seq, t0=1000.0)
        if seq <= 3:
            observe(node, seq)                # stalls early, so the stall is already on
    mark = len(verdicts(node))

    for seq in range(1, 6):
        tick(node, seq, t0=2000.0)

    published = verdicts(node)[mark:]
    assert published, "the stall was already being announced; the restart did not end it"
    for v in published:
        assert v["missed_ticks"] >= 0
        assert api.validate_verdict(v) == []

    # …and the schema itself now refuses one, so no producer can ship it again.
    assert api.validate_verdict(dict(published[-1], missed_ticks=-2)) != []


def test_stepping_again_clears_the_stall():
    node = a_node()
    tick(node, 1)
    observe(node, 1)
    for seq in range(2, 2 + monitor_node._STALL_TICKS + 1):
        tick(node, seq)
    assert node._stalled is True

    resumed = 2 + monitor_node._STALL_TICKS
    tick(node, resumed)
    observe(node, resumed)
    assert node._stalled is False


def test_the_legacy_wire_is_readmitted_only_after_a_longer_silence():
    """Re-admission is deliberately slower than the indication: legacy arrivals carry no
    `seq` and are numbered from their own counter, so re-admitting a merely *slow*
    envelope double-steps the tick they share."""
    node = a_node()
    tick(node, 1)
    observe(node, 1)                       # the envelope wins from here
    legacy_observe(node)
    steps_after_demotion = len(verdicts(node))

    for seq in range(2, 2 + monitor_node._LEGACY_READMIT_TICKS + 1):
        tick(node, seq)
    assert node._legacy_readmitted is True

    legacy_observe(node)
    assert len(verdicts(node)) > steps_after_demotion, \
        "the legacy wire should step again once the envelope has gone quiet"


def test_a_returning_envelope_demotes_the_legacy_wire_again():
    node = a_node()
    tick(node, 1)
    observe(node, 1)
    for seq in range(2, 2 + monitor_node._LEGACY_READMIT_TICKS + 1):
        tick(node, seq)
    assert node._legacy_readmitted is True

    back = 2 + monitor_node._LEGACY_READMIT_TICKS
    tick(node, back)
    observe(node, back)
    assert node._legacy_readmitted is False
    before = len(verdicts(node))
    legacy_observe(node)
    assert len(verdicts(node)) == before, "the legacy copy must not step again"


# =============================================================================
# The automaton graph: latched once per spec, one integer per tick
#
# The console's automaton pane rendered nothing because the node published each
# formula's *status* and never the automaton behind it. Both halves land here: the
# graph on the latched manifest, where it costs one message per spec load, and the
# state integer on every verdict row. The third case these pin is the one that has to
# keep working when neither is available.
# =============================================================================

def a_graph(name="nav") -> dict:
    return {
        "name": name,
        "formula": "F(path_active)",
        "initial": 0,
        "states": [{"id": 0, "accepting": False, "sink": False},
                   {"id": 1, "accepting": True, "sink": False}],
        "edges": [{"from": 0, "to": 0, "label": "!path_active"},
                  {"from": 0, "to": 1, "label": "path_active"},
                  {"from": 1, "to": 1, "label": "1"}],
    }


def manifests(node) -> list[dict]:
    return [json.loads(m) for m in node.publishers[api.MANIFEST].sent]


def test_graph_walks_the_automaton_into_the_shape_the_contract_declares(monkeypatch):
    """`LTLMonitor.graph()` against a fake `aut`/`bdict`, which is the only way it can
    be run on a host with no spot. The assertion is the literal contract example."""
    m = a_real_monitor(monkeypatch)
    assert m.graph() == {
        "name": "full_navigation_sequence",
        "formula": "F(mission_started && F(path_active))",
        "initial": 0,
        "states": [{"id": 0, "accepting": False, "sink": False},
                   {"id": 1, "accepting": False, "sink": False},
                   {"id": 2, "accepting": True,  "sink": False}],
        "edges": [{"from": 0, "to": 0, "label": "!mission_started"},
                  {"from": 0, "to": 1, "label": "mission_started"},
                  {"from": 1, "to": 1, "label": "!path_active"},
                  {"from": 1, "to": 2, "label": "path_active"},
                  {"from": 2, "to": 2, "label": "1"}],
    }
    assert api.validate_automata([m.graph()]) == []


def test_a_sink_state_is_flagged_from_the_monitors_own_precomputed_set(monkeypatch):
    """`sink` is not derivable from `accepting` -- it is `_find_sink_states`' answer,
    and it is what tells a console the run is irrecoverable rather than merely not
    accepting yet."""
    m = a_real_monitor(monkeypatch, sinks=[1])
    states = {s["id"]: s for s in m.graph()["states"]}
    assert states[1] == {"id": 1, "accepting": False, "sink": True}
    assert states[0]["sink"] is False


def test_graphs_covers_every_monitor_including_the_failure_modes(monkeypatch):
    """A named failure mode is an LTL monitor too, and `verdict.failure_modes[].state`
    is worthless without a graph to read it against."""
    multi = object.__new__(automata.MultiMonitor)
    multi.monitors = [
        a_real_monitor(monkeypatch, name="full_navigation_sequence"),
        a_real_monitor(monkeypatch, name="collision_imminent",
                       formula="G(!collision_risk)"),
    ]
    graphs = multi.graphs()
    assert [g["name"] for g in graphs] == \
        ["full_navigation_sequence", "collision_imminent"]
    assert api.validate_automata(graphs) == []


def test_the_node_publishes_the_automaton_graph_on_the_latched_manifest():
    node = a_node(graphs=[a_graph("nav"), a_graph("collision_imminent")])
    payload = manifests(node)[-1]
    assert api.validate_skill_manifest(payload) == []
    assert [g["name"] for g in payload["automata"]] == ["nav", "collision_imminent"]


def test_the_graph_is_rebuilt_when_a_spec_is_loaded(monkeypatch):
    """It is latched and derived once per spec load, which is the whole reason it can
    afford to be the full automaton. So the load is the one moment it has to be rebuilt
    -- otherwise the pane keeps drawing the previous skill's automaton for the rest of
    the run, with the new skill's state integers pointing into it."""
    node = a_node(graphs=[a_graph("nav")])
    monkeypatch.setattr(
        monitor_node, "MultiMonitor",
        lambda *a, **k: FakeMulti([FakeMonitor("wandered", "G(!wandered)")],
                                  graphs=[a_graph("wandered")]),
    )
    node.load_spec_callback(ros_stub.Message(json.dumps(a_spec())))
    assert [g["name"] for g in manifests(node)[-1]["automata"]] == ["wandered"]


def test_a_node_that_cannot_describe_its_automata_still_publishes_a_valid_manifest():
    """The degrade path, and the default here: a faked monitor has no graph. Absent,
    not an empty list -- an empty list would tell the console this skill has no
    monitors, which is a different and untrue thing."""
    node = a_node()
    assert node._automata() is None
    payload = manifests(node)[-1]
    assert "automata" not in payload
    assert api.validate_skill_manifest(payload) == []


def test_a_monitor_that_raises_while_describing_itself_does_not_take_the_manifest_down():
    """A spot call that throws must cost the pane, not the manifest -- every other
    thing a client reads about this monitor is on that payload."""
    class Exploding(FakeMulti):
        def graphs(self):
            raise RuntimeError("spot said no")

    node = a_node(multi=Exploding([FakeMonitor("nav", "F(path_active)")]))
    assert node._automata() is None
    payload = manifests(node)[-1]
    assert "automata" not in payload
    assert api.validate_skill_manifest(payload) == []


def test_every_verdict_row_reports_the_state_of_its_own_automaton():
    node = a_node(monitors=[
        FakeMonitor("nav", "F(path_active)", current_state=2),
        FakeMonitor(
            "collision_imminent", "G(!collision_risk)", current_state=5,
            failure_mode=FailureModeInfo(name="collision_imminent",
                                         fault_category="SAFETY", description=""),
        ),
    ])
    tick(node, 1)
    observe(node, 1)

    v = verdicts(node)[-1]
    assert api.validate_verdict(v) == []
    assert v["formulas"][0]["state"] == 2
    assert v["failure_modes"][0]["state"] == 5


def test_a_monitor_with_no_state_to_report_publishes_null_and_a_valid_verdict():
    """The verdict half of the degrade path. `state` is nullable precisely so a
    producer that cannot report one is not forced to invent a state number the console
    would then highlight as fact."""
    node = a_node(monitors=[
        FakeMonitor("nav", "F(path_active)", current_state=None),
        FakeMonitor(
            "collision_imminent", "G(!collision_risk)", current_state=None,
            failure_mode=FailureModeInfo(name="collision_imminent",
                                         fault_category="SAFETY", description=""),
        ),
    ])
    tick(node, 1)
    observe(node, 1)

    v = verdicts(node)[-1]
    assert api.validate_verdict(v) == []
    assert v["formulas"][0]["state"] is None
    assert v["failure_modes"][0]["state"] is None


def test_the_phase_machines_own_fault_reports_no_state():
    """It is a violation counter, not a Büchi automaton. There is no node to point at
    and `null` says so, rather than a 0 that indexes some other monitor's graph."""
    spec = a_spec(execution_phases=[{
        "phase": "Approach",
        "enter_condition": "True",
        "progress_condition": "path_active",
        "progress_violation_limit": 1,
        "exit_condition": "False",
    }])
    node = a_node(spec)
    for seq in (1, 2):
        tick(node, seq)
        observe(node, seq, aps={"path_active": False})

    rows = {e["name"]: e for e in verdicts(node)[-1]["failure_modes"]}
    phase_row = next(e for name, e in rows.items() if name != "collision_imminent")
    assert phase_row["state"] is None


# =============================================================================
# `verdict.phase_guards` -- the truth the phase machine acted on
#
# The one thing the console cannot get from the latched manifest is whether each of a
# phase's conditions holds right now, and it must not evaluate them itself: a second
# implementation of the expression evaluator is where this project's
# `min_range < 0.25` decimal-point bug lived three times. So `_update_phase_state`
# records what it computed, and the verdict publishes that recording rather than a
# second opinion. These tests pin that it really is the same number -- and that a guard
# the machine short-circuited past reaches the wire as `null`, not as `false`.
# =============================================================================

def _guards(verdict) -> dict:
    """The published block as {guard name: value}."""
    return {g["name"]: g["value"] for g in verdict["phase_guards"]["guards"]}


def _exprs(verdict) -> dict:
    return {g["name"]: g["expr"] for g in verdict["phase_guards"]["guards"]}


def _two_phase_spec(**first) -> dict:
    phase0 = {
        "phase": "Approach",
        "enter_condition": "mission_started",
        "invariant": "upright",
        "invariant_fault_category": "SAFETY",
        "progress_condition": "not nav_stuck",
        "exit_condition": "path_active",
    }
    phase0.update(first)
    return a_spec(execution_phases=[
        phase0,
        {"phase": "Track", "enter_condition": "path_active",
         "invariant": "upright", "invariant_fault_category": "SAFETY",
         "progress_condition": "not nav_stuck", "exit_condition": "arrived"},
    ])


def test_the_verdict_publishes_the_guards_the_phase_machine_evaluated():
    """The entering tick: the machine consults every guard the phase declares, and every
    one of them reaches the wire with the expression the spec authored beside it."""
    node = a_node(_two_phase_spec(), monitors=[FakeMonitor("nav", "F(path_active)")])
    tick(node, 1)
    observe(node, 1, aps={"mission_started": True, "upright": True,
                          "nav_stuck": False, "path_active": False})

    v = verdicts(node)[-1]
    assert api.validate_verdict(v) == []
    assert v["phase"] == "Approach" and v["phase_index"] == 0
    assert v["phase_guards"]["phase"] == "Approach"
    assert _guards(v) == {
        "enter_condition": True,        # it is why the phase was entered
        "invariant": True,
        "progress_condition": True,
        "exit_condition": False,        # …and why it was not left again
    }
    assert _exprs(v)["progress_condition"] == "not nav_stuck"


def test_the_published_exit_condition_is_the_one_that_decided_the_transition():
    """The point of the whole field: the number on the wire is the number the monitor
    acted on. `exit_condition` reads true on exactly the tick the phase index advances,
    and the pane's `true` is therefore the same evaluation that moved the machine."""
    node = a_node(_two_phase_spec(), monitors=[FakeMonitor("nav", "F(path_active)")])
    aps = {"mission_started": True, "upright": True, "nav_stuck": False,
           "path_active": False, "arrived": False}
    tick(node, 1)
    observe(node, 1, aps=aps)
    tick(node, 2)
    observe(node, 2, aps=dict(aps, path_active=True))

    before, after = verdicts(node)[-2], verdicts(node)[-1]
    assert before["phase_index"] == 0 and _guards(before)["exit_condition"] is False
    # The machine moved, and it moved because that same expression came back true.
    assert after["phase_index"] == 1
    assert node.phase_idx == 1
    assert _guards(after)["enter_condition"] is True, (
        "phase 1's enter condition is what admitted it, and it is published as such"
    )
    # The outgoing phase's exit guard is not smuggled into the incoming phase's block.
    assert after["phase_guards"]["phase"] == "Track"
    assert _exprs(after)["exit_condition"] == "arrived"


def test_a_guard_the_machine_short_circuited_past_reports_null_not_false():
    """`min_steps` is the cleanest short circuit there is: below it the machine never
    asks whether it may leave. Publishing `false` would tell an operator the exit
    condition was checked and did not hold -- a claim about the world, from a tick on
    which the monitor made no such claim."""
    node = a_node(
        _two_phase_spec(timing_bounds={"min_steps": 5}),
        monitors=[FakeMonitor("nav", "F(path_active)")],
    )
    tick(node, 1)
    observe(node, 1, aps={"mission_started": True, "upright": True,
                          "nav_stuck": False, "path_active": True})

    v = verdicts(node)[-1]
    assert api.validate_verdict(v) == []
    guards = _guards(v)
    # `path_active` is true and would have fired the exit -- and the machine still sits
    # in phase 0, because it never evaluated it.
    assert v["phase_index"] == 0
    assert guards["exit_condition"] is None
    assert guards["exit_condition"] is not False
    # …while the guards it did consult carry real answers on the same tick.
    assert guards["invariant"] is True and guards["progress_condition"] is True


def test_a_steady_tick_reports_null_for_the_guards_entry_consulted():
    """`enter_condition` and `precondition` are asked once, on entry. On every later
    tick of the same phase they are simply not consulted, and the honest report of that
    is `null` -- not the stale `true` that admitted the phase ten steps ago."""
    node = a_node(
        _two_phase_spec(precondition="upright"),
        monitors=[FakeMonitor("nav", "F(path_active)")],
    )
    aps = {"mission_started": True, "upright": True, "nav_stuck": False,
           "path_active": False}
    for seq in (1, 2):
        tick(node, seq)
        observe(node, seq, aps=aps)

    entering, steady = verdicts(node)[-2], verdicts(node)[-1]
    assert _guards(entering)["enter_condition"] is True
    assert _guards(entering)["precondition"] is True
    assert steady["phase_index"] == 0, "still the same phase, still the same entry"
    assert _guards(steady)["enter_condition"] is None
    assert _guards(steady)["precondition"] is None
    assert _guards(steady)["invariant"] is True, "the per-step guards still report"


def test_an_ap_the_evaluator_could_not_supply_leaves_its_guard_null():
    """An AP in `unknown_aps` is simply absent from `ap_values`, so the expression
    raises and the machine falls back on a default. The default is what the machine
    *did*; it is not what the spec's condition said, and publishing it as that
    condition's value invents an evaluation that never happened."""
    node = a_node(_two_phase_spec(), monitors=[FakeMonitor("nav", "F(path_active)")])
    tick(node, 1)
    # `nav_stuck` never arrived: `not nav_stuck` cannot be evaluated at all.
    observe(node, 1, aps={"mission_started": True, "upright": True,
                          "path_active": False})

    v = verdicts(node)[-1]
    assert api.validate_verdict(v) == []
    guards = _guards(v)
    assert guards["progress_condition"] is None
    # The machine's own fallback for an unevaluable progress condition is "no
    # violation" -- it did not count one -- and that is *not* published as `true`.
    assert node.phase_violation_count == 0
    assert guards["progress_condition"] is not True
    assert guards["invariant"] is True, "an expression that did evaluate still reports"


def test_a_breached_invariant_publishes_false_and_stops_asking():
    """The other side of the same coin. `false` here is a real answer the operator must
    act on, and everything the machine skipped on its way out is `null` -- so the pane
    can show which guard ended the phase and which were never reached."""
    node = a_node(_two_phase_spec(), monitors=[FakeMonitor("nav", "F(path_active)")])
    aps = {"mission_started": True, "upright": True, "nav_stuck": False,
           "path_active": False}
    tick(node, 1)
    observe(node, 1, aps=aps)
    tick(node, 2)
    observe(node, 2, aps=dict(aps, upright=False))

    v = verdicts(node)[-1]
    assert api.validate_verdict(v) == []
    guards = _guards(v)
    assert guards["invariant"] is False
    assert guards["progress_condition"] is None, "never reached: the phase already failed"
    assert guards["exit_condition"] is None
    assert any(fm["name"].endswith(":invariant") for fm in v["failure_modes"])


def test_an_idle_run_publishes_a_null_block():
    """No phase is active, so there is nothing to report guards for. `null` for the
    whole block, not an empty guard list -- which would claim a phase is running and
    declares no conditions at all."""
    node = a_node(_two_phase_spec(), monitors=[FakeMonitor("nav", "F(path_active)")])
    tick(node, 1)
    observe(node, 1, aps={"mission_started": False, "upright": True,
                          "nav_stuck": False, "path_active": False})

    v = verdicts(node)[-1]
    assert v["phase"] == "Idle" and v["phase_index"] is None
    assert v["phase_guards"] is None
    assert api.validate_verdict(v) == []


def test_a_spec_with_no_phases_publishes_a_null_block_and_a_valid_verdict():
    """The degrade path. `a_spec()` declares no `execution_phases` at all, and nothing
    about the phase pane may make such a monitor publish a verdict its own validator
    rejects."""
    node = a_node()
    assert node.has_phases is False
    tick(node, 1)
    observe(node, 1, aps={"path_active": True})

    v = verdicts(node)[-1]
    assert v["phase_guards"] is None
    assert api.validate_verdict(v) == []


def test_a_reload_forgets_the_guards_of_the_spec_it_replaced():
    """A spec swap resets the phase machine, and a block left over from the old spec
    would name a phase the new one does not have."""
    node = a_node(_two_phase_spec(), monitors=[FakeMonitor("nav", "F(path_active)")])
    tick(node, 1)
    observe(node, 1, aps={"mission_started": True, "upright": True,
                          "nav_stuck": False, "path_active": False})
    assert verdicts(node)[-1]["phase_guards"] is not None

    node._reset_phase_state()
    assert node._phase_guards is None
    assert node.verdict()["phase_guards"] is None
    assert api.validate_verdict(node.verdict()) == []


def test_the_published_guards_are_the_ones_the_machine_recorded():
    """No second evaluation anywhere on the path. The node's own record of what
    `_update_phase_state` computed is what the verdict carries, key for key."""
    node = a_node(_two_phase_spec(), monitors=[FakeMonitor("nav", "F(path_active)")])
    tick(node, 1)
    observe(node, 1, aps={"mission_started": True, "upright": True,
                          "nav_stuck": True, "path_active": False})

    recorded = {guard: value for (idx, guard), value
                in node._phase_guard_values.items() if idx == node.phase_idx}
    published = {name: value for name, value in _guards(verdicts(node)[-1]).items()
                 if value is not None}
    assert published == recorded
    assert recorded["progress_condition"] is False
    assert node.phase_violation_count == 1, (
        "the machine counted a violation off the same evaluation it published"
    )
