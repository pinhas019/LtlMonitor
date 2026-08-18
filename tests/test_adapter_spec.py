"""The adapter-as-data mapping, exercised with plain objects instead of a ROS graph.

What these protect: a descriptor is now the only thing standing between a robot's
topics and every atomic proposition, so a silently-wrong field path or a schema key
that no source ever writes is a monitor that reports plausible nonsense.

The behavioural tests are written against INLINE descriptors defined here rather than
against the shipped files in skill_monitor/adapters/. That is deliberate. The shipped
navigation schema is being redesigned to stop depending on the planner's own status
stream, and a test that pins its field paths would have to be rewritten with it --
whereas the window/fold/tick semantics below are embodiment-agnostic and must not
change. Only the structural invariants at the bottom iterate the shipped descriptors,
and they assert nothing about any particular robot's topics.
"""

import json
import math

import pytest

import skill_monitor
from skill_monitor.core import adapter_spec, api, spec_contract


# --------------------------------------------------------------- test fixtures

#: A schema wide enough to exercise every fold policy and both step phases, without
#: being any particular robot's schema.
SCHEMA = {
    "min_range": {"doc": "float, metres. Nearest obstacle ahead.", "default": 10.0},
    "base_roll": {"doc": "float, radians.", "default": 0.0},
    "base_pitch": {"doc": "float, radians.", "default": 0.0},
    "base_height": {"doc": "float, metres.", "default": 1.0},
    "upright_flag": {"doc": "float, 1.0 when upright.", "default": 1.0},
    "linear_vel": {"doc": "float, m/s.", "default": 0.0},
    "nav_state": {"doc": "string, the planner state.", "default": "waiting_inputs"},
    "nav_stuck": {"doc": "bool, blocked for a debounce window.", "default": False},
}


def _spec(sources, schema=None, **kw):
    return adapter_spec.from_dict(
        {"name": "t", "schema": dict(schema or SCHEMA), "sources": list(sources), **kw})


def _state(sources, schema=None, **kw):
    return adapter_spec.SensorState(_spec(sources, schema, **kw))


def _source(steps, sid="s", topic="/t", type_="std_msgs/msg/Float32", **kw):
    return {"id": sid, "topic": topic, "type": type_, "steps": list(steps), **kw}


#: One float field, folded by whichever policy the test is exercising.
def _range_source(aggregate=None, **kw):
    step = {"key": "min_range", "field": "range"}
    if aggregate is not None:
        step["aggregate"] = aggregate
    return _source([step], sid="points", topic="/points", **kw)


#: nav_state off a message, nav_stuck debounced once per TICK over the folded value.
def _status_source(debounce_s=10.0, **kw):
    return _source(
        [{"key": "nav_state", "field": "state", "default": "waiting_inputs"},
         {"key": "nav_stuck", "fn": "stuck_streak", "inputs": ["nav_state"],
          "on": "tick", "args": {"debounce_s": debounce_s}}],
        sid="status", topic="/status", type_="std_msgs/msg/String", **kw)


def _ns(**kw):
    """Nested attribute object, standing in for a ROS message."""
    class N:
        def __init__(self, d):
            for k, v in d.items():
                setattr(self, k, v)
    return N(kw)


def _odom(z=1.0, vx=0.0, q=(0.0, 0.0, 0.0, 1.0)):
    return _ns(
        pose=_ns(pose=_ns(position=_ns(x=0.0, y=0.0, z=z),
                          orientation=_ns(x=q[0], y=q[1], z=q[2], w=q[3]))),
        twist=_ns(twist=_ns(linear=_ns(x=vx), angular=_ns(z=0.0))),
    )


ODOM_SOURCE = _source(
    [{"key": "linear_vel", "field": "twist.twist.linear.x", "round": 2},
     {"key": "base_height", "field": "pose.pose.position.z", "round": 3},
     {"keys": ["base_roll", "base_pitch"], "fn": "quat_to_roll_pitch",
      "field": "pose.pose.orientation", "round": 3},
     {"key": "upright_flag", "fn": "upright",
      "inputs": ["base_roll", "base_pitch", "base_height"],
      "args": {"tilt_max": 0.5, "height_min": 0.5}}],
    sid="odom", topic="/odom", type_="nav_msgs/msg/Odometry")


