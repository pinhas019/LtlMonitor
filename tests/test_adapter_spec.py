"""The adapter-as-data mapping, exercised with plain objects instead of a ROS graph.

What these protect: a descriptor is now the only thing standing between a robot's
topics and every atomic proposition, so a silently-wrong field path or a schema key
that no source ever writes is a monitor that reports plausible nonsense.

The window/fold/tick SEMANTICS are exercised against inline descriptors defined here,
because they are embodiment-agnostic: pinning them to a particular robot's field paths
would mean rewriting them when the navigation schema is redesigned to stop depending on
the planner's own status stream.

The shipped descriptors are pinned separately, at the bottom, and that half is not
optional. A descriptor is the only thing standing between a robot's topics and every
atomic proposition, and it is a JSON file with no type checker, no linter and no
compiler behind it: `twist.twist.linear.y`, a `dta` instead of `data`, a dropped
`"frame": "optical"` or a mistyped topic name all load cleanly and produce a monitor
reporting plausible nonsense. Only a test that reads the shipped file catches those.
What is pinned is what the schema redesign does not touch -- the `odom`, `points`,
`range` and `vision` sources, and every source's topic, type, decode and qos. The
`status`/`nav2` FIELD paths are deliberately not pinned here, because those are the
ones being redesigned.
"""

import inspect
import json
import math
import sys
import threading
import time
import warnings

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


def test_a_raising_tick_step_rolls_the_whole_tick_back():
    """The tick-steps used to run outside the try, after the fold was committed. A
    tick-step that raised therefore left `values` describing tick k while `ticks` and
    `refreshed_keys()` still described tick k-1 -- so the observation and the seam P10
    is told to trust disagreed about which tick they were talking about.

    Reachable: a decode edge case leaves a string where a float belongs, and `upright`
    compares it.
    """
    src = _source(
        [{"key": "base_height", "field": "h"},
         {"key": "upright_flag", "fn": "upright", "on": "tick",
          "inputs": ["base_roll", "base_pitch", "base_height"]}],
        sid="odom", topic="/odom")
    st = _state([src])

    st.update("odom", {"h": 0.9})
    st.tick()
    before, ticks_before = st.sensor_eval(), st.ticks
    assert before["base_height"] == 0.9 and before["upright_flag"] == 1.0

    st.update("odom", {"h": "0.2"})                       # a str where a float belongs
    with pytest.raises(TypeError):
        st.tick()

    assert st.sensor_eval() == before, "the fold was committed by a tick that failed"
    assert st.ticks == ticks_before, "the tick index advanced past a tick that failed"
    assert st.refreshed_keys() == {"base_height"}, (
        "refreshed_keys described a different tick than sensor_eval did")
    assert st.pending_samples() == 0, "the poisoned window survived"

    st.update("odom", {"h": 0.3})
    st.tick()
    assert st.sensor_eval()["base_height"] == 0.3, "the failed tick wedged every tick"
    assert st.ticks == ticks_before + 1


def test_a_failed_tick_does_not_advance_the_debounce():
    """Worse than "the streak advanced": each failed tick permanently INFLATES it, so
    a declared ten-second debounce fires N ticks early where N is the number of failed
    ticks in its history. Same false positive reset() exists to prevent, arriving
    through a different door, on a safety-relevant AP.
    """
    status = _source(
        [{"key": "nav_state", "field": "state"},
         {"key": "nav_stuck", "fn": "stuck_streak", "inputs": ["nav_state"],
          "on": "tick", "args": {"debounce_s": 10.0}}],
        sid="status", topic="/status", type_="std_msgs/msg/String")
    # Declared second, so its tick-step runs AFTER the streak has already advanced --
    # which is the ordering that leaves the advance behind when it raises.
    raiser = _source(
        [{"key": "base_height", "field": "h"},
         {"key": "upright_flag", "fn": "upright", "on": "tick",
          "inputs": ["base_roll", "base_pitch", "base_height"]}],
        sid="odom", topic="/odom")
    st = _state([status, raiser], tick_hz=1.0)
    assert st.spec.resolved_thresholds()["nav_stuck"] == 10

    successful_blocked_ticks = 0
    for i in range(16):
        st.update("status", {"state": "no_path_found"})
        if i in (2, 5, 8):                                # three ticks that will fail
            st.update("odom", {"h": "not a height"})
            with pytest.raises(TypeError):
                st.tick()
            assert st.sensor_eval()["nav_stuck"] is False
            continue

        st.tick()
        successful_blocked_ticks += 1
        assert st.sensor_eval()["nav_stuck"] is (successful_blocked_ticks >= 10), (
            f"fired after {successful_blocked_ticks} successful blocked ticks; "
            f"the descriptor declares 10")


def test_a_failed_tick_does_not_reset_the_debounce_either():
    """The rollback restores the streak to its value at the START of the failed tick,
    which is not the same as clearing it -- a failure must cost that tick, not the two
    before it."""
    status = _source(
        [{"key": "nav_state", "field": "state"},
         {"key": "nav_stuck", "fn": "stuck_streak", "inputs": ["nav_state"],
          "on": "tick", "args": {"debounce_s": 3.0}}],
        sid="status", topic="/status", type_="std_msgs/msg/String")
    raiser = _source(
        [{"key": "base_height", "field": "h"},
         {"key": "upright_flag", "fn": "upright", "on": "tick",
          "inputs": ["base_roll", "base_pitch", "base_height"]}],
        sid="odom", topic="/odom")
    st = _state([status, raiser])

    for _ in range(2):
        st.update("status", {"state": "unreachable"})
        st.tick()                                         # streak 2 of 3

    st.update("odom", {"h": "not a height"})
    with pytest.raises(TypeError):
        st.tick()

    st.update("status", {"state": "unreachable"})
    st.tick()                                             # the third GOOD one
    assert st.sensor_eval()["nav_stuck"] is True, (
        "the failed tick threw away the two blocked ticks before it")


def test_a_raising_message_step_still_reports_its_source_as_alive():
    """A step that raises produces nothing and never reaches the end of update(), so
    recording arrival at the bottom made a live topic report as silent -- which
    promotes every AP over it to UNKNOWN and freezes the automaton. Reachable:
    quat_to_roll_pitch on an orientation the decoder left malformed."""
    st = _state([ODOM_SOURCE])
    malformed = _ns(pose=_ns(pose=_ns(position=_ns(z=1.0), orientation="not a quat")),
                    twist=_ns(twist=_ns(linear=_ns(x=0.0), angular=_ns(z=0.0))))

    with pytest.raises(TypeError):
        st.update("odom", malformed)
    st.tick()

    assert st.refreshed_sources() == {"odom"}, (
        "a topic that delivered a message it could not map was reported as silent")
    assert "base_roll" not in st.refreshed_keys(), "nothing was extracted, and says so"


def test_values_is_a_snapshot_not_a_live_view():
    """`values` is rebound by every tick rather than mutated, which is what makes a
    tick atomic -- no reader can see a half-updated dict. The cost, documented on the
    attribute: a consumer that CACHES the dict object freezes on a stale observation."""
    st = _state([_range_source()])
    cached = st.values

    st.update("points", {"range": 2.0})
    st.tick()

    assert cached["min_range"] == 10.0, "values is documented as a snapshot"
    assert st.values["min_range"] == 2.0, "re-reading the attribute is the contract"
    assert st.sensor_eval()["min_range"] == 2.0


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


def test_a_source_that_delivered_a_message_yielding_nothing_still_counts_as_refreshed():
    """Arrival and extraction YIELD are different questions. A Nav2 status with an
    empty status_list, or a JSON status whose fields are all absent, decodes to
    nothing -- but the topic is alive. Reporting it as having delivered nothing
    promotes every AP over that source to UNKNOWN and freezes the automaton."""
    src = _source([{"key": "linear_vel", "field": "v"}], sid="odom", topic="/odom")
    st = _state([src])

    st.update("odom", {"nothing_we_read": 1.0})           # a real message, no fields
    st.tick()
    assert st.refreshed_sources() == {"odom"}, (
        "a live topic was reported as silent because extraction yielded nothing")
    assert st.refreshed_keys() == frozenset(), "no key got a sample, and says so"


def test_a_source_that_sent_nothing_at_all_is_not_refreshed():
    """The complement, so the rule above is not just 'always true'."""
    st = _state([_source([{"key": "linear_vel", "field": "v"}], sid="odom")])
    st.tick()
    assert st.refreshed_sources() == frozenset()


@pytest.mark.parametrize("samples", [
    [1.0, float("nan"), 0.5],
    [float("nan"), 1.0, 0.5],
    [1.0, 0.5, float("nan")],
])
def test_non_finite_samples_do_not_make_min_depend_on_arrival_order(samples):
    """`min([1.0, nan, 0.5])` is 0.5 but `min([nan, 1.0, 0.5])` is nan -- so without
    this the observation depends on which frame of a depth cloud landed first."""
    st = _state([_range_source(aggregate="min")])
    for s in samples:
        st.update("points", {"range": s})
    st.tick()
    assert st.sensor_eval()["min_range"] == 0.5


def test_non_finite_samples_do_not_defeat_the_quantile_sort():
    src = _source([{"key": "min_range", "field": "range",
                    "aggregate": "quantile", "q": 0.5}], sid="points")
    st = _state([src])
    for r in (9.0, float("nan"), 1.0, float("inf"), 2.0):
        st.update("points", {"range": r})
    st.tick()
    assert st.sensor_eval()["min_range"] == 2.0


