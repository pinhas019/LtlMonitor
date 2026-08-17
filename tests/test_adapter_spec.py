"""The adapter-as-data mapping, exercised with plain objects instead of a ROS graph.

What these protect: a descriptor is now the only thing standing between a robot's
topics and every atomic proposition, so a silently-wrong field path or a schema key
that no source ever writes is a monitor that reports plausible nonsense.
"""

import math

import pytest

from skill_monitor.core import adapter_spec


def _ns(**kw):
    """Nested attribute object, standing in for a ROS message."""
    class N:
        def __init__(self, d):
            for k, v in d.items():
                setattr(self, k, v)
    return N(kw)


def _odom(z=1.0, vx=0.0, wz=0.0, q=(0.0, 0.0, 0.0, 1.0)):
    return _ns(
        pose=_ns(pose=_ns(position=_ns(x=0.0, y=0.0, z=z),
                          orientation=_ns(x=q[0], y=q[1], z=q[2], w=q[3]))),
        twist=_ns(twist=_ns(linear=_ns(x=vx), angular=_ns(z=wz))),
    )


def test_every_shipped_descriptor_loads_and_covers_its_schema():
    assert adapter_spec.available(), "no descriptors found"
    for name in adapter_spec.available():
        spec = adapter_spec.load(name)
        state = adapter_spec.SensorState(spec)
        # Full key set before a single message has arrived: the evaluator publishes
        # every tick, including the first.
        assert set(state.sensor_eval()) == set(spec.keys()), name
        assert all(v is not None for v in state.sensor_eval().values()), name


def test_odom_fields_and_derived_upright():
    st = adapter_spec.SensorState(adapter_spec.load("real_g1"))
    st.update("odom", _odom(z=0.9, vx=0.5123, wz=-0.2))
    v = st.sensor_eval()
    assert v["linear_vel"] == 0.51 and v["angular_vel"] == -0.2
    assert v["base_height"] == 0.9
    assert v["base_roll"] == 0.0 and v["base_pitch"] == 0.0
    assert v["upright_flag"] == 1.0

    # Collapsed on the floor: height below the limit flips the derived flag.
    st.update("odom", _odom(z=0.2))
    assert st.sensor_eval()["upright_flag"] == 0.0

    # Rolled over: tilt alone is enough, height still fine.
    half = math.sin(0.9 / 2), math.cos(0.9 / 2)
    st.update("odom", _odom(z=1.0, q=(half[0], 0.0, 0.0, half[1])))
    v = st.sensor_eval()
    assert v["upright_flag"] == 0.0 and v["base_roll"] == pytest.approx(0.9, abs=1e-3)


def test_pointcloud_uses_the_optical_remap():
    st = adapter_spec.SensorState(adapter_spec.load("real_g1"))
    # Optical frame: (x right, y down, z forward). A wall 2 m ahead at chest height
    # is (0, -0.8, 2.0); without the remap this reads as no obstacle at all.
    st.update("points", [(0.0, -0.8, 2.0)])
    assert st.sensor_eval()["min_range"] == 2.0

    # A point on the ground is outside the height band and must not count.
    st.update("points", [(0.0, 1.1, 0.5)])
    assert st.sensor_eval()["min_range"] == 10.0


def test_status_json_maps_and_debounces_stuck():
    spec = adapter_spec.load("real_g1")
    st = adapter_spec.SensorState(spec)
    st.update("status", {"mode": "AUTOMATIC", "state": "following",
                         "finished": False, "num_waypoints": 3,
                         "current_target_idx": 1})
    v = st.sensor_eval()
    assert v["nav_mode"] == "AUTOMATIC" and v["nav_state"] == "following"
    assert v["num_waypoints"] == 3 and v["current_target_idx"] == 1
    assert v["mission_finished"] is False and v["nav_stuck"] is False

    # One blocked tick is not stuck; ten consecutive ones are.
    for _ in range(9):
        st.update("status", {"state": "no_path_found"})
    assert st.sensor_eval()["nav_stuck"] is False
    st.update("status", {"state": "no_path_found"})
    assert st.sensor_eval()["nav_stuck"] is True
    # Recovery clears it immediately.
    st.update("status", {"state": "following"})
    assert st.sensor_eval()["nav_stuck"] is False

    # Absent fields fall back to the step default rather than blanking the key.
    assert st.sensor_eval()["num_waypoints"] == 0