# ------------------------------------------------- the two live bugs, pinned

def test_transient_obstacle_within_one_tick_is_not_lost():
    """The headline bug: at 1 Hz over a ~15-30 Hz cloud, last-sample-wins discards 29
    of 30 frames and the one it keeps need not be the frame that saw the obstacle.

    Asserted THROUGH the atomic proposition, by evaluating the rule the shipped spec
    actually carries, so this test cannot drift from formulas_g1.json.
    """
    st = _state([_range_source(aggregate="min")])
    for r in (5.0, 0.2, 5.0):
        st.update("points", {"range": r})
    st.tick()

    assert st.sensor_eval()["min_range"] == 0.2

    spec = json.loads(skill_monitor.spec_path("g1").read_text())
    rule = spec_contract.rule_of(spec["atomic_propositions"]["collision_risk"])
    assert rule, "collision_risk is no longer a rule AP"
    assert eval(rule, {"__builtins__": {}}, st.sensor_eval()) is True, (
        f"the transient obstacle survived the fold but {rule!r} did not see it")


def test_the_same_window_under_last_loses_the_obstacle():
    """The counterfactual, so the test above is known to be testing something."""
    st = _state([_range_source()])          # default aggregate
    for r in (5.0, 0.2, 5.0):
        st.update("points", {"range": r})
    st.tick()
    assert st.sensor_eval()["min_range"] == 5.0


def test_stuck_debounce_counts_ticks_not_messages():
    """`_fn_stuck_streak` used to advance inside Step.apply, i.e. once per incoming
    message, so a 5 Hz status topic turned a declared 10 s debounce into 2 s."""
    st = _state([_status_source(debounce_s=10.0)])       # tick_hz 1.0 -> 10 ticks

    for _ in range(30):
        st.update("status", {"state": "no_path_found"})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is False, "30 messages in one tick is one tick"

    for _ in range(8):                                    # ticks 2..9
        st.update("status", {"state": "no_path_found"})
        st.tick()
    assert st.sensor_eval()["nav_stuck"] is False

    st.update("status", {"state": "no_path_found"})       # tick 10
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is True


def test_stuck_debounce_is_expressed_in_seconds():
    spec = _spec([_status_source(debounce_s=10.0)], tick_hz=5.0)
    assert spec.resolved_thresholds()["nav_stuck"] == 50
    # ...and the resolved integer is readable off the wire, so a spec's "10+
    # consecutive ticks" prose has exactly one source of truth.
    assert spec.manifest()["schema"]["nav_stuck"]["debounce_ticks"] == 50

    st = adapter_spec.SensorState(spec)
    for _ in range(49):
        st.update("status", {"state": "unreachable"})
        st.tick()
    assert st.sensor_eval()["nav_stuck"] is False
    st.update("status", {"state": "unreachable"})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is True


def test_debounce_rounds_up_and_floors_at_one_tick():
    from skill_monitor.core.stuck_detector import threshold_from_seconds

    assert threshold_from_seconds(10.0, 1.0) == 10
    assert threshold_from_seconds(10.0, 5.0) == 50
    assert threshold_from_seconds(2.5, 1.0) == 3          # never fires early
    assert threshold_from_seconds(0.1, 1.0) == 1          # floors at one observation
    assert threshold_from_seconds(0.001, 1.0) == 1
    # Binary floating point: 1.1 * 10 is 11.000000000000002, and a bare ceil() would
    # silently turn a declared 11 ticks into 12.
    assert threshold_from_seconds(1.1, 10.0) == 11
    assert threshold_from_seconds(0.3, 10.0) == 3

    for bad in (0.0, -1.0):
        with pytest.raises(ValueError, match="debounce_s"):
            threshold_from_seconds(bad, 1.0)
    with pytest.raises(ValueError, match="tick_hz"):
        threshold_from_seconds(1.0, 0.0)


# ------------------------------------------------------- the observation window

