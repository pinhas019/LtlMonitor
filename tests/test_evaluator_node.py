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
from skill_monitor.backend.adapters.declarative import DeclarativeAdapter  # noqa: E402
from skill_monitor.backend import evaluator_node                            # noqa: E402
from skill_monitor.backend.evaluator_node import GenericClientNode         # noqa: E402
from skill_monitor.core import api                                         # noqa: E402

LEGACY_ADAPTER = evaluator_node._LEGACY_ADAPTER


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