def test_a_window_of_only_non_finite_samples_holds_the_previous_value():
    """Dropping every sample leaves NO measurement, which is a held value and an
    unrefreshed key -- not a fabricated number."""
    st = _state([_range_source(aggregate="min")])
    st.update("points", {"range": 0.4})
    st.tick()
    assert st.sensor_eval()["min_range"] == 0.4

    for bad in (float("nan"), float("inf"), float("-inf")):
        st.update("points", {"range": bad})
    st.tick()
    assert st.sensor_eval()["min_range"] == 0.4, "a non-finite sample became the trace"
    assert "min_range" not in st.refreshed_keys()
    assert st.refreshed_sources() == {"points"}, "the topic was alive and said so"


def test_last_still_carries_a_non_finite_sample_through():
    """`last` is byte-identical to the pre-window behaviour, and that is load-bearing:
    it is not the fold's job to censor a value nobody asked it to order."""
    st = _state([_range_source()])
    st.update("points", {"range": float("nan")})
    st.tick()
    assert math.isnan(st.sensor_eval()["min_range"])


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


# ------------------------------------------------- the episode boundary: reset()

def test_two_states_over_ONE_spec_share_the_streak():
    """Pinned because it is surprising and because it is what reset() is for: the
    streak lives in the extractor's closure, which belongs to the SPEC. Constructing
    a fresh SensorState does not give you a fresh debounce."""
    spec = _spec([_status_source(debounce_s=2.0)])
    a, b = adapter_spec.SensorState(spec), adapter_spec.SensorState(spec)
    a.update("status", {"state": "unreachable"})
    a.tick()
    b.update("status", {"state": "unreachable"})
    b.tick()                                              # b's FIRST blocked tick
    assert b.sensor_eval()["nav_stuck"] is True, (
        "the shared streak stopped being shared; the reset() rationale needs revisiting")


def test_reset_clears_the_streak_at_an_episode_boundary():
    """`arm`/`reset` restarts the episode (docs/clocking.md). Carrying the previous
    episode's blocked ticks across it fires nav_stuck on the first blocked
    observation of a fresh run -- the exact false positive the debounce prevents."""
    st = _state([_status_source(debounce_s=3.0)])
    for _ in range(2):
        st.update("status", {"state": "unreachable"})
        st.tick()
    assert st.sensor_eval()["nav_stuck"] is False         # 2 of 3

    st.reset()

    st.update("status", {"state": "unreachable"})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is False, (
        "the previous episode's streak counted toward this one")
    st.update("status", {"state": "unreachable"})
    st.tick()
    st.update("status", {"state": "unreachable"})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is True, "and the fresh streak still works"


def test_reset_restores_the_defaults_the_window_and_the_tick_index():
    st = _state([_range_source(aggregate="min"), _status_source()])
    st.update("points", {"range": 0.2})
    st.tick()
    st.update("points", {"range": 0.3})                   # left in the OPEN window
    assert st.sensor_eval()["min_range"] == 0.2 and st.ticks == 0

    st.reset()
    assert st.sensor_eval() == st.spec.defaults()
    assert st.ticks == -1
    assert st.pending_samples() == 0
    assert st.refreshed_keys() == frozenset()
    assert st.refreshed_sources() == frozenset()


def test_reset_on_one_state_clears_the_shared_streak_for_the_other():
    spec = _spec([_status_source(debounce_s=2.0)])
    a, b = adapter_spec.SensorState(spec), adapter_spec.SensorState(spec)
    a.update("status", {"state": "unreachable"})
    a.tick()
    b.reset()
    b.update("status", {"state": "unreachable"})
    b.tick()
    assert b.sensor_eval()["nav_stuck"] is False


# --------------------------------- the one broken state sensor_eval cannot show you

def test_updating_forever_without_ticking_warns():
    """A caller that never calls tick() gets the schema defaults forever, and it is
    SILENT: sensor_eval() returns a full, plausible dict and every test stays green.
    DeclarativeAdapter is in exactly that state on dev today -- P3 is what will call
    tick() -- so this is a live regression, not a hypothetical one."""
    st = _state([_range_source()])
    budget = st._untick_budget

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(budget + 2):
            st.update("points", {"range": 1.0})

    assert len(caught) == 1, "warned per message, or not at all"
    assert issubclass(caught[0].category, RuntimeWarning)
    assert "tick()" in str(caught[0].message)
    assert st.updates_since_tick == budget + 2
    assert st.sensor_eval()["min_range"] == 10.0, "the schema default, forever"


def test_a_ticked_state_never_warns_however_fast_the_topic():
    """The budget is derived from the declared rates, so a genuinely fast source that
    IS being ticked must stay silent -- a warning that cries wolf is not a guard."""
    st = _state([_range_source(expected_hz=200.0)], tick_hz=1.0)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(50):
            for _ in range(200):                          # a full second of samples
                st.update("points", {"range": 1.0})
            st.tick()
    assert caught == [], [str(w.message) for w in caught]


def test_nothing_in_the_declarative_adapter_drives_the_clock(monkeypatch):
    """Pinning the live regression itself, so merging cannot make it invisible.

    `DeclarativeAdapter._on_message` calls `update()` and nothing calls `tick()`, so
    `get_sensor_eval()` returns the schema defaults for the life of the process. P3 is
    the package that drives the clock; when it does, THIS test fails, and that failure
    is the notification.

    It asserts on the MECHANISM, not on the values. A test that feeds messages and
    checks the values did not move still passes once a `tick()` method and a
    `register_clock()` exist, because a unit test spins no node and starts no timer --
    so the notification it was supposed to deliver would never arrive.
    """
    from skill_monitor.backend.adapters import declarative

    source = inspect.getsource(declarative)
    assert ".tick(" not in source, (
        "declarative.py now calls tick(): P3 has landed. Replace this test with one "
        "that asserts the observation DOES advance")

    adapter = declarative.DeclarativeAdapter("real_g1")
    assert not hasattr(adapter, "tick"), "the adapter grew a tick() -- see above"
    assert not hasattr(adapter, "register_clock"), (
        "the adapter grew a clock hook -- see above")

    # Registering subscriptions must not create a timer either: a timer that calls
    # nothing is how this ends up half-wired and looking finished.
    subscriptions, timers = [], []

    class _FakeNode:
        def create_subscription(self, *a, **kw):
            subscriptions.append(a)

        def create_timer(self, *a, **kw):
            timers.append(a)

    # The message CLASS lookup is the only part of this path that needs ROS.
    monkeypatch.setattr(declarative, "_msg_class", lambda type_str: object)
    adapter.register_subscriptions(_FakeNode())
    assert len(subscriptions) == len(adapter.spec.sources), "sanity: it did subscribe"
    assert timers == [], "a timer was created, but nothing calls tick()"

    # ...and the consequence, through the real message path rather than around it.
    odom = next(s for s in adapter.spec.sources if s.id == "odom")
    before = adapter.get_sensor_eval()
    for _ in range(50):
        adapter._on_message(odom, _shipped_odom(pz=0.2, vx=1.25))

    assert adapter.get_sensor_eval() == before, "something else is writing the values"
    assert adapter.state.updates_since_tick == 50, (
        "the window is where those 50 messages went, and it is not being closed")


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


def test_null_debounce_is_rejected_rather_than_falling_back_to_ten():
    """`"debounce_s": null` used to fall through to the extractor's own default of 10
    ticks -- in a file that raises on a misspelt "agregate"."""
    with pytest.raises(ValueError, match="debounce_s"):
        _spec([_source([{"key": "nav_stuck", "fn": "stuck_streak", "on": "tick",
                         "inputs": ["nav_state"], "args": {"debounce_s": None}}])])


@pytest.mark.parametrize("bad", ["10", float("inf"), float("nan"), True, 0, -1.0, []])
def test_a_bad_debounce_is_a_load_error_not_a_crash(bad):
    """Every rejection has to be a ValueError. `"10"` reached a multiplication as a
    TypeError and `inf` reached math.ceil() as an OverflowError, escaping the
    descriptor loader; `true` is an int in Python and silently resolved to one tick,
    i.e. a debounce that fires on the first blocked observation."""
    with pytest.raises(ValueError, match="debounce_s"):
        _spec([_source([{"key": "nav_stuck", "fn": "stuck_streak", "on": "tick",
                         "inputs": ["nav_state"], "args": {"debounce_s": bad}}])])


@pytest.mark.parametrize("bad", ["10", True, 0, -1, 1.5, float("nan"), None])
def test_a_bad_hand_written_threshold_is_rejected_at_load(bad):
    """`args.threshold` is the number all three shipped descriptors actually use, and
    it was entirely unvalidated: '10' and nan give a debounce that can never fire, 0
    and True give one satisfied before any sample arrived, and every one of them
    loaded and failed (or silently did not) at runtime instead."""
    with pytest.raises(ValueError, match="threshold"):
        _spec([_source([{"key": "nav_stuck", "fn": "stuck_streak",
                         "inputs": ["nav_state"], "args": {"threshold": bad}}],
                       sid="status", topic="/s", type_="std_msgs/msg/String")])