def test_window_is_cleared_between_ticks():
    st = _state([_range_source(aggregate="min")])
    for r in (5.0, 0.2):
        st.update("points", {"range": r})
    st.tick()
    assert st.sensor_eval()["min_range"] == 0.2

    st.update("points", {"range": 5.0})
    st.tick()
    assert st.sensor_eval()["min_range"] == 5.0, "last tick's samples leaked forward"


def test_ticking_while_idle_does_not_accumulate():
    st = _state([_range_source(aggregate="min")])
    for _ in range(200):
        st.update("points", {"range": 5.0})
        st.tick()
    assert st.pending_samples() == 0
    # And an idle stretch afterwards cannot resurrect any of it.
    for _ in range(200):
        st.tick()
    assert st.pending_samples() == 0
    assert st.sensor_eval()["min_range"] == 5.0


def test_a_tick_with_no_data_still_ticks():
    st = _state([_range_source(aggregate="min")])
    st.update("points", {"range": 3.0})
    st.tick()
    before = st.sensor_eval()

    st.tick()
    assert st.ticks == 1, "the tick index must advance whether or not data arrived"
    assert st.sensor_eval() == before, "values hold across an empty tick"
    assert st.refreshed_keys() == frozenset(), "nothing was refreshed"
    assert st.refreshed_sources() == frozenset()


def test_a_key_with_no_sample_holds_its_last_value():
    st = _state([_range_source(aggregate="min"), _status_source()])
    st.update("points", {"range": 0.4})
    st.update("status", {"state": "following"})
    st.tick()
    assert st.refreshed_keys() == {"min_range", "nav_state"}

    st.update("status", {"state": "following"})           # only the status topic
    st.tick()
    assert st.sensor_eval()["min_range"] == 0.4, "zero-order hold is preserved"
    assert "min_range" not in st.refreshed_keys(), "a held value is not evidence"
    assert st.refreshed_keys() == {"nav_state"}
    assert st.refreshed_sources() == {"status"}


def test_sensor_eval_is_a_pure_read():
    st = _state([_range_source(aggregate="min")])
    st.update("points", {"range": 0.9})
    st.tick()

    reads = [st.sensor_eval() for _ in range(3)]
    assert reads[0] == reads[1] == reads[2]
    assert reads[0]["min_range"] == 0.9

    # Reading must not consume the window, and must not be what closes a tick.
    st.update("points", {"range": 0.1})
    assert st.sensor_eval()["min_range"] == 0.9, "a getter must not fold"
    assert st.pending_samples() == 1
    assert st.sensor_eval()["min_range"] == 0.9
    st.tick()
    assert st.sensor_eval()["min_range"] == 0.1


def test_a_bad_fold_leaves_the_observation_intact_and_recovers():
    """The fold is built in full before anything is committed, so a `min` over mixed
    types cannot leave half the observation updated -- and the poisoned window costs
    exactly one tick rather than raising out of every tick from then on."""
    st = _state([_range_source(aggregate="min"),
                 _source([{"key": "linear_vel", "field": "v"}], sid="odom", topic="/o")])
    st.update("points", {"range": 0.4})
    st.update("odom", {"v": 1.5})
    st.tick()
    good = st.sensor_eval()
    assert good["min_range"] == 0.4 and good["linear_vel"] == 1.5

    st.update("points", {"range": 1.0})
    st.update("points", {"range": "not a number"})        # min() over mixed types
    st.update("odom", {"v": 9.9})
    with pytest.raises(ValueError, match="min_range"):
        st.tick()
    assert st.sensor_eval() == good, "a failed fold half-committed the observation"

    st.update("points", {"range": 2.0})
    st.tick()
    assert st.sensor_eval()["min_range"] == 2.0, "the poisoned window wedged the tick"


def test_sensor_eval_returns_a_copy():
    st = _state([_range_source()])
    st.sensor_eval()["min_range"] = -1.0
    assert st.sensor_eval()["min_range"] == 10.0


