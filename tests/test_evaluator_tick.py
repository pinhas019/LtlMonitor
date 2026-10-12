"""The evaluator under a clock: each pulse folds the sensor window and, when a skill is
armed, publishes one `api.OBSERVATION` stamped with that pulse's `seq`.

Before this, `SensorState.tick()` had no caller, so every sensor value stayed at its
schema default however many messages arrived, and no producer published the envelope
the recorder already records -- so a recording carried ticks and verdicts but no
sensors. Driven through `tests/ros_stub.py`; the G1 spec is rule-based, so no LLM call
is ever queued.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ros_stub

pytestmark = pytest.mark.skipif(
    ros_stub.real_ros_present(),
    reason="a real rclpy is installed; these tests drive a stub and must not shadow it",
)

ros_stub.install()

from skill_monitor.backend.adapters.declarative import DeclarativeAdapter  # noqa: E402
from skill_monitor.backend.evaluator_node import GenericClientNode         # noqa: E402
from skill_monitor.core import api                                         # noqa: E402

SPEC = json.loads(
    (Path(__file__).resolve().parents[1] / "skill_monitor/specs/formulas_g1.json")
    .read_text(encoding="utf-8"))
ARMED_APS = ["mission_started", "path_active", "moving_towards_target"]
FOLLOWING = {"mode": "AUTOMATIC", "state": "following", "finished": False,
             "num_waypoints": 3, "current_target_idx": 1}


class FakeClock:
    def __init__(self, now: float = 100.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def node(clock):
    made = GenericClientNode(DeclarativeAdapter(descriptor="real_g1", clock=clock),
                             api_url="http://127.0.0.1:0/unused", model="none")
    yield made
    made.destroy_node()


def _source(node, source_id):
    return next(s for s in node.adapter.spec.sources if s.id == source_id)


def deliver(node, source_id, payload):
    """A message on one of the adapter's own topics, as the executor would hand it."""
    for callback in node.subscriptions[_source(node, source_id).topic]:
        callback(ros_stub.Message(data=json.dumps(payload)))


def pulse(node, seq, t=None, tick_hz=1.0):
    payload = api.build_tick(seq=seq, t=float(seq if t is None else t),
                             tick_hz=tick_hz, t0=1_700_000_000.0, mode="replay")
    for callback in node.subscriptions[api.TICK]:
        callback(ros_stub.Message(data=json.dumps(payload)))
    node.query_queue.join()              # the worker publishes; wait for it


def arm(node, aps=ARMED_APS):
    node.desc_callback(ros_stub.Message(data=json.dumps({
        "skill_name": SPEC["skill_name"], "phase": "ExecutionAndTracking",
        "ap_descriptions": SPEC["atomic_propositions"],
    })))
    node.aps_callback(ros_stub.Message(data=json.dumps(aps)))


def sent(node, topic):
    pub = node.publishers.get(topic)
    return [json.loads(text) for text in pub.sent] if pub else []


def legacy(node):
    return sent(node, node.eval_pub.topic)


# =============================================================================
# The fold
# =============================================================================

def test_without_a_pulse_the_values_stay_at_their_defaults():
    """The bug, stated as a test of the old behaviour's cause: messages land in the
    open window and nothing reads them until the window is closed."""
    adapter = DeclarativeAdapter(descriptor="real_g1", clock=FakeClock())
    default = adapter.get_sensor_eval()["nav_state"]
    adapter._on_message(_source_by_id(adapter, "status"),
                        ros_stub.Message(data=json.dumps(FOLLOWING)))
    assert adapter.get_sensor_eval()["nav_state"] == default


def _source_by_id(adapter, source_id):
    return next(s for s in adapter.spec.sources if s.id == source_id)


def test_a_pulse_folds_the_window_into_the_values(node):
    deliver(node, "status", FOLLOWING)
    pulse(node, 1)
    values = node.adapter.get_sensor_eval()
    assert values["nav_state"] == "following"
    assert values["nav_mode"] == "AUTOMATIC"


def test_an_idle_pulse_still_folds_but_publishes_nothing(node):
    """P3: the window closes on every pulse, armed or not, or an idle stretch piles
    every message since boot into the first armed tick."""
    assert node.idle
    deliver(node, "status", FOLLOWING)
    pulse(node, 1)
    assert node.adapter.state.pending_samples() == 0
    assert node.adapter.get_sensor_eval()["nav_state"] == "following"
    assert sent(node, api.OBSERVATION) == [] and legacy(node) == []


# =============================================================================
# The envelope
# =============================================================================

def test_an_armed_pulse_publishes_an_observation_stamped_with_the_pulse_seq(node):
    arm(node)
    deliver(node, "status", FOLLOWING)
    pulse(node, 7)

    (obs,) = sent(node, api.OBSERVATION)
    assert api.validate_observation(obs) == []
    assert obs["seq"] == 7 and obs["t"] == 7.0
    assert obs["step"] is None                 # the monitor owns the episode step
    assert obs["sensors"]["nav_state"] == "following"
    assert set(obs["ap_values"]) == set(ARMED_APS)
    assert obs["ap_values"]["path_active"] is True
    assert obs["unknown_aps"] == []