def test_a_good_hand_written_threshold_still_loads():
    spec = _spec([_source([{"key": "nav_state", "field": "state"},
                           {"key": "nav_stuck", "fn": "stuck_streak",
                            "inputs": ["nav_state"], "args": {"threshold": 4}}],
                          sid="status", topic="/s", type_="std_msgs/msg/String")])
    assert spec.manifest()["sources"][0]["steps"][1]["threshold"] == 4


@pytest.mark.parametrize("bad", ["2", True, -1, 1.5])
def test_a_bad_round_is_rejected_at_load(bad):
    """`round(v, "2")` is a TypeError on the first message, in a callback, on the
    robot -- not at load, where every other descriptor error surfaces."""
    with pytest.raises(ValueError, match="round"):
        _spec([_source([{"key": "min_range", "field": "range", "round": bad}],
                       sid="points")])


def test_round_null_means_no_rounding_and_is_not_an_error():
    """Unlike `debounce_s: null`, which fell through to a DIFFERENT default of 10,
    `"round": null` means exactly what omitting it means."""
    st = _state([_source([{"key": "min_range", "field": "range", "round": None}],
                         sid="points")])
    st.update("points", {"range": 1.23456})
    st.tick()
    assert st.sensor_eval()["min_range"] == 1.23456


@pytest.mark.parametrize("bad", ["0.5", True, float("nan"), 1.5, -0.1])
def test_a_bad_quantile_q_is_rejected_at_load(bad):
    with pytest.raises(ValueError, match="q"):
        _spec([_source([{"key": "min_range", "field": "range",
                         "aggregate": "quantile", "q": bad}], sid="points")])


def test_an_unknown_extractor_argument_is_rejected_at_load():
    """A misspelt kwarg reached the extractor as a TypeError out of the loader,
    escaping the handling every other bad descriptor gets -- and silently left the
    real argument on its default, which for z_lo/z_hi is the obstacle band."""
    with pytest.raises(ValueError, match="z_low"):
        _spec([_source([{"key": "min_range", "fn": "min_range_points",
                         "args": {"z_low": 0.1, "z_hi": 1.5}}], sid="points")])


def test_args_with_no_extractor_to_receive_them_is_rejected_at_load():
    with pytest.raises(ValueError, match="args"):
        _spec([_source([{"key": "min_range", "field": "range",
                         "args": {"threshold": 3}}], sid="points")])


@pytest.mark.parametrize("bad", [0, -1.0, True, float("inf"), float("nan"), "5"])
def test_non_positive_tick_hz_is_rejected_at_load(bad):
    with pytest.raises(ValueError, match="tick_hz"):
        _spec([_range_source()], tick_hz=bad)


@pytest.mark.parametrize("field", ["expected_hz", "max_age_s"])
@pytest.mark.parametrize("bad", [0, -1.0, True, float("inf")])
def test_non_positive_source_health_is_rejected_at_load(field, bad):
    with pytest.raises(ValueError, match=field):
        _spec([_range_source(**{field: bad})])


# ------------------------------------------------- `inputs` ordering, at load

def test_a_message_step_declared_before_its_producer_is_rejected_at_load():
    """Steps run in declaration order, so a consumer above its producer reads LAST
    TICK's value -- silently, for the whole life of the descriptor. Putting
    upright_flag above base_height used to load without complaint."""
    with pytest.raises(ValueError, match="base_height"):
        _spec([_source(
            [{"keys": ["base_roll", "base_pitch"], "fn": "quat_to_roll_pitch",
              "field": "pose.pose.orientation"},
             {"key": "upright_flag", "fn": "upright",
              "inputs": ["base_roll", "base_pitch", "base_height"]},
             {"key": "base_height", "field": "pose.pose.position.z"}],
            sid="odom", topic="/odom", type_="nav_msgs/msg/Odometry")])


def test_a_message_step_reading_its_own_sources_tick_step_is_rejected_at_load():
    """A tick-step runs after every message-step, so this reads the previous tick."""
    with pytest.raises(ValueError, match="nav_stuck"):
        _spec([_source(
            [{"key": "nav_state", "field": "state"},
             {"key": "linear_vel", "fn": "eq", "inputs": ["nav_stuck"],
              "args": {"to": True}},
             {"key": "nav_stuck", "fn": "stuck_streak", "inputs": ["nav_state"],
              "on": "tick", "args": {"debounce_s": 1.0}}],
            sid="status", topic="/s", type_="std_msgs/msg/String")])


def test_tick_steps_out_of_order_across_sources_are_rejected_at_load():
    """`tick_steps()` is source-order x step-order, so swapping two `sources` entries
    silently makes a consumer read a one-tick-stale value. Forever."""
    producer = _source(
        [{"key": "nav_stuck", "fn": "stuck_streak", "inputs": ["nav_state"],
          "on": "tick", "args": {"debounce_s": 1.0}}], sid="a", topic="/a")
    consumer = _source(
        [{"key": "upright_flag", "fn": "eq", "inputs": ["nav_stuck"], "on": "tick",
          "args": {"to": True}}], sid="b", topic="/b")

    _spec([_status_source(), producer, consumer])         # producer first: fine
    with pytest.raises(ValueError, match="nav_stuck"):
        _spec([_status_source(), consumer, producer])     # swapped: one tick stale


def test_a_step_may_read_the_key_it_writes():
    """An accumulator reading its own previous value is a real pattern and is
    unambiguous -- only a STRICTLY later producer is the bug."""
    spec = _spec([_source(
        [{"key": "nav_state", "field": "state"},
         {"key": "nav_stuck", "fn": "stuck_streak", "inputs": ["nav_stuck"],
          "on": "tick", "args": {"debounce_s": 1.0}}],
        sid="status", topic="/s", type_="std_msgs/msg/String")])
    assert spec.tick_steps()[0].inputs == ("nav_stuck",)


def test_every_shipped_descriptor_declares_its_steps_in_dependency_order():
    for name in adapter_spec.available():
        adapter_spec.load(name)                           # raises if it does not


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


def test_an_int_defaulted_key_is_still_a_measurement():
    """`isinstance(default, float)` silently exempted every `"default": 0` key --
    which on the shipped schema is num_waypoints and current_target_idx."""
    schema = {"linear_vel": {"doc": "int, counts", "default": 0}}
    spec = _spec([_source([{"key": "linear_vel", "field": "v"}], sid="s",
                          expected_hz=30.0)], schema=schema, tick_hz=1.0)
    assert any("linear_vel" in w and "discarded" in w for w in spec.warnings()), (
        spec.warnings())


def test_a_bool_defaulted_key_is_not_a_measurement():
    """bool is a subclass of int, so widening the gate must not sweep flags in."""
    schema = {"nav_stuck": {"doc": "bool", "default": False}}
    spec = _spec([_source([{"key": "nav_stuck", "field": "f"}], sid="s",
                          expected_hz=30.0)], schema=schema, tick_hz=1.0)
    assert not any("discarded" in w for w in spec.warnings()), spec.warnings()


def test_a_source_with_no_declared_rate_says_the_discard_check_cannot_run():
    """The other half of the same hole: expected_hz defaults to tick_hz, so the rate
    test can never trip on a descriptor that declares no rates -- which is every
    descriptor shipped today. Reporting nothing there is a clean bill of health for
    exactly the file the check exists to catch."""
    spec = _spec([_range_source()], tick_hz=1.0)          # no expected_hz
    assert any("min_range" in w and "points" in w and "expected_hz" in w
               for w in spec.warnings()), spec.warnings()


def test_real_g1_min_range_is_warned_about():
    """The descriptor with the exact bug the warning exists to surface: a monocular
    depth cloud, folded with `last`, against a 1 Hz tick, with no rate declared."""
    warns = adapter_spec.load("real_g1").warnings()
    assert any("min_range" in w and "points" in w for w in warns), warns


def test_declaring_a_rate_or_a_fold_silences_it():
    assert not any(
        "min_range" in w and "expected_hz" in w
        for w in _spec([_range_source(aggregate="min")]).warnings())
    quiet = _spec([_range_source(expected_hz=1.0)], tick_hz=1.0).warnings()
    assert not any("min_range" in w for w in quiet), quiet


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
        {"keys": ["min_range"], "aggregate": "last", "threshold": None,
         "on": "message"}]


def test_manifest_reports_the_resolved_fold_policy():
    m = _spec([_range_source(aggregate="min")]).manifest()
    assert m["sources"][0]["steps"][0]["aggregate"] == "min"


def test_manifest_publishes_debounce_ticks_only_for_a_tick_debounce():
    """A hand-written `args.threshold` on a MESSAGE-step counts messages, so ten
    messages inside one tick trip it. Announcing that as `debounce_ticks` tells the
    frontend a ten-TICK debounce and is simply false -- and every shipped descriptor
    still carries exactly that step."""
    spec = _spec([_source(
        [{"key": "nav_state", "field": "state"},
         {"key": "nav_stuck", "fn": "stuck_streak", "inputs": ["nav_state"],
          "args": {"threshold": 10}}],
        sid="status", topic="/status", type_="std_msgs/msg/String")])

    assert spec.resolved_thresholds() == {}, (
        "a message-counted streak was published as a tick count")
    assert "debounce_ticks" not in spec.manifest()["schema"]["nav_stuck"]

    # ...but the number the runtime actually uses is not hidden: it goes on the step,
    # beside the `on` that says what unit it is in.
    step = spec.manifest()["sources"][0]["steps"][1]
    assert step["threshold"] == 10 and step["on"] == "message"