def test_default_aggregate_is_last_and_matches_todays_behaviour():
    """A descriptor that declares nothing must behave exactly as it did before the
    window existed: the final message of the tick wins, key by key."""
    spec = _spec([_range_source()])
    assert spec.aggregate_by_key()["min_range"] == "last"

    st = adapter_spec.SensorState(spec)
    for r in (1.0, 2.0, 3.0):
        st.update("points", {"range": r})
    st.tick()
    assert st.sensor_eval()["min_range"] == 3.0


@pytest.mark.parametrize("policy,samples,expected", [
    ("last", [1.0, 2.0, 3.0], 3.0),
    ("first", [1.0, 2.0, 3.0], 1.0),
    ("min", [5.0, 0.2, 5.0], 0.2),
    ("max", [5.0, 0.2, 5.0], 5.0),
    ("mean", [1.0, 2.0, 3.0], 2.0),
])
def test_aggregate_vocabulary(policy, samples, expected):
    st = _state([_range_source(aggregate=policy)])
    for s in samples:
        st.update("points", {"range": s})
    st.tick()
    assert st.sensor_eval()["min_range"] == pytest.approx(expected)


def test_any_and_all_fold_booleans():
    schema = {"nav_stuck": {"doc": "bool", "default": False}}
    for policy, expected in (("any", True), ("all", False)):
        st = _state(
            [_source([{"key": "nav_stuck", "field": "flag", "aggregate": policy}],
                     sid="s")],
            schema=schema)
        for flag in (False, True, False):
            st.update("s", {"flag": flag})
        st.tick()
        assert st.sensor_eval()["nav_stuck"] is expected


def test_quantile_interpolates():
    src = _source([{"key": "min_range", "field": "range",
                    "aggregate": "quantile", "q": 0.5}], sid="points")
    st = _state([src])
    for r in (1.0, 2.0, 9.0):
        st.update("points", {"range": r})
    st.tick()
    assert st.sensor_eval()["min_range"] == 2.0


# ------------------------------------------------------------------ tick-steps

def test_tick_steps_see_this_ticks_folded_value():
    """The difference between "blocked for 10 s" and "blocked for 10 s, reported one
    tick late" -- the most likely thing to be silently wrong."""
    st = _state([_status_source(debounce_s=1.0)])         # threshold 1 tick
    st.update("status", {"state": "no_path_found"})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is True, (
        "the tick-step read last tick's held value, not the one just folded")


def test_tick_steps_run_on_an_empty_window_too():
    st = _state([_status_source(debounce_s=3.0)])
    st.update("status", {"state": "unreachable"})
    st.tick()                                             # streak 1
    st.tick()                                             # streak 2, no message
    assert st.sensor_eval()["nav_stuck"] is False
    st.tick()                                             # streak 3 -> fires
    assert st.sensor_eval()["nav_stuck"] is True


def test_streak_advances_on_a_tick_with_no_status_message():
    """A status topic that publishes on transitions only still has to debounce in
    time: the held nav_state is what the tick-step reads."""
    st = _state([_status_source(debounce_s=5.0)])
    st.update("status", {"state": "no_traversable"})
    st.tick()
    assert st.refreshed_keys() == {"nav_state"}

    for _ in range(4):
        st.tick()                                         # not one further message
        assert "nav_state" not in st.refreshed_keys(), (
            "a held value must never be reported as refreshed")
    assert st.sensor_eval()["nav_state"] == "no_traversable"
    assert st.sensor_eval()["nav_stuck"] is True


def test_tick_step_output_is_never_windowed():
    st = _state([_status_source(debounce_s=1.0)])
    st.update("status", {"state": "no_path_found"})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is True
    assert st.pending_samples() == 0, "a tick-step's output leaked into the next window"
    assert "nav_stuck" not in st.refreshed_keys(), (
        "a derived value is not a sample; refreshed_keys reports observations")


def test_recovery_clears_the_streak():
    st = _state([_status_source(debounce_s=2.0)])
    for _ in range(2):
        st.update("status", {"state": "unreachable"})
        st.tick()
    assert st.sensor_eval()["nav_stuck"] is True
    st.update("status", {"state": "following"})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is False


