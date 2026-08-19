"""The monitor node's wiring, driven without a ROS graph.

`core/manifest.py` holds the decisions and `tests/test_manifest.py` pins them. This
file pins the lines that *feed* those decisions: which wire is allowed to step the
automaton, and what the ledger is handed when the clock restarts. Neither is visible
from a pure function's arguments.

`tests/ros_stub.py` supplies the graph. The automaton is faked outright -- `MultiMonitor`
needs `spot`, and what these tests need from it is a count of how many times it was
stepped, which a real one would only obscure.
"""

from __future__ import annotations

import json

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


def tick(node, seq, *, t0=None, tick_hz=1.0):
    payload = api.build_tick(seq=seq, t=float(seq), tick_hz=tick_hz, mode="wall")
    if t0 is not None:
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


def test_a_clock_that_never_sends_t0_behaves_exactly_as_before():
    """P1 may land after this. Absent `t0` means one epoch forever, which is the
    behaviour that was already there -- backwards is stale and stays refused."""
    node = a_node()
    for seq in (10, 11):
        tick(node, seq)
        observe(node, seq)
    observe(node, 9)
    assert len(node.multi.steps) == 2
    assert node.ledger.epoch is None


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