def test_no_shipped_descriptor_announces_a_tick_debounce_it_does_not_have():
    """The regression as it exists on disk: real_g1/mujoco/isaac_lab all attach
    stuck_streak to a message-step with a hand-written threshold of 10."""
    for name in adapter_spec.available():
        spec = adapter_spec.load(name)
        schema = spec.manifest()["schema"]
        for key, entry in schema.items():
            assert "debounce_ticks" not in entry, (
                f"{name}: {key} announces a tick debounce but is counted per message")
        for src in spec.manifest()["sources"]:
            for step in src["steps"]:
                if step["threshold"] is not None:
                    assert step["on"] in ("message", "tick"), f"{name}: {step}"


def test_manifest_publishes_debounce_ticks_for_a_real_tick_debounce():
    spec = _spec([_status_source(debounce_s=10.0)], tick_hz=5.0)
    assert spec.manifest()["schema"]["nav_stuck"]["debounce_ticks"] == 50
    step = spec.manifest()["sources"][0]["steps"][1]
    assert step["threshold"] == 50 and step["on"] == "tick"


def test_manifest_feeds_the_wire_contract_directly():
    """`api.build_adapter(**spec.manifest())` must type-check, so P2's manifest and
    P0's published payload cannot drift apart."""
    spec = _spec([_range_source(expected_hz=15.0), _status_source()])
    assert api.validate_adapter(api.build_adapter(**spec.manifest())) == []


# ----------------------------------------------------------- schema composition
#
# A shared vocabulary across the three descriptors is what makes the monitor
# EMBODIMENT-agnostic. One vocabulary that is entirely navigation's is what keeps it
# SKILL-specific. Composition is the seam between the two, so what is exercised here is
# that a fragment list behaves like the single file it replaces, plus the one thing a
# merge can do that a single file cannot: silently change what a key means.

def _fragment(tmp_path, name, keys):
    path = tmp_path / name
    path.write_text(json.dumps({"name": name.split("_")[0], "keys": keys}))
    return path


POSE_FRAGMENT = {"pos_x": {"doc": "float, metres. X in odom.", "default": 0.0}}
NAV_FRAGMENT = {"min_range": {"doc": "float, metres. Nearest obstacle.",
                              "default": 10.0}}


def _composed(tmp_path, schema, steps=None):
    """A descriptor whose `schema` is whatever the test is exercising, over a source
    that writes nothing -- so the composition is the only thing under test."""
    return adapter_spec.from_dict(
        {"name": "composed", "schema": schema,
         "sources": [_source(list(steps or []), sid="s", topic="/t")]},
        base_dir=tmp_path)


def test_a_schema_list_composes_its_fragments(tmp_path):
    """The whole point: pose keys and nav keys in one vocabulary, from two files
    neither of which had to know about the other."""
    _fragment(tmp_path, "pose_schema.json", POSE_FRAGMENT)
    _fragment(tmp_path, "nav_schema.json", NAV_FRAGMENT)
    spec = _composed(tmp_path, ["pose_schema.json", "nav_schema.json"])
    assert spec.keys() == frozenset({"pos_x", "min_range"})
    assert spec.defaults() == {"pos_x": 0.0, "min_range": 10.0}
    # ...and the prose comes along, because that is what the spec generator writes over.
    assert "odom" in spec.docs()["pos_x"]
    assert "obstacle" in spec.docs()["min_range"]


def test_a_later_fragment_overrides_an_earlier_one(tmp_path):
    """Left to right, later wins. Without this "the standard fragment, with this one
    key retuned for my robot" is not expressible and every robot forks the file."""
    _fragment(tmp_path, "nav_schema.json", NAV_FRAGMENT)
    spec = _composed(
        tmp_path,
        ["nav_schema.json",
         {"min_range": {"doc": "float, metres. Nearest obstacle.", "default": 4.0}}])
    assert spec.defaults()["min_range"] == 4.0, "the earlier fragment won"


def test_composition_is_ordered_not_a_set_union(tmp_path):
    """The same two fragments the other way round give the other answer -- which is
    what makes the order load-bearing rather than decorative."""
    _fragment(tmp_path, "a_schema.json", {"k": {"doc": "a", "default": 1.0}})
    _fragment(tmp_path, "b_schema.json", {"k": {"doc": "b", "default": 2.0}})
    assert _composed(tmp_path, ["a_schema.json", "b_schema.json"]).defaults()["k"] == 2.0
    assert _composed(tmp_path, ["b_schema.json", "a_schema.json"]).defaults()["k"] == 1.0


def test_a_meaning_changing_override_is_warned_about_rather_than_silent(tmp_path):
    """Override is allowed, but a fragment redefining what a key MEANS -- or what it
    holds before any message arrives -- is exactly the plausible-nonsense class this
    module exists to catch. It goes in warnings(), so it reaches the manifest and the
    wire instead of living only in the diff."""
    _fragment(tmp_path, "nav_schema.json", NAV_FRAGMENT)
    spec = _composed(
        tmp_path,
        ["nav_schema.json",
         {"min_range": {"doc": "float, CENTIMETRES. Nearest obstacle.",
                        "default": 1000.0}}])
    warned = [w for w in spec.warnings() if "min_range" in w and "redefined" in w]
    assert warned, spec.warnings()
    assert "doc" in warned[0] and "default" in warned[0], (
        f"the warning must name WHAT changed, not merely that something did: {warned[0]}")
    assert "nav_schema.json" in warned[0], "the warning does not name the loser"
    # ...and it is on the wire, not just in a log nobody reads.
    assert warned[0] in spec.manifest()["warnings"]


def test_an_identical_redeclaration_is_not_warned_about(tmp_path):
    """Two fragments agreeing about a key says nothing new. Warning there trains people
    to ignore the warnings, which is how the meaning-changing one above gets missed."""
    _fragment(tmp_path, "a_schema.json", dict(NAV_FRAGMENT))
    _fragment(tmp_path, "b_schema.json", dict(NAV_FRAGMENT))
    spec = _composed(tmp_path, ["a_schema.json", "b_schema.json"])
    assert not [w for w in spec.warnings() if "redefined" in w], spec.warnings()


def test_a_bare_schema_string_still_means_what_it_always_meant(tmp_path):
    """The pre-composition spelling. Every descriptor on disk used it and any one of
    them may keep using it."""
    _fragment(tmp_path, "nav_schema.json", NAV_FRAGMENT)
    bare = _composed(tmp_path, "nav_schema.json")
    listed = _composed(tmp_path, ["nav_schema.json"])
    assert bare.keys() == listed.keys() == frozenset({"min_range"})
    assert bare.defaults() == listed.defaults()
    assert not [w for w in bare.warnings() if "redefined" in w]


def test_an_inline_schema_dict_still_means_what_it_always_meant(tmp_path):
    """The other pre-composition spelling, and the one every test in this file above
    uses -- a manipulation adapter declaring its own vocabulary with no file at all."""
    inline = {"gripper_closed": {"doc": "bool, jaws shut.", "default": False}}
    spec = _composed(tmp_path, inline)
    assert spec.keys() == frozenset({"gripper_closed"})
    assert _composed(tmp_path, [inline]).keys() == spec.keys()


def test_a_fragment_list_may_mix_files_and_inline_dicts(tmp_path):
    _fragment(tmp_path, "pose_schema.json", POSE_FRAGMENT)
    spec = _composed(
        tmp_path,
        ["pose_schema.json", {"gripper_closed": {"doc": "bool.", "default": False}}])
    assert spec.keys() == frozenset({"pos_x", "gripper_closed"})


def test_a_fragment_that_does_not_exist_names_itself_and_the_adapter(tmp_path):
    """A typo'd fragment name used to be a bare FileNotFoundError out of json.loads,
    with no adapter in it -- which, with a list, does not say which of them is wrong."""
    _fragment(tmp_path, "pose_schema.json", POSE_FRAGMENT)
    with pytest.raises(ValueError, match="nav_scheme.json"):
        _composed(tmp_path, ["pose_schema.json", "nav_scheme.json"])


def test_an_empty_or_absent_schema_is_still_rejected(tmp_path):
    for schema in ([], {}, [{}]):
        with pytest.raises(ValueError, match="declares no schema"):
            _composed(tmp_path, schema)
    with pytest.raises(ValueError, match="declares no schema"):
        adapter_spec.from_dict({"name": "composed", "sources": []}, base_dir=tmp_path)


def test_a_fragment_of_the_wrong_type_is_rejected_at_load(tmp_path):
    _fragment(tmp_path, "pose_schema.json", POSE_FRAGMENT)
    with pytest.raises(ValueError, match="file name or an inline"):
        _composed(tmp_path, ["pose_schema.json", 5])


def test_a_fragment_file_with_no_keys_object_is_rejected_at_load(tmp_path):
    (tmp_path / "broken_schema.json").write_text(json.dumps({"name": "broken"}))
    with pytest.raises(ValueError, match="no 'keys' object"):
        _composed(tmp_path, ["broken_schema.json"])