def test_two_instances_do_not_share_debounce_state():
    spec_a, spec_b = _spec([_status_source(debounce_s=2.0)]), _spec(
        [_status_source(debounce_s=2.0)])
    a, b = adapter_spec.SensorState(spec_a), adapter_spec.SensorState(spec_b)
    for _ in range(2):
        a.update("status", {"state": "unreachable"})
        a.tick()
    b.tick()
    assert a.sensor_eval()["nav_stuck"] is True
    assert b.sensor_eval()["nav_stuck"] is False


# ---------------------------------------------------- within-message chaining

def test_within_message_chaining_survives_windowing():
    """`upright_flag` must be computed from THIS message's roll/pitch/height. If the
    chain read the held values instead, the height would still be last tick's 1.0 and
    the flag would come out 1.0 for a robot lying on the floor."""
    st = _state([ODOM_SOURCE])
    st.update("odom", _odom(z=0.2))
    st.tick()
    v = st.sensor_eval()
    assert v["base_height"] == 0.2
    assert v["upright_flag"] == 0.0, "upright read last tick's height, not this message's"


def test_chaining_uses_the_latest_message_not_the_folded_window():
    st = _state([ODOM_SOURCE])
    st.update("odom", _odom(z=1.0))                       # upright
    st.update("odom", _odom(z=0.2))                       # collapsed
    st.tick()
    # Both messages chained correctly within themselves; `last` then picks the second.
    assert st.sensor_eval()["upright_flag"] == 0.0
    assert st.sensor_eval()["base_height"] == 0.2


def test_derived_keys_land_in_the_window_and_are_refreshed():
    st = _state([ODOM_SOURCE])
    st.update("odom", _odom(z=0.9, vx=0.5123))
    st.tick()
    v = st.sensor_eval()
    assert v["linear_vel"] == 0.51
    assert v["base_roll"] == 0.0 and v["base_pitch"] == 0.0
    assert v["upright_flag"] == 1.0
    assert {"linear_vel", "base_height", "base_roll", "base_pitch",
            "upright_flag"} <= st.refreshed_keys()


def test_tilt_alone_flips_upright():
    st = _state([ODOM_SOURCE])
    half = math.sin(0.9 / 2), math.cos(0.9 / 2)
    st.update("odom", _odom(z=1.0, q=(half[0], 0.0, 0.0, half[1])))
    st.tick()
    v = st.sensor_eval()
    assert v["upright_flag"] == 0.0
    assert v["base_roll"] == pytest.approx(0.9, abs=1e-3)


# ------------------------------------------------------------------ extractors

def test_pointcloud_uses_the_optical_remap():
    src = _source([{"key": "min_range", "fn": "min_range_points", "round": 2,
                    "args": {"z_lo": 0.1, "z_hi": 1.5, "default": 10.0,
                             "frame": "optical"}}],
                  sid="points", type_="sensor_msgs/msg/PointCloud2",
                  decode="pointcloud_xyz")
    st = _state([src])
    # Optical frame: (x right, y down, z forward). A wall 2 m ahead at chest height is
    # (0, -0.8, 2.0); without the remap this reads as no obstacle at all.
    st.update("points", [(0.0, -0.8, 2.0)])
    st.tick()
    assert st.sensor_eval()["min_range"] == 2.0

    st.update("points", [(0.0, 1.1, 0.5)])                # ground, outside the band
    st.tick()
    assert st.sensor_eval()["min_range"] == 10.0


def test_laserscan_ignores_no_return_encodings():
    src = _source([{"key": "min_range", "fn": "min_range_scan", "round": 2,
                    "args": {"default": 10.0}}],
                  sid="range", type_="sensor_msgs/msg/LaserScan",
                  decode="laserscan_ranges")
    st = _state([src])
    st.update("range", [float("inf"), 0.0, float("nan"), 3.25])
    st.tick()
    assert st.sensor_eval()["min_range"] == 3.25
    st.update("range", [float("inf"), 0.0])
    st.tick()
    assert st.sensor_eval()["min_range"] == 10.0


