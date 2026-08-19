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
from skill_monitor.core import api, manifest                    # noqa: E402
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


class FakeMonitor:
    """One LTL monitor. `violated_when` decides its status from the observation, which
    is how a test says "this is the tick the collision formula breaks" without spot."""

    def __init__(self, name, formula, failure_mode=None, violated_when=None) -> None:
        self.name = name
        self.formula = formula
        self.failure_mode = failure_mode
        self.status = MonitorStatus.INCONCLUSIVE
        self.current_state = 0
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


class FakeMulti:
    def __init__(self, monitors) -> None:
        self.monitors = list(monitors)
        #: One entry per `step()`. The whole point of the fake.
        self.steps: list[dict] = []

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


def a_node(spec_dict=None, *, monitors=None, adapter=None):
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
    node = monitor_node.LtlMonitorNode(spec, FakeMulti(monitors), Args())
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
    assert v["formulas"] == [{"name": "nav", "status": "INCONCLUSIVE"}]


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