def test_two_instances_do_not_share_debounce_state():
    a = adapter_spec.SensorState(adapter_spec.load("real_g1"))
    b = adapter_spec.SensorState(adapter_spec.load("real_g1"))
    for _ in range(10):
        a.update("status", {"state": "unreachable"})
    assert a.sensor_eval()["nav_stuck"] is True
    assert b.sensor_eval()["nav_stuck"] is False


def test_nav2_status_source_leaves_state_alone_when_no_goals():
    st = adapter_spec.SensorState(adapter_spec.load("mujoco"))
    assert st.sensor_eval()["nav_mode"] == "MANUAL"
    st.update("nav2", None)                     # empty status_list decodes to None
    assert st.sensor_eval()["nav_state"] == "waiting_inputs"
    st.update("nav2", 4)                        # succeeded
    v = st.sensor_eval()
    assert v["nav_state"] == "finished" and v["mission_finished"] is True
    assert v["nav_mode"] == "AUTOMATIC"


def test_laserscan_ignores_no_return_encodings():
    st = adapter_spec.SensorState(adapter_spec.load("mujoco"))
    st.update("range", [float("inf"), 0.0, float("nan"), 3.25])
    assert st.sensor_eval()["min_range"] == 3.25
    st.update("range", [float("inf"), 0.0])
    assert st.sensor_eval()["min_range"] == 10.0


def test_scalar_field_source():
    st = adapter_spec.SensorState(adapter_spec.load("real_g1"))
    st.update("vision", _ns(data=0.8712))
    assert st.sensor_eval()["image_similarity_to_goal"] == 0.871


def test_descriptor_writing_an_undeclared_key_is_rejected_at_load():
    raw = {
        "name": "bad", "schema": {"a": {"doc": "", "default": 0}},
        "sources": [{"id": "s", "topic": "/t", "type": "std_msgs/msg/Float32",
                     "steps": [{"key": "typo_a", "field": "data"}]}],
    }
    with pytest.raises(ValueError, match="schema does not declare"):
        adapter_spec.from_dict(raw)


def test_unknown_extractor_is_rejected_at_load():
    raw = {
        "name": "bad", "schema": {"a": {"doc": "", "default": 0}},
        "sources": [{"id": "s", "topic": "/t", "type": "std_msgs/msg/Float32",
                     "steps": [{"key": "a", "fn": "teleport"}]}],
    }
    with pytest.raises(ValueError, match="unknown extractor"):
        adapter_spec.from_dict(raw)


def test_schema_key_no_source_writes_and_no_default_is_rejected():
    raw = {
        "name": "bad",
        "schema": {"a": {"doc": "", "default": 0}, "orphan": {"doc": ""}},
        "sources": [{"id": "s", "topic": "/t", "type": "std_msgs/msg/Float32",
                     "steps": [{"key": "a", "field": "data"}]}],
    }
    with pytest.raises(ValueError, match="never produced"):
        adapter_spec.from_dict(raw)


def test_manifest_is_json_serializable_and_self_describing():
    import json
    m = adapter_spec.load("real_g1").manifest()
    round_tripped = json.loads(json.dumps(m))
    assert round_tripped["adapter"] == "real_g1"
    assert "min_range" in round_tripped["schema"]
    assert round_tripped["schema"]["min_range"]["doc"]
    topics = {s["topic"] for s in round_tripped["sources"]}
    assert "/path_manager/status" in topics