def test_nav2_status_extractor_leaves_state_alone_when_no_goals():
    schema = {"nav_state": {"doc": "string", "default": "waiting_inputs"}}
    src = _source([{"key": "nav_state", "fn": "nav2_status"}],
                  sid="nav2", type_="action_msgs/msg/GoalStatusArray",
                  decode="goal_status", qos="action_status")
    st = _state([src], schema=schema)
    st.update("nav2", None)                               # empty status_list -> None
    st.tick()
    assert st.sensor_eval()["nav_state"] == "waiting_inputs"
    st.update("nav2", 4)                                  # succeeded
    st.tick()
    assert st.sensor_eval()["nav_state"] == "finished"


def test_scalar_field_and_step_default():
    schema = {"linear_vel": {"doc": "float", "default": 0.0}}
    src = _source([{"key": "linear_vel", "field": "data", "round": 3}], sid="vision")
    st = _state([src], schema=schema)
    st.update("vision", _ns(data=0.8712))
    st.tick()
    assert st.sensor_eval()["linear_vel"] == 0.871

    # An absent field with no default contributes nothing rather than blanking the key.
    st.update("vision", _ns(other=1.0))
    st.tick()
    assert st.sensor_eval()["linear_vel"] == 0.871
    assert st.refreshed_keys() == frozenset()


def test_casts_and_step_defaults_apply_before_the_fold():
    schema = {"nav_stuck": {"doc": "bool", "default": False}}
    src = _source([{"key": "nav_stuck", "field": "finished", "default": False,
                    "cast": "bool"}], sid="status", type_="std_msgs/msg/String",
                  decode="json")
    st = _state([src], schema=schema)
    st.update("status", {})                               # field absent -> the default
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is False
    st.update("status", {"finished": 1})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is True


# ------------------------------------------------------------------ validation

def test_unknown_key_on_a_step_is_rejected_at_load():
    """The highest-value rule of the set: {"agregate": "min"} used to be accepted in
    silence, leaving the fold on its default and the transient-obstacle bug live."""
    with pytest.raises(ValueError, match="agregate"):
        _spec([_source([{"key": "min_range", "field": "range", "agregate": "min"}])])


def test_unknown_key_on_a_source_is_rejected_at_load():
    with pytest.raises(ValueError, match="trackd"):
        _spec([_source([{"key": "min_range", "field": "range"}], trackd=True)])


def test_unknown_key_on_the_descriptor_is_rejected_at_load():
    with pytest.raises(ValueError, match="tik_hz"):
        _spec([_range_source()], tik_hz=5.0)


def test_unknown_aggregate_is_rejected_at_load():
    with pytest.raises(ValueError, match="minimum"):
        _spec([_range_source(aggregate="minimum")])


def test_quantile_without_q_is_rejected_at_load():
    with pytest.raises(ValueError, match="quantile"):
        _spec([_range_source(aggregate="quantile")])


def test_q_without_quantile_is_rejected_at_load():
    with pytest.raises(ValueError, match="quantile"):
        _spec([_source([{"key": "min_range", "field": "range", "q": 0.5}])])


def test_numeric_aggregate_on_a_string_key_is_rejected_at_load():
    with pytest.raises(ValueError, match="nav_state"):
        _spec([_source([{"key": "nav_state", "field": "state", "aggregate": "min"}])])


def test_numeric_aggregate_on_a_bool_key_is_rejected_at_load():
    with pytest.raises(ValueError, match="nav_stuck"):
        _spec([_source([{"key": "nav_stuck", "field": "flag", "aggregate": "mean"}])])


def test_two_sources_folding_one_key_differently_are_rejected_at_load():
    with pytest.raises(ValueError, match="min_range"):
        _spec([
            _source([{"key": "min_range", "field": "range", "aggregate": "min"}],
                    sid="a", topic="/a"),
            _source([{"key": "min_range", "field": "range", "aggregate": "max"}],
                    sid="b", topic="/b"),
        ])


def test_two_sources_folding_one_key_the_same_way_are_fine():
    spec = _spec([
        _source([{"key": "min_range", "field": "range", "aggregate": "min"}],
                sid="a", topic="/a"),
        _source([{"key": "min_range", "field": "range", "aggregate": "min"}],
                sid="b", topic="/b"),
    ])
    assert spec.aggregate_by_key()["min_range"] == "min"


