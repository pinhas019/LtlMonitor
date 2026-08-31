"""What the evaluator announces about the robot, driven without a ROS graph.

`backend/evaluator_node.py` is P3's and still on the legacy wire, so most of it is not
pinned here. One thing is: **the adapter manifest goes out on both wires.**

That payload had subscribers on the new wire and no publisher. The monitor listens on
`api.ADAPTER` and `/ltl/adapter` both, the gateway serves `api.ADAPTER` as a latched
GET, and the console's raw-echo source picker is keyed on it -- so against a real robot
the picker had nothing in it and an operator could not name a single source to echo.
`docs/api.md` names P3 the producer, and P3 published only the legacy topic. Nothing
failed loudly; the console simply said it did not know what the robot had.

`tests/ros_stub.py` supplies the graph. The LLM is never reached: a rule-based
descriptor leaves `llm_aps` empty, and nothing here arms a query.
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

from rclpy.qos import DurabilityPolicy                                     # noqa: E402
from std_msgs.msg import String                                            # noqa: E402
from skill_monitor.backend.adapters.declarative import DeclarativeAdapter  # noqa: E402
from skill_monitor.backend import evaluator_node                            # noqa: E402
from skill_monitor.backend.evaluator_node import GenericClientNode         # noqa: E402
from skill_monitor.core import api                                         # noqa: E402

LEGACY_ADAPTER = evaluator_node._LEGACY_ADAPTER
LEGACY_EVALUATIONS = evaluator_node._LEGACY_EVALUATIONS


def a_node(descriptor="real_g1"):
    """The evaluator over a shipped descriptor. `api_url` is never called: the G1 spec
    is rule-based, so no atomic proposition is ever queued for a model."""
    return GenericClientNode(DeclarativeAdapter(descriptor=descriptor),
                             api_url="http://127.0.0.1:0/unused", model="none")


def published(node, topic):
    pub = node.publishers.get(topic)
    return list(pub.sent) if pub else []


# =============================================================================
# The adapter manifest, on both wires
# =============================================================================

def test_the_adapter_manifest_goes_out_on_the_contract_topic():
    """The regression. Without this the gateway has no adapter to serve, so the
    console's echo picker is empty and a real robot's sources cannot be named."""
    node = a_node()
    sent = published(node, api.ADAPTER)
    assert len(sent) == 1, f"{api.ADAPTER} was published {len(sent)} times, want exactly 1"
    payload = json.loads(sent[0])
    assert payload["adapter"] == "real_g1"
    assert [s["id"] for s in payload["sources"]] == \
        [s.id for s in node.adapter.spec.sources]


def test_the_legacy_wire_still_carries_it_too():
    """P5 and P7 still read `/ltl/adapter`. Both wires stay live during the migration,
    which is the same rule every other topic follows -- the stack has to run at every
    commit, not only after the last package lands."""
    node = a_node()
    assert len(published(node, LEGACY_ADAPTER)) == 1


def test_both_wires_carry_the_identical_document():
    """Byte-identical, not merely equivalent. Two consumers reading two topics must not
    be able to disagree about what this robot can observe -- and a re-serialisation is
    exactly where a key order or a float repr quietly diverges."""
    node = a_node()
    assert published(node, api.ADAPTER)[0] == published(node, LEGACY_ADAPTER)[0]


def test_the_announcement_is_latched_on_both_wires():
    """It is announced once, at startup. A console that connects a minute later has to
    still receive it, or the picker is empty for a robot that is working perfectly."""
    node = a_node()
    for topic in (api.ADAPTER, LEGACY_ADAPTER):
        qos = node.publishers[topic].qos
        assert qos is not None, f"{topic} was created with no QoS profile"
        assert getattr(qos, "durability", None) == DurabilityPolicy.TRANSIENT_LOCAL, \
            f"{topic} is not latched; a late subscriber would hear nothing"


def test_what_it_announces_is_what_the_adapter_says_it_can_observe():
    """The manifest is the adapter's own, passed through the contract's builder and not
    reassembled here. A schema this file rebuilt could drift from the one the fold
    actually uses, and the drift would be invisible: nothing validates on receipt."""
    node = a_node()
    payload = json.loads(published(node, api.ADAPTER)[0])
    for key, value in node.adapter.manifest().items():
        assert payload[key] == value, f"the wire altered {key}"


def test_the_announcement_satisfies_the_contract_it_is_published_under():
    """It did not. `AdapterSpec.manifest` returns `api.build_adapter`'s keyword
    arguments precisely so the shape cannot drift, and P3 published the bare dict --
    so what went out carried no `schema_version` and failed `api.validate_adapter`.
    Nothing complained, because no consumer validates an adapter on receipt."""
    node = a_node()
    payload = json.loads(published(node, api.ADAPTER)[0])
    assert api.validate_adapter(payload) == []
    assert payload["schema_version"] == api.SCHEMA_VERSION


@pytest.mark.parametrize("descriptor", ["real_g1", "mujoco", "isaac_lab"])
def test_every_shipped_descriptor_announces_itself(descriptor):
    node = a_node(descriptor)
    payload = json.loads(published(node, api.ADAPTER)[0])
    assert payload["adapter"] == descriptor
    assert payload["sources"], f"{descriptor} announced no sources at all"
    assert api.validate_adapter(payload) == []


# =============================================================================
# The tick, and the observation it closes
# =============================================================================
#
# Nothing here goes near the LLM queue. The worker is a live daemon thread, so a test
# that queued a snapshot would be racing it for the item; every test below drives the
# pulse path or the publish path directly instead. `ros_stub` timers never fire, which
# is also why `_free_run` has to be callable by name rather than only through
# `create_timer`.

def a_pulse(seq=1, t=1.0, tick_hz=1.0, t0=100.0):
    return String(data=json.dumps(
        api.build_tick(seq=seq, t=t, tick_hz=tick_hz, mode="wall", t0=t0)))


def an_odom(px=0.0, pz=0.7):
    """Enough of nav_msgs/Odometry for the real_g1 descriptor's field paths. Plain
    dicts: `SensorState.update` walks the path, it does not care about the type."""
    return {"pose": {"pose": {"position": {"x": px, "y": 0.0, "z": pz},
                              "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}},
            "twist": {"twist": {"linear": {"x": 0.0, "y": 0.0, "z": 0.0},
                                "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}}}


def test_the_pulse_closes_the_window_even_while_idle():
    """The bug P3's brief names, and the reason `adapter.tick()` sits above the idle
    return. If only the publishing path closed the window, an idle evaluator would
    never close one: the window would grow across the whole idle stretch and the first
    armed tick would fold minutes of samples into a single observation. An obstacle
    the robot walked past two minutes ago would fire `collision_risk` on resume."""
    node = a_node()
    assert node.idle, "sanity: it starts idle, which is the interesting case"

    for _ in range(30):
        node.adapter.state.update("odom", an_odom(px=2.0))
    assert node.adapter.state.updates_since_tick == 30

    node.tick_callback(a_pulse(seq=1))

    assert node.adapter.state.updates_since_tick == 0, (
        "the window survived a pulse while idle; it will be folded into whichever "
        "tick happens to arm")
    assert node.adapter.state.ticks == 0, "the tick did not close"
    assert published(node, api.OBSERVATION) == [], "idle must not publish"


def test_the_observation_advances_with_the_pulse():
    """The whole point of the migration: values move, and the tick index they are
    stamped with is the clock's, not this process's."""
    node = a_node()
    node.adapter.state.update("odom", an_odom(px=1.0))
    node.tick_callback(a_pulse(seq=7, t=7.5))
    first = node.adapter.get_sensor_eval()["pos_x"]

    node.adapter.state.update("odom", an_odom(px=9.0))
    node.tick_callback(a_pulse(seq=8, t=8.5))
    second = node.adapter.get_sensor_eval()["pos_x"]

    assert (first, second) == (1.0, 9.0), "the held values are not following the data"
    assert (node._tick_seq, node._tick_t) == (8, 8.5), "the pulse's seq was not adopted"


def test_the_observation_is_published_and_satisfies_its_contract():
    """Nothing validates an observation on receipt, so the builder's own validator is
    the only thing standing between a malformed envelope and the automaton."""
    node = a_node()
    node.adapter.state.update("odom", an_odom(px=3.0))
    node.adapter.tick(2.0)

    node._publish_observation(
        {"required_aps": ["upright", "collision_risk"], "seq": 4, "t": 2.0,
         "confidence": 1.0, "clock": "external",
         "data_health": node.adapter.data_health()},
        node.adapter.get_sensor_eval(),
        {"upright": True, "collision_risk": False},
    )

    sent = published(node, api.OBSERVATION)
    assert len(sent) == 1
    payload = json.loads(sent[0])
    assert api.validate_observation(payload) == []
    assert payload["seq"] == 4
    assert payload["ap_values"] == {"upright": True, "collision_risk": False}
    assert payload["sensors"]["pos_x"] == 3.0


def test_every_declared_source_reports_its_health():
    """All six, not the three that happen to be `tracked`. An untracked source still
    feeds sensor_eval keys -- `goal` is where `dist_to_goal` comes from -- and a
    console that cannot show its age cannot tell a waypoint that stopped arriving
    from one that never moved."""
    node = a_node()
    node.adapter.tick(1.0)
    node._publish_observation(
        {"required_aps": [], "seq": 1, "t": 1.0, "confidence": 1.0,
         "clock": "external", "data_health": node.adapter.data_health()},
        node.adapter.get_sensor_eval(), {})

    health = json.loads(published(node, api.OBSERVATION)[0])["data_health"]
    assert set(health) == {s.id for s in node.adapter.spec.sources}
    for source_id, entry in health.items():
        assert set(entry) == {"rate_hz", "expected_hz", "age_s", "samples_this_tick",
                              "refreshed", "dropped", "tracked"}, source_id


def test_an_ap_without_a_boolean_names_itself_instead_of_defaulting_to_false():
    """The LLM can omit an AP or answer with something that is not a bool. Coercing
    that to False would make a failed evaluation indistinguishable from a negative
    one, on the wire the automaton steps on."""
    node = a_node()
    node.adapter.tick(1.0)
    node._publish_observation(
        {"required_aps": ["upright", "at_goal", "nav_stuck"], "seq": 1, "t": 1.0,
         "confidence": 1.0, "clock": "external", "data_health": {}},
        node.adapter.get_sensor_eval(),
        {"upright": True, "at_goal": "yes"},          # 'yes' is not a bool; nav_stuck absent
    )

    payload = json.loads(published(node, api.OBSERVATION)[0])
    assert payload["ap_values"] == {"upright": True}
    assert sorted(payload["unknown_aps"]) == ["at_goal", "nav_stuck"]
    assert api.validate_observation(payload) == [], (
        "an AP may not appear in ap_values and unknown_aps both")


def test_an_unevaluable_ap_is_unknown_on_the_envelope_and_false_on_the_legacy_wire():
    """Through `_process_evaluation`, because that is where the defaulting lives.

    The legacy `/ltl/evaluations` dict is flat booleans with no way to spell UNKNOWN,
    so it has always sent `final_evals.setdefault(ap, False)` for an AP that no rule
    matched and no model answered. On a safety proposition that default is not
    neutral: False for `collision_risk` reads as "the way is clear".

    The envelope has `unknown_aps` precisely so it does not have to lie, so the two
    wires disagree here ON PURPOSE and this pins that they do. Changing the legacy
    semantics is P10's; publishing an honest envelope is not.
    """
    node = a_node()
    node.idle = False
    node.required_aps = ["upright", "collision_risk"]
    # A description no rule parser can read, and no model is reachable to answer it,
    # so `collision_risk` comes back undecided.
    node.state_desc = {"skill_name": "nav", "ap_descriptions": {
        "upright": "True when upright_flag > 0.5.",
        "collision_risk": "whatever the operator thinks looks dangerous",
    }}
    node.adapter.state.update("odom", an_odom(pz=0.75))
    node.tick_callback(a_pulse(seq=2, t=2.0))
    node._process_evaluation(node.query_queue.get_nowait())

    envelope = json.loads(published(node, api.OBSERVATION)[0])
    assert envelope["ap_values"] == {"upright": True}
    assert envelope["unknown_aps"] == ["collision_risk"], (
        "an AP nothing could evaluate was given a truth value")

    legacy = json.loads(published(node, LEGACY_EVALUATIONS)[0])
    assert legacy["collision_risk"] is False, (
        "the legacy wire's defaulting changed; that is P10's call, not this one's")


def test_the_free_running_fallback_goes_quiet_once_a_clock_appears():
    """Without a clock on the graph -- a dev host, `--mock` -- the evaluator still has
    to emit, or it looks broken. The moment a real pulse arrives the fallback stops
    for good: two producers on one trace is the bug docs/clocking.md prevents."""
    node = a_node()
    node._free_run()
    node._free_run()
    assert (node._tick_seq, node._clock_seen) == (2, False)

    node.tick_callback(a_pulse(seq=50, t=50.0))
    assert (node._tick_seq, node._clock_seen) == (50, True)

    node._free_run()
    assert node._tick_seq == 50, "the fallback kept counting after the clock arrived"


def test_a_malformed_pulse_is_refused_rather_than_adopted():
    """A tick with no `t0` is refused by `validate_tick` -- and a clock that restarts
    is indistinguishable from a redelivery without it."""
    node = a_node()
    node.tick_callback(a_pulse(seq=3, t=3.0))

    node.tick_callback(String(data='{"schema_version": 1, "seq": 99}'))
    node.tick_callback(String(data="not json at all"))

    assert node._tick_seq == 3, "a malformed pulse moved the tick index"