def test_a_composed_schema_validates_steps_exactly_as_a_single_file_does(tmp_path):
    """Composition changes where the vocabulary comes from and nothing else: a step
    writing a key no fragment declared is still a load-time error."""
    _fragment(tmp_path, "pose_schema.json", POSE_FRAGMENT)
    _composed(tmp_path, ["pose_schema.json"],
              steps=[{"key": "pos_x", "field": "data"}])          # declared: fine
    with pytest.raises(ValueError, match="schema does not declare"):
        _composed(tmp_path, ["pose_schema.json"],
                  steps=[{"key": "pos_z", "field": "data"}])


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


# ------------------------------------------------------------- the lock, exercised
#
# The lock is the only thing between this design and silent sample loss the moment
# anyone adds a callback group, a MultiThreadedExecutor, or the server tier's network
# thread. Under the default single-threaded executor it is uncontended and these tests
# prove nothing about production -- which is the point: they are what stops someone
# removing it as dead weight.

def _run(targets, timeout=30.0):
    """Start every callable on its own thread, join them, and re-raise anything that
    escaped -- an exception in a worker thread is otherwise just a message on stderr
    and a green test."""
    errors = []

    def guard(fn):
        def run():
            try:
                fn()
            except BaseException as exc:                  # noqa: BLE001 - re-raised below
                errors.append(exc)
        return run

    threads = [threading.Thread(target=guard(fn)) for fn in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
    assert not any(t.is_alive() for t in threads), "a worker deadlocked"
    if errors:
        raise errors[0]


def test_concurrent_writers_lose_no_samples():
    """Four writers, two thousand messages each, one open window.

    CPython's GIL makes a single list append atomic, so this one may well pass with
    the lock removed -- it pins the no-loss property, not the lock. The test below is
    the one the lock is load-bearing for.
    """
    st = _state([_range_source(aggregate="min")])
    writers, per_writer = 4, 2000
    start = threading.Barrier(writers)

    def writer(i):
        def run():
            start.wait()
            for n in range(per_writer):
                st.update("points", {"range": float(i * per_writer + n)})
        return run

    with warnings.catch_warnings():
        # This test deliberately never ticks, which is exactly what the un-ticked
        # guard warns about. Filters are restored before the assertions.
        warnings.simplefilter("ignore", RuntimeWarning)
        _run([writer(i) for i in range(writers)])
        pending = st.pending_samples()

    assert pending == writers * per_writer, (
        f"{writers * per_writer - pending} sample(s) were dropped on the way into "
        f"the window")
    st.tick()
    assert st.sensor_eval()["min_range"] == 0.0
    assert st.pending_samples() == 0


def test_a_tick_concurrent_with_writers_does_not_tear_the_window():
    """The other half, and the one the lock is really for: `tick()` iterates the
    window while `update()` is writing into it.

    Each message here contributes ONE key of many, so the window's size changes as
    messages land and the fold is long enough to be preempted part-way through --
    which turns the race into a hard `RuntimeError: dictionary changed size during
    iteration` instead of an occasional lost sample nobody ever notices. The switch
    interval is shortened for the same reason: without it CPython can run the whole
    fold between two thread switches and the race simply never gets a chance.
    """
    keys = [f"k{i}" for i in range(64)]
    schema = {k: {"doc": "float", "default": 0.0} for k in keys}
    src = _source([{"key": k, "field": k} for k in keys], sid="s", topic="/s")
    st = _state([src], schema=schema)

    ticks_wanted, stop = 200, threading.Event()
    start = threading.Barrier(4)
    overlapped = []

    def writer():
        start.wait()
        i = 0
        while not stop.is_set():
            st.update("s", {keys[i % len(keys)]: 1.0})
            i += 1

    def ticker():
        start.wait()
        try:
            for _ in range(ticks_wanted):
                # A real tick is paced by a clock. Without SOME pause the ticker runs
                # all its iterations before the writers are scheduled at all, and the
                # test overlaps nothing -- which the assertion below catches.
                time.sleep(0.0005)
                st.tick()
                overlapped.append(bool(st.refreshed_keys()))
        finally:
            stop.set()

    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        with warnings.catch_warnings():
            # Spin-loop writers outrun 200 ticks by more than the un-ticked budget.
            # That is an artefact of a test with no sleep in it, not the state the
            # guard is for -- the ticker below asserts the ticks really happened.
            warnings.simplefilter("ignore", RuntimeWarning)
            _run([writer, writer, writer, ticker])
    finally:
        sys.setswitchinterval(previous_interval)

    assert st.ticks == ticks_wanted - 1, "a tick was lost or double-counted"
    assert sum(overlapped) > ticks_wanted // 2, (
        "the writers and the ticker did not actually overlap, so this proved nothing")
    st.tick()
    assert st.pending_samples() == 0
    assert set(st.sensor_eval()) == set(st.spec.keys()), "the observation lost a key"


# ------------------------------------ shipped descriptors, pinned field by field
#
# Everything below reads skill_monitor/adapters/*.json. Sabotage any one of them --
# `twist.twist.linear.x` -> `.y`, `data` -> `dta`, drop `"frame": "optical"`, point
# the status topic somewhere else -- and this section is what fails.

#: id -> (topic, type, decode, qos, tracked). A wrong topic subscribes to nothing and
#: the adapter reports its defaults forever; a wrong decode hands the steps a message
#: they cannot read; the nav2 qos is TRANSIENT_LOCAL because an action status topic
#: publishes on transitions, so a plain depth silently misses the goal you subscribed
#: after. None of that raises at load, and none of it is visible in a running system
#: except as a monitor that looks fine.
SHIPPED_SOURCES = {
    "real_g1": {
        "odom": ("/t265/odom/sample", "nav_msgs/msg/Odometry", None, 10, True),
        "goal": ("/next_waypoint", "geometry_msgs/msg/PointStamped", None, 10, False),
        "points": ("/depth_anything/points", "sensor_msgs/msg/PointCloud2",
                   "pointcloud_xyz", 10, True),
        "status": ("/path_manager/status", "std_msgs/msg/String", "json", 10, True),
        "vision": ("/vision/goal_similarity", "std_msgs/msg/Float32", None, 10, False),
    },
    "mujoco": {
        "odom": ("/odom", "nav_msgs/msg/Odometry", None, 10, True),
        "goal": ("/goal_pose", "geometry_msgs/msg/PoseStamped", None, 10, False),
        "range": ("/scan", "sensor_msgs/msg/LaserScan", "laserscan_ranges", 10, True),
        "nav2": ("/navigate_to_pose/_action/status", "action_msgs/msg/GoalStatusArray",
                 "goal_status", "action_status", False),
        "vision": ("/vision/goal_similarity", "std_msgs/msg/Float32", None, 10, False),
    },
    "isaac_lab": {
        "odom": ("/odom", "nav_msgs/msg/Odometry", None, 10, True),
        "goal": ("/goal_pose", "geometry_msgs/msg/PoseStamped", None, 10, False),
        "range": ("/g1/lidar/points", "sensor_msgs/msg/PointCloud2",
                  "pointcloud_xyz", 10, True),
        "nav2": ("/navigate_to_pose/_action/status", "action_msgs/msg/GoalStatusArray",
                 "goal_status", "action_status", False),
        "vision": ("/vision/goal_similarity", "std_msgs/msg/Float32", None, 10, False),
    },
}


def _shipped_odom(px=0.0, py=0.0, pz=1.0, vx=0.0, vy=0.0, vz=0.0,
                  wx=0.0, wy=0.0, wz=0.0, q=(0.0, 0.0, 0.0, 1.0)):
    """A full Odometry stand-in. Every component is separately settable so a test can
    make each one distinct -- a field path that reads `.y` where it should read `.x`
    is only catchable if the two hold different numbers."""
    return _ns(
        pose=_ns(pose=_ns(position=_ns(x=px, y=py, z=pz),
                          orientation=_ns(x=q[0], y=q[1], z=q[2], w=q[3]))),
        twist=_ns(twist=_ns(linear=_ns(x=vx, y=vy, z=vz),
                            angular=_ns(x=wx, y=wy, z=wz))),
    )


def test_shipped_source_topics_types_and_decoders_are_pinned():
    assert set(adapter_spec.available()) == set(SHIPPED_SOURCES), (
        "a descriptor was added or removed; pin its topics here too")
    for name, expected in SHIPPED_SOURCES.items():
        spec = adapter_spec.load(name)
        actual = {s.id: (s.topic, s.type, s.decode, s.qos, s.tracked)
                  for s in spec.sources}
        assert actual == expected, name


def test_shipped_odom_field_paths_are_pinned():
    """All six odom keys, from one message whose every component is distinct."""
    for name in adapter_spec.available():
        st = adapter_spec.SensorState(adapter_spec.load(name))
        st.update("odom", _shipped_odom(px=11.0, py=22.0, pz=0.9,
                                        vx=0.5123, vy=-7.0, vz=-8.0,
                                        wx=-3.0, wy=-4.0, wz=-0.2))
        st.tick()
        v = st.sensor_eval()
        assert v["linear_vel"] == 0.51, f"{name}: not twist.twist.linear.x"
        assert v["angular_vel"] == -0.2, f"{name}: not twist.twist.angular.z"
        assert v["base_height"] == 0.9, f"{name}: not pose.pose.position.z"
        assert v["base_roll"] == 0.0 and v["base_pitch"] == 0.0, name
        assert v["upright_flag"] == 1.0, name