def test_the_legacy_payload_still_goes_out_beside_it(node):
    """P4/P5/P7 still read the legacy wire; the monitor steps once per tick whichever
    arrives first, so both are safe to publish."""
    arm(node)
    deliver(node, "status", FOLLOWING)
    pulse(node, 1)
    (flat,) = legacy(node)
    assert flat["path_active"] is True
    assert flat["__sensors__"]["nav_state"] == "following"


def test_the_observation_and_the_legacy_payload_agree(node):
    arm(node)
    deliver(node, "status", FOLLOWING)
    pulse(node, 1)
    (obs,), (flat,) = sent(node, api.OBSERVATION), legacy(node)
    assert obs["sensors"] == flat["__sensors__"]
    assert all(obs["ap_values"][ap] == flat[ap] for ap in ARMED_APS)


def test_consecutive_pulses_carry_their_own_seq_in_order(node):
    arm(node)
    for seq in (3, 4, 5):
        deliver(node, "status", FOLLOWING)
        pulse(node, seq)
    assert [o["seq"] for o in sent(node, api.OBSERVATION)] == [3, 4, 5]


# =============================================================================
# Data health
# =============================================================================

def test_data_health_describes_every_source_for_the_tick_just_closed(node, clock):
    arm(node)
    pulse(node, 1)                              # opens a 1 s window from here
    clock.now += 1.0
    deliver(node, "status", FOLLOWING)
    deliver(node, "status", FOLLOWING)
    pulse(node, 2)

    obs = sent(node, api.OBSERVATION)[-1]
    health = obs["data_health"]
    assert set(health) == {s.id for s in node.adapter.spec.sources}
    status = health["status"]
    assert status["samples_this_tick"] == 2
    assert status["rate_hz"] == pytest.approx(2.0)
    assert status["expected_hz"] == pytest.approx(5.0)
    assert status["refreshed"] is True
    assert status["age_s"] == pytest.approx(0.0)


def test_a_source_that_never_arrived_is_unrefreshed_with_a_finite_age(node, clock):
    arm(node)
    clock.now += 4.0
    pulse(node, 1)
    odom = sent(node, api.OBSERVATION)[-1]["data_health"]["odom"]
    assert odom["refreshed"] is False
    assert odom["samples_this_tick"] == 0
    assert odom["age_s"] == pytest.approx(4.0)  # since the adapter started


def test_a_stale_source_reaches_the_monitor_through_data_health(node):
    """`normalize_observation` reads staleness off `refreshed: false`, so an unrefreshed
    source is exactly what the monitor will treat as stale for this tick."""
    from skill_monitor.core.manifest import normalize_observation
    arm(node)
    deliver(node, "status", FOLLOWING)
    pulse(node, 1)
    observation = normalize_observation(sent(node, api.OBSERVATION)[-1])
    assert "status" not in observation.stale_sources
    assert "odom" in observation.stale_sources


# =============================================================================
# Failure and fallback
# =============================================================================

def test_a_fold_that_raises_is_logged_and_publishes_nothing_for_that_tick(node):
    arm(node)

    def broken():
        raise RuntimeError("tick step exploded")

    node.adapter.tick = broken
    pulse(node, 1)
    assert sent(node, api.OBSERVATION) == [] and legacy(node) == []
    assert any("tick 1" in line for line in node.get_logger().at("error"))

    del node.adapter.tick                       # back to the class method
    deliver(node, "status", FOLLOWING)
    pulse(node, 2)
    assert [o["seq"] for o in sent(node, api.OBSERVATION)] == [2]


@pytest.mark.parametrize("body", [
    "not json",
    json.dumps({"seq": 1}),
    json.dumps(api.build_tick(seq=1, t=1.0, tick_hz=1.0, t0=1.0) | {"seq": "one"}),
])
def test_a_malformed_pulse_is_ignored_and_folds_nothing(node, body):
    ticks_before = node.adapter.state.ticks
    for callback in node.subscriptions[api.TICK]:
        callback(ros_stub.Message(data=body))
    assert node.adapter.state.ticks == ticks_before
    assert node.get_logger().at("error")


def test_while_pulses_arrive_the_fallback_timer_stays_quiet(node):
    arm(node)
    pulse(node, 1)
    before = len(legacy(node))
    node._on_timer()
    node.query_queue.join()
    assert len(legacy(node)) == before


def test_without_a_clock_the_timer_still_evaluates_on_the_legacy_wire_only(node):
    """No clock, no `seq` to stamp an envelope with -- so today's behaviour, now with
    real values instead of schema defaults."""
    arm(node)
    deliver(node, "status", FOLLOWING)
    node._on_timer()
    node.query_queue.join()
    (flat,) = legacy(node)
    assert flat["__sensors__"]["nav_state"] == "following"
    assert sent(node, api.OBSERVATION) == []


def test_a_hand_written_adapter_runs_under_a_clock_unchanged():
    """`SensorAdapter.tick()` and `data_health()` default to no-ops, so an adapter that
    keeps no window needs no change to receive pulses."""
    from skill_monitor.backend.adapters.base import SensorAdapter

    class Minimal(SensorAdapter):
        SCHEMA = {"linear_vel": "m/s"}

        def register_subscriptions(self, node):
            pass

        def get_sensor_eval(self):
            return {"linear_vel": 0.0}

    adapter = Minimal()
    assert adapter.tick() is None
    assert adapter.data_health() == {}