def test_tick_step_without_inputs_is_rejected_at_load():
    with pytest.raises(ValueError, match="nav_stuck"):
        _spec([_source([{"key": "nav_stuck", "fn": "stuck_streak", "on": "tick"}])])


def test_tick_step_with_a_field_is_rejected_at_load():
    with pytest.raises(ValueError, match="nav_stuck"):
        _spec([_source([{"key": "nav_stuck", "fn": "stuck_streak", "on": "tick",
                         "field": "state", "inputs": ["nav_state"]}])])


def test_tick_step_declaring_an_aggregate_is_rejected_at_load():
    with pytest.raises(ValueError, match="nav_stuck"):
        _spec([_source([{"key": "nav_stuck", "fn": "stuck_streak", "on": "tick",
                         "inputs": ["nav_state"], "aggregate": "any"}])])


def test_unknown_step_phase_is_rejected_at_load():
    with pytest.raises(ValueError, match="tock"):
        _spec([_source([{"key": "min_range", "field": "range", "on": "tock"}])])


def test_debounce_outside_a_tick_step_is_rejected_at_load():
    with pytest.raises(ValueError, match="nav_stuck"):
        _spec([_source([{"key": "nav_stuck", "fn": "stuck_streak",
                         "inputs": ["nav_state"], "args": {"debounce_s": 10.0}}])])


def test_threshold_and_debounce_together_are_rejected_at_load():
    with pytest.raises(ValueError, match="nav_stuck"):
        _spec([_source([{"key": "nav_stuck", "fn": "stuck_streak", "on": "tick",
                         "inputs": ["nav_state"],
                         "args": {"threshold": 10, "debounce_s": 10.0}}])])


@pytest.mark.parametrize("bad", [0, -1.0])
def test_non_positive_tick_hz_is_rejected_at_load(bad):
    with pytest.raises(ValueError, match="tick_hz"):
        _spec([_range_source()], tick_hz=bad)


@pytest.mark.parametrize("field", ["expected_hz", "max_age_s"])
def test_non_positive_source_health_is_rejected_at_load(field):
    with pytest.raises(ValueError, match=field):
        _spec([_range_source(**{field: 0})])


def test_cross_source_inputs_are_rejected_at_load():
    """A message-step chained onto another source's key mixes two time bases."""
    with pytest.raises(ValueError, match="nav_state"):
        _spec([
            _status_source(),
            _source([{"key": "nav_stuck", "fn": "eq", "inputs": ["nav_state"],
                      "args": {"to": "no_path_found"}}], sid="other", topic="/o"),
        ])


def test_a_tick_step_may_read_another_sources_key():
    """The complement of the rule above: a tick-step reads the folded observation, so
    crossing sources is exactly what it is for."""
    spec = _spec([
        _source([{"key": "nav_state", "field": "state"}], sid="status", topic="/s"),
        _source([{"key": "nav_stuck", "fn": "stuck_streak", "inputs": ["nav_state"],
                  "on": "tick", "args": {"debounce_s": 1.0}}], sid="other", topic="/o"),
    ])
    st = adapter_spec.SensorState(spec)
    st.update("status", {"state": "unreachable"})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is True


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


def test_unknown_source_id_on_update_raises():
    st = _state([_range_source()])
    with pytest.raises(KeyError, match="nope"):
        st.update("nope", {"range": 1.0})


# ------------------------------------------------------------- data health

def test_source_health_defaults_are_derived_not_invented():
    spec = _spec([_range_source(expected_hz=15.0)])
    src = spec.sources[0]
    assert src.expected_hz == 15.0
    assert src.max_age_s == pytest.approx(max(2 / 15.0, 1 / 1.0))
    assert src.required is True                           # defaults to `tracked`


def test_required_is_not_the_same_field_as_tracked():
    spec = _spec([_range_source(tracked=False, required=True)])
    src = spec.sources[0]
    assert src.tracked is False and src.required is True


def test_a_source_without_expected_hz_is_a_warning_not_an_error():
    spec = _spec([_range_source()])
    assert spec.sources[0].expected_hz == spec.tick_hz
    assert any("expected_hz" in w and "points" in w for w in spec.warnings())