# ------------------------------------------ pose and goal, across all three robots
#
# `pose_schema.json` is the fragment that makes the vocabulary skill-agnostic, so the
# claim it rests on -- all three descriptors expose the SAME keys, and every one of
# them reads the right field -- is what is pinned here.

#: The keys `pose_schema.json` contributes: where the robot is, in the odometry frame.
#: Nothing in this list mentions a goal, a waypoint or a planner, which is the whole
#: reason it is a separate fragment.
POSE_KEYS = frozenset({"pos_x", "pos_y", "pos_z", "yaw"})

#: Navigation's notion of a destination. These are nav's, not the embodiment's, so they
#: live in `nav_schema.json` and a manipulation skill composing only the pose fragment
#: never sees them.
GOAL_KEYS = frozenset({"goal_x", "goal_y", "dist_to_goal"})


def _goal_msg(name, x, y, z=0.0):
    """The commanded-goal message each descriptor's `goal` source expects: a
    PointStamped on the real robot, a PoseStamped in both sims."""
    if name == "real_g1":
        return _ns(point=_ns(x=x, y=y, z=z))
    return _ns(pose=_ns(position=_ns(x=x, y=y, z=z)))


def test_every_shipped_descriptor_exposes_the_identical_vocabulary():
    """The agnosticism claim, stated as a property. A key one descriptor has and
    another does not is a rule that silently means nothing on the other robot -- and
    `--adapter` is advertised as a swap that needs no other change."""
    vocabularies = {n: adapter_spec.load(n).keys() for n in adapter_spec.available()}
    assert len(set(vocabularies.values())) == 1, {
        n: sorted(k ^ set.intersection(*[set(v) for v in vocabularies.values()]))
        for n, k in vocabularies.items()
    }
    shared = next(iter(vocabularies.values()))
    assert POSE_KEYS <= shared, sorted(POSE_KEYS - shared)
    assert GOAL_KEYS <= shared, sorted(GOAL_KEYS - shared)


def test_pose_fragment_is_composed_by_every_shipped_descriptor():
    """Composed, not copied. If someone inlines the pose keys into nav_schema.json the
    vocabulary is unchanged and every other test here still passes -- but the fragment
    a manipulation skill would compose has quietly stopped existing."""
    for name in adapter_spec.available():
        declared = adapter_spec.load(name).raw["schema"]
        assert isinstance(declared, list), f"{name}: schema is not composed"
        assert declared == ["pose_schema.json", "nav_schema.json"], name


def test_pose_fragment_declares_no_navigation_key():
    """The fragment is only skill-agnostic if it stays that way. A `goal_x` added here
    would be inherited by every skill that wants a pose and nothing else."""
    keys, _ = adapter_spec.compose_schema(
        "pose_schema.json", skill_monitor.adapters_dir(), "pose")
    assert set(keys) == POSE_KEYS, sorted(set(keys) ^ POSE_KEYS)
    for key, entry in keys.items():
        assert entry.get("doc"), f"pose_schema.json: {key} has no doc"
        # Units and frame, per key -- the generator writes rules off this prose.
        assert "metres" in entry["doc"] or "radians" in entry["doc"], key
        assert "odometry frame" in entry["doc"].lower(), f"{key} does not name its frame"


def test_shipped_pose_field_paths_are_pinned():
    """pos_x/pos_y/pos_z off `pose.pose.position`, from a message whose components are
    all distinct -- a descriptor reading `.y` into `pos_x` loads and validates cleanly
    and puts the robot somewhere it has never been."""
    for name in adapter_spec.available():
        st = adapter_spec.SensorState(adapter_spec.load(name))
        st.update("odom", _shipped_odom(px=11.0, py=22.0, pz=0.9))
        st.tick()
        v = st.sensor_eval()
        assert v["pos_x"] == 11.0, f"{name}: not pose.pose.position.x"
        assert v["pos_y"] == 22.0, f"{name}: not pose.pose.position.y"
        assert v["pos_z"] == 0.9, f"{name}: not pose.pose.position.z"
        assert POSE_KEYS <= st.refreshed_keys(), name


@pytest.mark.parametrize("heading", [0.0, math.pi / 2, -math.pi / 2, 2.5, -2.5])
def test_shipped_yaw_is_the_heading_about_the_odometry_z_axis(heading):
    """A yaw-only quaternion is (0, 0, sin(h/2), cos(h/2)). Reading the wrong Euler
    component -- or the wrong quaternion element -- gives 0.0 for every one of these,
    which is indistinguishable from a robot that never turns."""
    q = (0.0, 0.0, math.sin(heading / 2), math.cos(heading / 2))
    for name in adapter_spec.available():
        st = adapter_spec.SensorState(adapter_spec.load(name))
        st.update("odom", _shipped_odom(q=q))
        st.tick()
        v = st.sensor_eval()
        assert v["yaw"] == pytest.approx(heading, abs=1e-3), name
        # ...and yaw is not roll or pitch: a level robot that has turned is still level.
        assert v["base_roll"] == 0.0 and v["base_pitch"] == 0.0, name
        assert v["upright_flag"] == 1.0, f"{name}: turning is not falling over"


def test_shipped_yaw_wraps_rather_than_accumulating():
    """atan2's range is (-pi, pi]. Pinned because the doc promises it and a rule
    comparing two headings has to know that -3.13 and 3.13 are neighbours."""
    for name in adapter_spec.available():
        st = adapter_spec.SensorState(adapter_spec.load(name))
        st.update("odom", _shipped_odom(
            q=(0.0, 0.0, math.sin(1.75 * math.pi), math.cos(1.75 * math.pi))))
        st.tick()
        assert -math.pi <= st.sensor_eval()["yaw"] <= math.pi, name


def test_shipped_goal_field_paths_are_pinned():
    """`/next_waypoint` is a PointStamped and both sims' `/goal_pose` is a PoseStamped,
    so the two field paths genuinely differ -- and a wrong one leaves the goal on its
    default forever, which reads as a goal at the odometry origin."""
    for name in adapter_spec.available():
        st = adapter_spec.SensorState(adapter_spec.load(name))
        st.update("goal", _goal_msg(name, x=3.0, y=-4.0, z=99.0))
        st.tick()
        v = st.sensor_eval()
        assert v["goal_x"] == 3.0, f"{name}: goal_x is not the commanded x"
        assert v["goal_y"] == -4.0, f"{name}: goal_y is not the commanded y"


def test_shipped_dist_to_goal_is_planar_distance_from_the_pose_to_the_goal():
    """Three cases the arithmetic has to get right, and one it has to ignore."""
    for name in adapter_spec.available():
        st = adapter_spec.SensorState(adapter_spec.load(name))

        # Goal directly ahead: 5 m along +X.
        st.update("odom", _shipped_odom(px=1.0, py=2.0))
        st.update("goal", _goal_msg(name, x=6.0, y=2.0))
        st.tick()
        assert st.sensor_eval()["dist_to_goal"] == 5.0, f"{name}: goal ahead"

        # Goal directly behind. Distance is unsigned: it is how far, not which way.
        st.update("odom", _shipped_odom(px=11.0, py=2.0))
        st.tick()
        assert st.sensor_eval()["dist_to_goal"] == 5.0, f"{name}: goal behind"

        # Standing on the goal: exactly zero, not an epsilon.
        st.update("odom", _shipped_odom(px=6.0, py=2.0))
        st.tick()
        assert st.sensor_eval()["dist_to_goal"] == 0.0, f"{name}: standing on the goal"

        # 3-4-5, so a mistaken abs(dx)+abs(dy) or a max() reads 7.0 or 4.0, not 5.0.
        st.update("odom", _shipped_odom(px=3.0, py=6.0))
        st.update("goal", _goal_msg(name, x=6.0, y=2.0))
        st.tick()
        assert st.sensor_eval()["dist_to_goal"] == 5.0, f"{name}: not hypot"


def test_shipped_dist_to_goal_ignores_height():
    """Planar on purpose: the z of a commanded waypoint is whatever the publisher
    stamped it at, not ground the robot has to cover. Including it would make
    "arrived" depend on the goal publisher's choice of altitude."""
    for name in adapter_spec.available():
        st = adapter_spec.SensorState(adapter_spec.load(name))
        st.update("odom", _shipped_odom(px=0.0, py=0.0, pz=0.78))
        st.update("goal", _goal_msg(name, x=3.0, y=4.0, z=25.0))
        st.tick()
        assert st.sensor_eval()["dist_to_goal"] == 5.0, f"{name}: z leaked in"


def test_shipped_dist_to_goal_is_recomputed_every_tick_as_the_robot_moves():
    """It is a tick-step, so it tracks the pose even on ticks where no goal message
    arrives -- a goal topic that publishes once must not freeze the distance."""
    for name in adapter_spec.available():
        st = adapter_spec.SensorState(adapter_spec.load(name))
        st.update("goal", _goal_msg(name, x=10.0, y=0.0))         # once, and never again
        seen = []
        for x in (0.0, 2.0, 4.0, 9.5):
            st.update("odom", _shipped_odom(px=x))
            st.tick()
            seen.append(st.sensor_eval()["dist_to_goal"])
        assert seen == [10.0, 8.0, 6.0, 0.5], name


def test_shipped_goal_keys_hold_their_defaults_when_no_goal_arrives():
    """A silent goal topic must leave the keys at their defaults and the fold intact.
    The failure this pins is not a wrong number, it is a TypeError out of the middle of
    tick() on a robot that has simply not been given a mission yet."""
    for name in adapter_spec.available():
        spec = adapter_spec.load(name)
        st = adapter_spec.SensorState(spec)
        assert st.sensor_eval()["goal_x"] == 0.0, name
        assert st.sensor_eval()["goal_y"] == 0.0, name
        assert st.sensor_eval()["dist_to_goal"] == 0.0, name

        st.update("odom", _shipped_odom(px=3.0, py=4.0))          # odom only
        st.tick()                                                 # must not raise
        v = st.sensor_eval()
        assert v["goal_x"] == 0.0 and v["goal_y"] == 0.0, f"{name}: goal invented"
        # With no goal commanded the goal keys are still the odometry ORIGIN, so this
        # is the distance home -- documented as such, and why an "arrived" rule needs
        # more than a small dist_to_goal. P12's `has_goal` is what will separate them.
        assert v["dist_to_goal"] == 5.0, name
        assert "goal" not in st.refreshed_sources(), (
            f"{name}: a source that published nothing is reported as fresh")
        assert not (GOAL_KEYS & st.refreshed_keys()), (
            f"{name}: goal keys claim to have been observed")


# --------------------------------------------------------- planner independence
#
# The hard project rule, which docs/packages/P7-frontend.md already states as though it
# were enforced ("they may only come from odometry and the commanded goals, never from
# the planner's self-report") and P12 lists as a test that does not exist yet: the
# monitor reads the ROBOT's own data and the COMMANDED target, never the navigation
# algorithm's account of how it is doing.
#
# The six keys already coming off /path_manager/status -- nav_state, nav_stuck,
# mission_finished, num_waypoints, current_target_idx, nav_mode -- are pre-existing
# debt that P12 removes wholesale. They are not licence to add a seventh, and position
# and goal are precisely where it would be easiest: a planner status JSON usually
# carries its current target already, and wiring goal_x to it would be one line, would
# load cleanly, and would blind the monitor to exactly the errors the planner makes.


def _is_planner_self_report(topic: str, type_: str) -> bool:
    """Whether a topic is the navigation algorithm talking about ITSELF.

    Structural rather than an allow-list of names, so a descriptor wired to a planner
    nobody has heard of yet is caught too: anything whose last path segment is `status`
    (TRAV's /path_manager/status and any other planner's equivalent), or an action
    server's status -- Nav2's GoalStatusArray being the same self-report for the stack
    TRAV replaced, matched by TYPE as well as by name so renaming the topic does not
    launder it.
    """
    return (topic.rstrip("/").rsplit("/", 1)[-1] == "status"
            or type_ == "action_msgs/msg/GoalStatusArray")


def _planner_sourced_keys(spec) -> dict:
    """key -> the planner-status source ids that write it, for one loaded spec."""
    out: dict = {}
    for src in spec.sources:
        if not _is_planner_self_report(src.topic, src.type):
            continue
        for step in src.steps:
            for key in step.keys:
                out.setdefault(key, set()).add(f"{src.id} ({src.topic})")
    return out


def test_no_position_or_goal_key_is_sourced_from_a_planner_status_topic():
    """The guard. Wire goal_x to /path_manager/status and this is what fails."""
    protected = POSE_KEYS | GOAL_KEYS
    for name in adapter_spec.available():
        spec = adapter_spec.load(name)
        assert protected <= set(spec.keys()), f"{name}: the guard protects nothing"
        offending = {k: v for k, v in _planner_sourced_keys(spec).items()
                     if k in protected}
        assert not offending, (
            f"{name}: {sorted(offending)} come from the planner's own status stream "
            f"({offending}). Position comes from odometry and the goal from the "
            f"COMMANDED target; the planner's account of how it is doing is not an "
            f"observation of the robot")


def test_the_planner_independence_guard_is_not_vacuous():
    """Every shipped descriptor still HAS a planner-status source, so the guard above
    is passing because the protected keys avoid it and not because the predicate never
    matches anything. The day that stops being true, P12 has landed and this whole
    section is rewritten -- but until then a silently-inert guard is worse than none."""
    matched = {
        name: sorted(s.id for s in adapter_spec.load(name).sources
                     if _is_planner_self_report(s.topic, s.type))
        for name in adapter_spec.available()
    }
    assert all(matched.values()), matched
    # ...and it matches the two families separately: TRAV's status JSON on the robot,
    # Nav2's action status in both sims.
    assert matched["real_g1"] == ["status"]
    assert matched["mujoco"] == matched["isaac_lab"] == ["nav2"]


def test_the_planner_independence_guard_catches_the_regression_it_exists_for():
    """The guard is only worth having if it fails on the change it forbids. This is
    that change: goal_x read straight out of the planner's status JSON."""
    schema, _ = adapter_spec.compose_schema(
        ["pose_schema.json", "nav_schema.json"], skill_monitor.adapters_dir())
    sabotaged = adapter_spec.from_dict({
        "name": "sabotaged", "schema": dict(schema),
        "defaults": {k: v.get("default") for k, v in schema.items()},
        "sources": [_source(
            [{"key": "goal_x", "field": "target_x", "default": 0.0},
             {"key": "pos_x", "field": "robot_x", "default": 0.0}],
            sid="status", topic="/path_manager/status",
            type_="std_msgs/msg/String", decode="json")],
    })
    offending = _planner_sourced_keys(sabotaged)
    assert set(offending) & (POSE_KEYS | GOAL_KEYS) == {"goal_x", "pos_x"}

    # ...and by TYPE, not only by the topic's name -- renaming the topic to something
    # innocuous must not get it past the guard.
    renamed = adapter_spec.from_dict({
        "name": "renamed", "schema": dict(schema),
        "defaults": {k: v.get("default") for k, v in schema.items()},
        "sources": [_source([{"key": "goal_y", "fn": "const", "args": {"value": 1.0}}],
                            sid="nav2", topic="/where_am_i_going",
                            type_="action_msgs/msg/GoalStatusArray")],
    })
    assert set(_planner_sourced_keys(renamed)) == {"goal_y"}


def test_shipped_upright_flag_falls_on_height_and_on_tilt():
    for name in adapter_spec.available():
        st = adapter_spec.SensorState(adapter_spec.load(name))

        st.update("odom", _shipped_odom(pz=0.2))          # collapsed on the floor
        st.tick()
        assert st.sensor_eval()["upright_flag"] == 0.0, name
        assert st.sensor_eval()["base_height"] == 0.2, name

        half = math.sin(0.9 / 2), math.cos(0.9 / 2)       # rolled over, height fine
        st.update("odom", _shipped_odom(pz=1.0, q=(half[0], 0.0, 0.0, half[1])))
        st.tick()
        v = st.sensor_eval()
        assert v["upright_flag"] == 0.0, name
        assert v["base_roll"] == pytest.approx(0.9, abs=1e-3), name


def test_real_g1_points_source_requests_the_optical_remap():
    """real_g1.json asks for `"frame": "optical"` on /depth_anything/points. Drop that
    one key and the descriptor still loads, still validates, and reads a wall two
    metres ahead as an empty corridor."""
    st = adapter_spec.SensorState(adapter_spec.load("real_g1"))

    # Optical frame is (x right, y down, z forward): a wall 2 m ahead at chest height
    # is (0, -0.8, 2.0). Unremapped, its z is 2.0, outside the 0.1-1.5 m band, so it
    # is discarded as ceiling and min_range reads 10.0 -- "nothing detected".
    st.update("points", [(0.0, -0.8, 2.0)])
    st.tick()
    assert st.sensor_eval()["min_range"] == 2.0, "the optical remap is not being applied"

    st.update("points", [(0.0, 1.1, 0.5)])                # ground, outside the band
    st.tick()
    assert st.sensor_eval()["min_range"] == 10.0


def test_isaac_lab_range_source_does_not_remap():
    """The complement, and the documented difference between the two descriptors:
    /g1/lidar/points is assumed Z-up body-planar already."""
    st = adapter_spec.SensorState(adapter_spec.load("isaac_lab"))

    st.update("range", [(2.0, 0.0, 0.8)])                  # body frame: 2 m ahead
    st.tick()
    assert st.sensor_eval()["min_range"] == 2.0

    st.update("range", [(0.0, -0.8, 2.0)])                 # the optical spelling
    st.tick()
    assert st.sensor_eval()["min_range"] == 10.0, "isaac_lab grew an optical remap"


def test_mujoco_range_source_ignores_the_no_return_encodings():
    st = adapter_spec.SensorState(adapter_spec.load("mujoco"))
    # inf/NaN/0.0 are LaserScan's "no return", not obstacles at 0 m.
    st.update("range", [float("inf"), 0.0, float("nan"), 3.25])
    st.tick()
    assert st.sensor_eval()["min_range"] == 3.25
    st.update("range", [float("inf"), 0.0])
    st.tick()
    assert st.sensor_eval()["min_range"] == 10.0