def test_last_on_a_fast_source_is_warned_about():
    """The transient-obstacle bug, made visible on the wire for any descriptor that
    declares its rates honestly and leaves the fold on its default."""
    spec = _spec([_range_source(expected_hz=30.0)], tick_hz=1.0)
    assert any("min_range" in w and "discarded" in w for w in spec.warnings())

    quiet = _spec([_range_source(aggregate="min", expected_hz=30.0)], tick_hz=1.0)
    assert not any("discarded" in w for w in quiet.warnings())


def test_last_on_a_state_like_key_is_not_warned_about():
    """`last` on a planner state string or a bool is the RIGHT answer, not a bug.
    Warning about those would train people to ignore the warnings."""
    spec = _spec([_status_source(expected_hz=30.0)], tick_hz=1.0)
    assert not any("discarded" in w for w in spec.warnings()), spec.warnings()


# --------------------------------------------------- manifest / wire contract

def test_manifest_is_json_serializable_and_self_describing():
    m = _spec([_range_source(expected_hz=15.0)], doc="a test robot").manifest()
    round_tripped = json.loads(json.dumps(m))
    assert round_tripped["adapter"] == "t"
    assert round_tripped["doc"] == "a test robot"
    assert round_tripped["tick_hz"] == 1.0
    assert "min_range" in round_tripped["schema"]
    assert round_tripped["schema"]["min_range"]["doc"]
    source = round_tripped["sources"][0]
    assert source["topic"] == "/points"
    assert source["expected_hz"] == 15.0 and source["required"] is True
    assert source["steps"] == [
        {"keys": ["min_range"], "aggregate": "last", "on": "message"}]


def test_manifest_reports_the_resolved_fold_policy():
    m = _spec([_range_source(aggregate="min")]).manifest()
    assert m["sources"][0]["steps"][0]["aggregate"] == "min"


def test_manifest_feeds_the_wire_contract_directly():
    """`api.build_adapter(**spec.manifest())` must type-check, so P2's manifest and
    P0's published payload cannot drift apart."""
    spec = _spec([_range_source(expected_hz=15.0), _status_source()])
    assert api.validate_adapter(api.build_adapter(**spec.manifest())) == []


# ------------------------------------- structural invariants, shipped descriptors

def test_every_shipped_descriptor_loads_and_covers_its_schema():
    assert adapter_spec.available(), "no descriptors found"
    for name in adapter_spec.available():
        spec = adapter_spec.load(name)
        state = adapter_spec.SensorState(spec)
        # Full key set before a single message has arrived: the evaluator publishes
        # every tick, including the first.
        assert set(state.sensor_eval()) == set(spec.keys()), name
        assert all(v is not None for v in state.sensor_eval().values()), name


def test_every_shipped_descriptor_resolves_tick_hz_and_per_source_health():
    """Health is DERIVED where a descriptor is silent, never absent -- the evaluator
    must be able to report an age for every source it subscribes to."""
    for name in adapter_spec.available():
        spec = adapter_spec.load(name)
        assert spec.tick_hz > 0, name
        for src in spec.sources:
            assert src.expected_hz > 0, f"{name}/{src.id}"
            assert src.max_age_s > 0, f"{name}/{src.id}"
            assert isinstance(src.required, bool), f"{name}/{src.id}"


def test_every_shipped_descriptor_announces_a_valid_manifest():
    for name in adapter_spec.available():
        spec = adapter_spec.load(name)
        problems = api.validate_adapter(api.build_adapter(**spec.manifest()))
        assert problems == [], f"{name}: {problems}"


def test_every_shipped_descriptor_ticks_without_data():
    """A tick fires even when nothing arrived -- that is the tick that has to report
    that nothing arrived."""
    for name in adapter_spec.available():
        state = adapter_spec.SensorState(adapter_spec.load(name))
        before = state.sensor_eval()
        state.tick()
        assert state.ticks == 0, name
        assert state.refreshed_keys() == frozenset(), name
        assert state.sensor_eval() == before, name
        assert state.pending_samples() == 0, name