def test_shipped_vision_source_reads_the_float32_data_field():
    """`std_msgs/msg/Float32` carries its value in `data` and nowhere else, and the
    step declares no default -- so a typo makes the key silently hold 0.0, which
    reads as "the goal is not in view" for the whole run."""
    for name in adapter_spec.available():
        st = adapter_spec.SensorState(adapter_spec.load(name))
        st.update("vision", _ns(data=0.8712))
        st.tick()
        assert st.sensor_eval()["image_similarity_to_goal"] == 0.871, name
        assert st.refreshed_keys() == {"image_similarity_to_goal"}, name


def test_real_g1_status_json_field_paths_and_casts_are_pinned():
    """The planner's own status stream is what P12 redesigns -- but it SHIPS today and
    it runs today, and until it is replaced a typo in one of these field names is a
    monitor reporting the step default as if it were an observation. When P12 lands,
    this test is rewritten with the schema; it is not deleted ahead of it.

    The casts are pinned with values that need them. `path_manager` is JSON over a
    `std_msgs/String`, so a number arriving as `"3"` is exactly what `cast: int` is
    there for -- and with the cast dropped the key holds a string that every numeric
    rule then compares wrongly.
    """
    st = adapter_spec.SensorState(adapter_spec.load("real_g1"))
    st.update("status", {"mode": "AUTOMATIC", "state": "following", "finished": 0,
                         "num_waypoints": "3", "current_target_idx": "1"})
    st.tick()
    v = st.sensor_eval()
    assert v["nav_mode"] == "AUTOMATIC", "not the 'mode' field"
    assert v["nav_state"] == "following", "not the 'state' field"
    assert v["mission_finished"] is False, "not the 'finished' field, or cast dropped"
    assert v["num_waypoints"] == 3, "cast: int dropped on num_waypoints"
    assert v["current_target_idx"] == 1, "cast: int dropped on current_target_idx"

    st.update("status", {"finished": 1})
    st.tick()
    assert st.sensor_eval()["mission_finished"] is True, "cast: bool dropped"


def test_real_g1_status_step_defaults_are_pinned():
    """An absent field falls back to the step's declared default rather than blanking
    the key -- and those defaults are the "nothing has happened yet" reading every
    rule is written against."""
    st = adapter_spec.SensorState(adapter_spec.load("real_g1"))
    st.update("status", {})                               # every field absent
    st.tick()
    v = st.sensor_eval()
    assert v["nav_mode"] == "MANUAL"
    assert v["nav_state"] == "waiting_inputs"
    assert v["mission_finished"] is False
    assert v["num_waypoints"] == 0 and v["current_target_idx"] == 0


def test_real_g1_nav_stuck_debounces_at_the_declared_threshold():
    """real_g1 still counts MESSAGES, deliberately -- the migration to `on: "tick"`
    plus `debounce_s` lands with the schema redesign. Until then the shipped number is
    10 and the descriptor is the only place it is written down: dropping it to 3 makes
    nav_stuck fire in under a third of the intended window, and nothing else notices.
    """
    st = adapter_spec.SensorState(adapter_spec.load("real_g1"))
    for _ in range(9):
        st.update("status", {"state": "no_path_found"})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is False, "fired before the 10th message"

    st.update("status", {"state": "no_path_found"})
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is True, "did not fire on the 10th"

    st.update("status", {"state": "following"})           # recovery clears it at once
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is False


@pytest.mark.parametrize("name", ["mujoco", "isaac_lab"])
def test_sim_nav2_source_mapping_is_pinned(name):
    """The sim descriptors translate Nav2's status into the planner vocabulary with
    three steps whose ARGUMENTS carry the meaning: `const` says the sim is always
    under automatic control, and `eq.to` says which state counts as mission-complete.
    Both are plain strings in JSON that nothing else checks.
    """
    st = adapter_spec.SensorState(adapter_spec.load(name))
    assert st.sensor_eval()["nav_mode"] == "MANUAL", "the schema default, pre-message"

    st.update("nav2", None)                               # empty status_list
    st.tick()
    assert st.sensor_eval()["nav_state"] == "waiting_inputs", (
        "an empty status_list overwrote the state instead of leaving it alone")

    st.update("nav2", 2)                                  # executing
    st.tick()
    v = st.sensor_eval()
    assert v["nav_state"] == "following"
    assert v["nav_mode"] == "AUTOMATIC", "const value is not AUTOMATIC"
    assert v["mission_finished"] is False

    st.update("nav2", 4)                                  # succeeded
    st.tick()
    v = st.sensor_eval()
    assert v["nav_state"] == "finished"
    assert v["mission_finished"] is True, "eq.to is not 'finished'"

    st.update("nav2", 6)                                  # aborted
    st.tick()
    v = st.sensor_eval()
    assert v["nav_state"] == "no_path_found"
    assert v["mission_finished"] is False


@pytest.mark.parametrize("name", ["mujoco", "isaac_lab"])
def test_sim_nav_stuck_debounces_at_the_declared_threshold(name):
    st = adapter_spec.SensorState(adapter_spec.load(name))
    for _ in range(9):
        st.update("nav2", 6)                              # aborted -> no_path_found
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is False, "fired before the 10th message"
    st.update("nav2", 6)
    st.tick()
    assert st.sensor_eval()["nav_stuck"] is True


def test_real_g1_points_height_band_is_pinned():
    """`z_lo`/`z_hi` decide what counts as an obstacle at all. Narrowing 0.1-1.5 to
    0.3-0.9 blinds the robot to anything outside a 60 cm slab -- a kerb, a table edge,
    a low bar -- while the optical-remap test above stays green, because a wall at
    chest height is inside every plausible band.

    Written in the OPTICAL frame the descriptor declares, so it pins the band and the
    remap together: body (x fwd, y left, z up) is optical (z, -x, -y).
    """
    st = adapter_spec.SensorState(adapter_spec.load("real_g1"))

    # body z = 0.2 -- above the 0.1 floor, below a narrowed 0.3 one. 2 m ahead.
    st.update("points", [(0.0, -0.2, 2.0)])
    st.tick()
    assert st.sensor_eval()["min_range"] == 2.0, "the 0.1 m floor moved up"

    # body z = 1.4 -- under the 1.5 ceiling, above a narrowed 0.9 one. 3 m ahead.
    st.update("points", [(0.0, -1.4, 3.0)])
    st.tick()
    assert st.sensor_eval()["min_range"] == 3.0, "the 1.5 m ceiling moved down"

    # ...and the band still EXCLUDES what it is there to exclude: floor and ceiling.
    st.update("points", [(0.0, -0.05, 2.0), (0.0, -1.6, 2.0)])
    st.tick()
    assert st.sensor_eval()["min_range"] == 10.0, "the band widened"


def test_isaac_lab_range_height_band_is_pinned():
    """The same band, in the body frame isaac_lab's cloud is already in."""
    st = adapter_spec.SensorState(adapter_spec.load("isaac_lab"))

    st.update("range", [(2.0, 0.0, 0.2)])
    st.tick()
    assert st.sensor_eval()["min_range"] == 2.0, "the 0.1 m floor moved up"

    st.update("range", [(3.0, 0.0, 1.4)])
    st.tick()
    assert st.sensor_eval()["min_range"] == 3.0, "the 1.5 m ceiling moved down"

    st.update("range", [(2.0, 0.0, 0.05), (2.0, 0.0, 1.6)])
    st.tick()
    assert st.sensor_eval()["min_range"] == 10.0, "the band widened"


#: Adapter-level `defaults` overrides, per descriptor. Nav2 reports no waypoint count,
#: so the sim descriptors declare the single implicit goal `send_goal.py` sends; a rule
#: like `current_target_idx < num_waypoints` reads differently at any other number, and
#: real_g1 gets the real count off its status topic and must NOT override.
SHIPPED_DEFAULT_OVERRIDES = {
    "real_g1": {},
    "mujoco": {"num_waypoints": 1},
    "isaac_lab": {"num_waypoints": 1},
}


def test_shipped_adapter_level_defaults_are_pinned():
    assert set(adapter_spec.available()) == set(SHIPPED_DEFAULT_OVERRIDES)
    for name, overrides in SHIPPED_DEFAULT_OVERRIDES.items():
        held = adapter_spec.SensorState(adapter_spec.load(name)).sensor_eval()
        assert held["num_waypoints"] == overrides.get("num_waypoints", 0), name
        for key, value in overrides.items():
            assert held[key] == value, f"{name}: {key}"


#: What the evaluator's console block shows for each robot. Emptying it, or dropping a
#: key from it, leaves an operator staring at a monitor that reports nothing -- and no
#: other test looks at this list.
SHIPPED_DESCRIBE_KEYS = {
    "real_g1": ["min_range", "nav_mode", "nav_state", "dist_to_goal",
                "image_similarity_to_goal"],
    "mujoco": ["min_range", "nav_state", "dist_to_goal", "image_similarity_to_goal"],
    "isaac_lab": ["min_range", "nav_state", "dist_to_goal", "image_similarity_to_goal"],
}


def test_shipped_describe_lists_are_pinned():
    assert set(adapter_spec.available()) == set(SHIPPED_DESCRIBE_KEYS)
    for name, keys in SHIPPED_DESCRIBE_KEYS.items():
        spec = adapter_spec.load(name)
        assert spec.describe_keys == keys, name
        assert set(keys) <= set(spec.keys()), f"{name}: describes a key it cannot read"


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
